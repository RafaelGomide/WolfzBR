import importlib
import io
from pathlib import Path

import pytest

from wolfz.core.ingest import CellMatrix, CellType, SheetStructure, read_sheet
from wolfz.core.ingest.excel import list_sheets, read_sheet_raw
from wolfz.core.ingest.structure import (
    TAIL_ROWS,
    MergedRange,
    _xml_das_janelas,
    read_xlsx_structure,
    sample_windows,
)

structure_mod = importlib.import_module("wolfz.core.ingest.structure")


def test_estrutura_xlsx(relatorio_xlsx):
    data = read_sheet(relatorio_xlsx)
    s = data.structure.to_dict()
    assert s["sheet"] == "Vendas"
    assert s["formatting"] is True
    assert s["merged"] == ["C3:E3"]
    assert s["bold"] == ["C3", "C5", "D5", "E5", "C8"]
    assert s["formulas"] == {"D8": "=SUM(D6:D7)"}
    assert s["types"]["D6"] == "number"
    assert s["types"]["E6"] == "date"
    assert s["types"]["C6"] == "text"
    assert s["warnings"] == []


def test_estrutura_so_nas_primeiras_e_ultimas_linhas(relatorio_xlsx):
    data = read_sheet(relatorio_xlsx, head_rows=4, tail_rows=2)
    s = data.structure
    assert s.sampled_rows == [(0, 3), (8, 9)]
    rows_seen = {r for r, _ in s.types} | {r for r, _ in s.bold}
    assert rows_seen <= {0, 1, 2, 3, 8, 9}
    assert (4, 2) not in s.bold  # cabeçalho na linha 5 ficou fora da amostra
    # Mesclagens vêm do arquivo inteiro: são poucas e baratas.
    assert s.merged == [MergedRange(2, 2, 2, 4)]


def test_estrutura_xls(exemplo_xls):
    s = read_sheet(exemplo_xls).structure
    assert s.formatting is False
    assert [m.to_a1() for m in s.merged] == ["B2:D2"]
    assert s.types[(4, 2)] is CellType.NUMBER
    assert s.types[(4, 3)] is CellType.DATE
    assert ".xls" in s.warnings[0]


def test_estrutura_ods_sem_mesclagem(exemplo_ods):
    s = read_sheet(exemplo_ods).structure
    assert s.merged == []
    assert ".ods" in s.warnings[0]


def test_formatacao_ilegivel_degrada(relatorio_xlsx, monkeypatch):
    def falha(*args, **kwargs):
        raise RuntimeError("estilo exótico")

    monkeypatch.setattr("wolfz.core.ingest.excel.read_xlsx_structure", falha)
    data = read_sheet(relatorio_xlsx)
    assert data.frame.height == 10
    assert data.structure.formatting is False
    assert data.structure.warnings


def test_estrutura_ida_e_volta_json(relatorio_xlsx):
    s = read_sheet(relatorio_xlsx).structure
    again = SheetStructure.from_dict(s.to_dict())
    assert again == s


@pytest.mark.parametrize(
    ("total", "head", "tail", "expected"),
    [
        (0, 50, 20, []),
        (10, 50, 20, [(0, 9)]),
        (100, 50, 20, [(0, 49), (80, 99)]),
        (60, 50, 20, [(0, 49), (50, 59)]),
        (5, 0, 2, [(3, 4)]),
    ],
)
def test_janelas_de_amostra(total, head, tail, expected):
    assert sample_windows(total, head, tail) == expected


def test_cell_matrix(relatorio_xlsx):
    data = read_sheet(relatorio_xlsx)
    m = CellMatrix.from_frame(data.frame, data.structure)
    assert m.height == 10
    assert m.col_offset == 2
    assert m.width == 3
    titulo = m.cell(2, 2)
    assert (titulo.value, titulo.type, titulo.merged, titulo.bold) == (
        "Relatório de vendas",
        CellType.TEXT,
        True,
        True,
    )
    assert m.cell(2, 3).merged  # parte coberta da mesclagem
    assert m.cell(2, 3).type is CellType.EMPTY
    assert m.cell(4, 3).bold
    assert m.cell(5, 3).type is CellType.NUMBER
    assert m.cell(5, 2).type is CellType.TEXT  # CPF guardado como texto no Excel
    assert m.cell(5, 4).type is CellType.DATE
    assert m.cell(5, 0).type is CellType.EMPTY  # coluna A, antes da grade
    assert m.cell(5, 99).type is CellType.EMPTY
    assert [r for r, _ in m] == list(range(10))


def test_cell_matrix_linhas_escolhidas(relatorio_xlsx):
    data = read_sheet(relatorio_xlsx)
    m = CellMatrix.from_frame(data.frame, data.structure, rows=[4, 7, 50])
    assert m.row_numbers == [4, 7]
    assert m.row(7)[0].value == "Total"
    with pytest.raises(KeyError):
        m.row(5)


def test_cell_matrix_sem_estrutura_infere_tipo(exemplo_ods):
    df = read_sheet(exemplo_ods).frame
    m = CellMatrix.from_frame(df)
    assert m.cell(3, 1).type is CellType.NUMBER
    assert m.cell(0, 0).type is CellType.EMPTY


def test_cell_matrix_vazia():
    import polars as pl

    m = CellMatrix.from_frame(pl.DataFrame())
    assert (m.height, m.width) == (0, 0)


def test_cell_matrix_valida_tamanhos():
    with pytest.raises(ValueError):
        CellMatrix([[]], [])


# XML da aba recortado nas janelas (FH.B2)

XLSX_DO_CORPUS = sorted((Path(__file__).resolve().parents[1] / "corpus").glob("*/original.xlsx"))


def _estrutura(caminho, monkeypatch=None, recortar=True, tail_rows=TAIL_ROWS):
    if not recortar:
        monkeypatch.setattr(structure_mod, "_xml_das_janelas", lambda xml, windows: None)
    aba = list_sheets(caminho, "xlsx", dimensions=False)[0].name
    altura = read_sheet_raw(caminho, aba).height
    return read_xlsx_structure(caminho, aba, altura, tail_rows=tail_rows).to_dict()


@pytest.mark.parametrize("caminho", XLSX_DO_CORPUS, ids=lambda p: p.parent.name)
def test_xml_recortado_da_a_mesma_estrutura(caminho, monkeypatch):
    rapido = _estrutura(caminho, tail_rows=3)
    with monkeypatch.context() as m:
        completo = _estrutura(caminho, m, recortar=False, tail_rows=3)
    assert rapido == completo


@pytest.mark.parametrize("caminho", XLSX_DO_CORPUS[:4], ids=lambda p: p.parent.name)
def test_xml_recortado_com_blocos_pequenos(caminho, monkeypatch):
    """Linha cortada entre dois blocos de leitura."""
    esperado = _estrutura(caminho, tail_rows=3)
    monkeypatch.setattr(structure_mod, "_BLOCO_XML", 7)
    assert _estrutura(caminho, tail_rows=3) == esperado


def test_xml_recortado_guarda_so_as_janelas():
    xml = (
        b'<worksheet><dimension ref="A1:A5"/><sheetData>'
        + b"".join(b'<row r="%d"><c r="A%d"><v>%d</v></c></row>' % (n, n, n) for n in range(1, 6))
        + b'<row r="6"/></sheetData><mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>'
    )
    recortado = _xml_das_janelas(io.BytesIO(xml), [(0, 0), (4, 5)])
    assert recortado == (
        b'<worksheet><dimension ref="A1:A5"/><sheetData>'
        b'<row r="1"><c r="A1"><v>1</v></c></row><row r="5"><c r="A5"><v>5</v></c></row><row r="6"/>'
        b'</sheetData><mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>'
    )


@pytest.mark.parametrize(
    "xml",
    [
        b"<worksheet><sheetData><row><c><v>1</v></c></row></sheetData></worksheet>",  # linha sem r
        b'<x:worksheet><x:sheetData><x:row r="1"/></x:sheetData></x:worksheet>',  # prefixo
        b"<worksheet><sheetData/></worksheet>",
        b'<worksheet><sheetData><row r="1">',  # cortado
    ],
)
def test_xml_fora_do_padrao_volta_para_a_leitura_de_sempre(xml):
    assert _xml_das_janelas(io.BytesIO(xml), [(0, 10)]) is None

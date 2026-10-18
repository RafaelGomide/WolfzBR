"""Leitura da entrada no script Python exportado (F2.B1).

Estas funções são copiadas para dentro do script (``bundle``), junto com a
detecção de encoding e separador de ``wolfz.core.ingest.csv``: o script lê
o arquivo do mesmo jeito que ``wolfz.run`` (``read_input``), sem depender
do WolfzBR. Planilha vem como grade (colunas ``A``, ``B``, …; linha i =
linha i + 1 da aba); CSV vem com cabeçalho, a não ser que a receita comece
pela grade.

O teste ``test_python.py`` confere, arquivo a arquivo do corpus, que a
leitura daqui é igual à do motor.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from wolfz.core.ingest.csv import detect_encoding, detect_separator, grid_width
from wolfz.core.ingest.excel import _text

AMOSTRA = 64_000
PLANILHAS = (".xlsx", ".xlsm", ".xls", ".ods")


def letra_coluna(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    i += 1
    while i:
        i, resto = divmod(i - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def ler_csv(caminho: str, grade: bool) -> pl.DataFrame:
    """CSV todo como texto, com encoding e separador detectados."""
    bruto = Path(caminho).read_bytes()
    encoding = detect_encoding(caminho)
    amostra = bruto[:AMOSTRA].decode(encoding, errors="replace")
    separador = detect_separator(amostra)
    texto = bruto.decode(encoding, errors="replace")
    if grade:
        # Cabeçalho sintético com as letras: a largura é a da linha mais
        # larga do começo do arquivo, não a do título da primeira linha.
        largura = grid_width(amostra, separador)
        texto = separador.join(letra_coluna(i) for i in range(largura)) + "\n" + texto
    return pl.read_csv(
        texto.encode("utf-8"),
        separator=separador,
        has_header=True,
        infer_schema=False,
        quote_char='"',
        truncate_ragged_lines=True,
    )


def ler_planilha(caminho: str, aba: str | None, aba_regex: str | None) -> pl.DataFrame:
    """Aba de .xlsx, .xls ou .ods como grade de texto. Sem ``aba``, a
    primeira visível; se ``aba`` não existe, a primeira que casa com
    ``aba_regex`` (o nome mudou de um mês para o outro).

    Como no WolfzBR: .xlsx pelo fastexcel; .xls e .ods pelo python-calamine,
    com os valores convertidos para o mesmo texto que o fastexcel produz."""
    from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum

    with CalamineWorkbook.from_path(caminho) as livro:
        abas = [m for m in livro.sheets_metadata if m.typ == SheetTypeEnum.WorkSheet]
        nomes = [m.name for m in abas]
        if aba is None:
            visiveis = [m.name for m in abas if m.visible == SheetVisibleEnum.Visible]
            aba = (visiveis or nomes)[0]
        elif aba not in nomes and aba_regex is not None:
            aba = next((n for n in nomes if re.fullmatch(aba_regex, n)), aba)
        if Path(caminho).suffix.lower() != ".xlsx":
            folha = livro.get_sheet_by_name(aba)
            linhas = folha.to_python(skip_empty_area=False)
            if not folha.start:
                return pl.DataFrame()
            largura = max((len(r) for r in linhas), default=0)
            dados = {
                letra_coluna(c): [_text(r[c]) if c < len(r) else None for r in linhas]
                for c in range(folha.start[1], largura)
            }
            return pl.DataFrame(dados, schema=dict.fromkeys(dados, pl.String))

    import fastexcel

    planilha = fastexcel.read_excel(caminho).load_sheet(aba, header_row=None, dtypes="string", skip_rows=0)
    colunas = planilha.available_columns()
    df = planilha.to_polars()
    if not colunas or df.width == 0:
        return pl.DataFrame()
    return df.rename({c.name: letra_coluna(c.absolute_index) for c in colunas})


def ler_entrada(caminho: str, aba: str | None, aba_regex: str | None, grade: bool) -> pl.DataFrame:
    """Lê a entrada como a receita espera, tudo como texto."""
    if Path(caminho).suffix.lower() in PLANILHAS:
        return ler_planilha(caminho, aba, aba_regex)
    return ler_csv(caminho, grade)

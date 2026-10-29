"""Juntar abas numa tabela só (F3 da 1.1, ADR-11, R5, R6).

A receita roda inteira em cada aba e as tabelas são empilhadas no fim. Nada
é unido em silêncio: coluna que falta, coluna a mais, nome quase igual e
tipo diferente aparecem como aviso ou erro.
"""

import time

import polars as pl
import pytest
from openpyxl import Workbook

import wolfz
from wolfz.core.engine import ErroAoJuntar, StepError
from wolfz.core.engine.juntar import casa_inteira, empilhar
from wolfz.core.ingest import IngestError
from wolfz.core.recipe import RecipeError, dumps_recipe, recipe_from_dict


def planilha(path, abas: dict[str, list[list]], ocultas: dict[str, str] | None = None):
    wb = Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(linha)
    for nome, estado in (ocultas or {}).items():
        wb[nome].sheet_state = estado
    wb.save(path)
    return path


def _mes(nome, n, colunas=("Vendedor", "Valor")):
    return [[f"Vendas {nome}"], list(colunas), *[[f"V{i}", str(i * 10)][: len(colunas)] for i in range(n)]]


def receita(combine=None, *passos, sheet="JAN"):
    source = {"type": "excel", "sheet": sheet}
    if combine is not None:
        source["combine_sheets"] = combine
    padrao = [{"op": "select_range", "start": "A2"}, {"op": "header_rows"}]
    return recipe_from_dict(
        {
            "wolfz_version": "1.1",
            "name": "vendas",
            "created_at": "2026-01-01T00:00:00Z",
            "source": source,
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate([*padrao, *passos], 1)],
        }
    )


@pytest.fixture
def trimestre(tmp_path):
    return planilha(
        tmp_path / "tri.xlsx",
        {
            "JAN": _mes("JAN", 3),
            "FEV": _mes("FEV", 2),
            "Base": _mes("Base", 1),
            "MAR": _mes("MAR", 4),
            "Config": _mes("Config", 1),
        },
        {"Base": "hidden", "Config": "veryHidden"},
    )


def test_junta_as_abas_visiveis_na_ordem_com_a_origem_em_primeiro(trimestre):
    df = wolfz.run(receita({}), trimestre)
    assert df.columns == ["aba", "Vendedor", "Valor"]
    assert df["aba"].to_list() == ["JAN"] * 3 + ["FEV"] * 2 + ["MAR"] * 4


def test_abas_ocultas_nunca_entram_e_sao_listadas(trimestre):
    r = wolfz.run_report(receita({}), trimestre)
    assert set(r.table["aba"]) == {"JAN", "FEV", "MAR"}
    assert r.hidden_sheets == ("Base", "Config")
    assert r.to_dict()["abas_ocultas"] == ["Base", "Config"]


def test_regex_casa_o_nome_inteiro(trimestre):
    df = wolfz.run(receita({"sheets_regex": "(?i)jan|mar"}), trimestre)
    assert df["aba"].unique(maintain_order=True).to_list() == ["JAN", "MAR"]


def test_regex_que_casa_so_um_pedaco_nao_pega(trimestre):
    with pytest.raises(IngestError) as exc:
        wolfz.run(receita({"sheets_regex": "JA"}), trimestre)
    assert "Abas do arquivo: JAN, FEV, Base, MAR, Config." in exc.value.message


def test_sem_coluna_de_origem(trimestre):
    df = wolfz.run(receita({"origin_col": None}), trimestre)
    assert df.columns == ["Vendedor", "Valor"] and df.height == 9


def test_nome_da_coluna_de_origem(trimestre):
    assert wolfz.run(receita({"origin_col": "Mes"}), trimestre).columns[0] == "Mes"


def test_reconciliacao_por_parte(trimestre):
    r = wolfz.run_report(
        receita({}, {"op": "drop_rows_where", "col": "Vendedor", "match": "equals", "value": "V0"}), trimestre
    )
    assert [(p.origin, p.rows_written) for p in r.parts] == [("JAN", 2), ("FEV", 1), ("MAR", 3)]
    assert r.rows_written == 6 and r.table.height == 6
    s3 = r.steps[2]
    assert (s3.rows_in, s3.rows_out) == (9, 6)
    d = r.to_dict()
    assert [p["origem"] for p in d["partes"]] == ["JAN", "FEV", "MAR"]
    assert d["partes"][0]["linhas_gravadas"] == 2


def test_coluna_que_falta_e_ninguem_cita_fica_vazia_com_aviso(tmp_path):
    arq = planilha(
        tmp_path / "a.xlsx",
        {"JAN": _mes("JAN", 2, ("Vendedor", "Valor")), "FEV": [["t"], ["Vendedor"], ["X"]]},
    )
    r = wolfz.run_report(receita({}), arq)
    assert r.table.filter(pl.col("aba") == "FEV")["Valor"].to_list() == [None]
    [d] = [d for d in r.divergences if d.parte == "FEV"]
    assert d.falta == ("Valor",)


def test_coluna_que_um_passo_cita_e_falta_numa_aba_e_erro_com_a_aba(tmp_path):
    arq = planilha(tmp_path / "a.xlsx", {"JAN": _mes("JAN", 2), "FEV": [["t"], ["Vendedor"], ["X"]]})
    with pytest.raises(StepError) as exc:
        wolfz.run(receita({}, {"op": "parse_decimal_br", "cols": ["Valor"]}), arq)
    assert exc.value.message.startswith("Na aba FEV: ")


def test_nome_quase_igual_vira_duas_colunas_com_aviso(tmp_path):
    arq = planilha(
        tmp_path / "a.xlsx",
        {"JAN": _mes("JAN", 1, ("Vendedor", "Valor")), "FEV": _mes("FEV", 1, ("vendedor", "Valor"))},
    )
    r = wolfz.run_report(receita({}), arq)
    assert {"Vendedor", "vendedor"} <= set(r.table.columns)
    [d] = [d for d in r.divergences if d.parte == "FEV"]
    assert d.quase_iguais == (("vendedor", "Vendedor"),)


def test_tipo_diferente_entre_abas_e_erro():
    with pytest.raises(ErroAoJuntar) as exc:
        empilhar([("JAN", pl.DataFrame({"Valor": [1.0]})), ("FEV", pl.DataFrame({"Valor": ["1"]}))], "aba")
    assert "'Valor' é número em JAN e texto em FEV" in exc.value.mensagem


def test_coluna_de_origem_com_nome_de_coluna_da_tabela_e_erro(trimestre):
    with pytest.raises(ErroAoJuntar, match="já tem uma coluna"):
        wolfz.run(receita({"origin_col": "Vendedor"}), trimestre)


def test_sheet_le_so_a_aba_pedida(trimestre):
    df = wolfz.run(receita({}), trimestre, sheet="FEV")
    assert df.height == 2 and "aba" not in df.columns
    with pytest.raises(IngestError) as exc:
        wolfz.run(receita(None), trimestre, sheet="FEVEREIRO")
    assert exc.value.code == "sheet_not_found"


def test_sem_combine_e_igual_a_antes(trimestre):
    assert wolfz.run(receita(None), trimestre).columns == ["Vendedor", "Valor"]
    assert wolfz.run_report(receita(None), trimestre).parts == ()


# ---------------------------------------------------------------------------
# Receita (R5, ADR-9)
# ---------------------------------------------------------------------------


def test_receita_grava_1_1_e_null_desliga_a_origem():
    texto = dumps_recipe(receita({"origin_col": None}))
    assert '"wolfz_version": "1.1"' in texto and '"origin_col": null' in texto
    assert recipe_from_dict(__import__("json").loads(texto)).source.combine_sheets.origin_col is None


@pytest.mark.parametrize(
    ("source", "erro"),
    [
        ({"type": "csv", "combine_sheets": {}}, "CSV não tem abas"),
        ({"type": "excel", "combine_sheets": {}, "match": {"sheet_name_regex": "x"}}, "não os dois"),
        ({"type": "excel", "combine_sheets": {"sheets_regex": "(a)\\1"}}, "regex inválida"),
        ({"type": "excel", "combine_sheets": {"arquivos": "../../**/*.xlsx"}}, "campo não permitido"),
        ({"type": "excel", "combine_sheets": {"origin_col": ""}}, "origin_col"),
    ],
)
def test_receita_recusada(source, erro):
    with pytest.raises(RecipeError) as exc:
        recipe_from_dict(
            {"wolfz_version": "1.1", "name": "x", "created_at": "2026-01-01T00:00:00Z", "source": source}
        )
    assert any(erro in e for e in exc.value.errors), exc.value.errors


def test_regex_catastrofica_termina_rapido():
    """R5: a regex vem da receita, que pode vir de terceiro."""
    inicio = time.perf_counter()
    assert casa_inteira(["a" * 30 + "b"], "(a+)+$") == [False]
    assert time.perf_counter() - inicio < 1

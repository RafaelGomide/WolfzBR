"""Exportação para o Tableau (F3.A): ``.hyper`` com os tipos certos e
``.tds`` com nomes amigáveis e formatação brasileira."""

import xml.etree.ElementTree as ET
from datetime import date, datetime, time
from decimal import Decimal

import polars as pl
import pytest

from wolfz.core.recipe import recipe_from_dict
from wolfz.core.recipe.migrate import CURRENT_VERSION
from wolfz.export.tableau import (
    escrever_hyper,
    escrever_tds,
    formatos_colunas,
    hyper_disponivel,
    nome_amigavel,
    tds,
)

hyperapi = pytest.importorskip("tableauhyperapi", reason="extra wolfzbr[tableau] não instalado")


@pytest.fixture
def tabela():
    return pl.DataFrame(
        {
            "municipio": ["Vitória", "Serra", None],
            "valor_total": [1234.56, -0.5, None],
            "media": [1.2345, float("nan"), None],
            "qtd": [1, 2, None],
            "data": [date(2024, 1, 31), None, date(2000, 2, 29)],
            "momento": [datetime(2024, 1, 31, 10, 30), None, None],
            "hora": [time(8, 0), None, None],
            "ok": [True, False, None],
        }
    )


def _ler_hyper(path):
    from tableauhyperapi import Connection, HyperProcess, TableName, Telemetry

    with (
        HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""}) as hyper,
        Connection(hyper.endpoint, str(path)) as conexao,
    ):
        definicao = conexao.catalog.get_table_definition(TableName("Extract", "Extract"))
        tipos = {c.name.unescaped: str(c.type) for c in definicao.columns}
        linhas = conexao.execute_list_query('SELECT * FROM "Extract"."Extract"')
    return tipos, linhas


def test_hyper_disponivel():
    assert hyper_disponivel()


def test_hyper_com_tipos_certos(tabela, tmp_path):
    destino = tmp_path / "pasta com acento ç" / "saida.hyper"
    destino.parent.mkdir()
    escrever_hyper(tabela, destino, {"valor_total": "brl", "media": "brl"})
    tipos, linhas = _ler_hyper(destino)
    assert tipos == {
        "municipio": "TEXT",
        "valor_total": "NUMERIC(18, 2)",
        "media": "DOUBLE",  # tem mais de dois decimais: não arredonda
        "qtd": "BIG_INT",
        "data": "DATE",
        "momento": "TIMESTAMP",
        "hora": "TIME",
        "ok": "BOOL",
    }
    assert len(linhas) == 3
    primeira = linhas[0]
    assert primeira[0] == "Vitória"
    assert primeira[1] == Decimal("1234.56")
    assert primeira[2] == pytest.approx(1.2345)
    assert str(primeira[4]) == "2024-01-31"
    assert linhas[1][2] is None  # NaN vira nulo
    assert all(v is None for v in linhas[2][1:4])
    assert list(destino.parent.iterdir()) == [destino]  # sem log nem arquivo temporário


def test_hyper_sem_linhas(tmp_path):
    destino = tmp_path / "vazio.hyper"
    escrever_hyper(pl.DataFrame({"a": pl.Series([], dtype=pl.String)}), destino)
    tipos, linhas = _ler_hyper(destino)
    assert tipos == {"a": "TEXT"} and linhas == []


def test_hyper_com_fuso_e_tipo_estranho(tmp_path):
    df = pl.DataFrame(
        {
            "quando": pl.Series([datetime(2024, 1, 1, 12)], dtype=pl.Datetime("us", "UTC")),
            "lista": [[1, 2]],
        }
    )
    escrever_hyper(df, tmp_path / "x.hyper")
    tipos, linhas = _ler_hyper(tmp_path / "x.hyper")
    assert tipos == {"quando": "TIMESTAMP", "lista": "TEXT"}
    assert str(linhas[0][0]).startswith("2024-01-01 12:00")


# ---------------------------------------------------------------------------
# .tds
# ---------------------------------------------------------------------------


def test_tds_aponta_para_o_hyper_com_formatos_br(tabela, tmp_path):
    escrever_tds(tabela, tmp_path / "saida.tds", "saída.hyper", {"valor_total": "brl", "media": "percent"})
    raiz = ET.parse(tmp_path / "saida.tds").getroot()
    assert raiz.tag == "datasource"
    conexao = raiz.find("connection/named-connections/named-connection/connection")
    assert conexao.get("class") == "hyper"
    assert conexao.get("dbname") == "saída.hyper"
    assert conexao.get("author-locale") == "pt_BR"
    assert raiz.find("connection/relation").get("table") == "[Extract].[Extract]"
    # <layout> exige dim-percentage e measure-percentage no Tableau; sem ele, o padrão.
    assert raiz.find("layout") is None

    colunas = {c.get("name"): c for c in raiz.findall("column")}
    assert list(colunas) == [f"[{n}]" for n in tabela.columns]
    assert colunas["[valor_total]"].get("caption") == "Valor total"
    assert "R$" in colunas["[valor_total]"].get("default-format")
    assert colunas["[valor_total]"].get("role") == "measure"
    assert colunas["[media]"].get("default-format").startswith("p")
    assert colunas["[data]"].get("default-format") == "*dd/MM/yyyy"
    assert colunas["[data]"].get("datatype") == "date"
    assert colunas["[municipio]"].get("role") == "dimension"
    assert colunas["[qtd]"].get("default-format") is None


def test_tds_escapa_nomes():
    df = pl.DataFrame({"a]b": [1], "x'y\"<z>": ["t"]})
    raiz = ET.fromstring(tds(df, "a&b.hyper"))
    assert [c.get("name") for c in raiz.findall("column")] == ["[a]]b]", "[x'y\"<z>]"]
    assert raiz.find(".//named-connection/connection").get("dbname") == "a&b.hyper"


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("valor_total", "Valor total"),
        ("uf", "Uf"),
        ("Código", "Código"),
        ("já tem espaço", "já tem espaço"),
        ("__", "__"),
    ],
)
def test_nome_amigavel(nome, esperado):
    assert nome_amigavel(nome) == esperado


def test_formatos_seguem_os_passos():
    receita = recipe_from_dict(
        {
            "wolfz_version": CURRENT_VERSION,
            "name": "t",
            "created_at": "2026-10-22T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [
                {"id": "s1", "op": "parse_brl", "cols": ["Vlr", "Desc"]},
                {"id": "s2", "op": "parse_percent", "cols": ["Pct"]},
                {"id": "s3", "op": "rename", "mapping": {"Vlr": "valor"}},
                {"id": "s4", "op": "parse_decimal_br", "cols": ["Desc"]},
                {"id": "s5", "op": "parse_brl", "cols": ["Outro"], "enabled": False},
            ],
        }
    )
    assert formatos_colunas(receita) == {"valor": "brl", "Pct": "percent"}

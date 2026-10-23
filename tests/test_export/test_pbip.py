"""Exportação para o Power BI como projeto PBIP (F3.B): arquivos e JSON
válidos contra os schemas oficiais, TMDL com as colunas, os tipos, as
medidas e a partição com o M da receita, e a tabela calendário opcional.

Abrir no Power BI Desktop e dar refresh é manual (dev/validacao_pbip.md)."""

import json
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from m_parser import parse_m

from wolfz.core.recipe import recipe_from_dict
from wolfz.core.recipe.migrate import CURRENT_VERSION
from wolfz.export.dados import ExportError, gravar_juntos
from wolfz.export.m import FonteM
from wolfz.export.pbip import (
    CALENDARIO,
    FORMATO_BRL,
    OpcoesPbip,
    escrever_arquivo,
    escrever_pasta,
    parametros_pbip,
    projeto_pbip,
    tmdl_nome,
)

jsonschema = pytest.importorskip("jsonschema")

SCHEMAS = Path(__file__).resolve().parents[1] / "fixtures" / "pbip_schemas"
PREFIXO_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/"
JSONS = (".json", ".pbip", ".pbir", ".pbism", ".platform")


def _receita(passos=(), nome="Vendas Mensais"):
    return recipe_from_dict(
        {
            "wolfz_version": CURRENT_VERSION,
            "name": nome,
            "created_at": "2026-10-22T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


RECEITA = _receita(
    [
        {"op": "parse_date_br", "cols": ["data"]},
        {"op": "parse_brl", "cols": ["Vlr"]},
        {"op": "rename", "mapping": {"Vlr": "valor"}},
        {"op": "parse_percent", "cols": ["margem"]},
        {"op": "cast", "types": {"qtd": "int", "ano": "int"}},
    ]
)
SCHEMA = pl.Schema(
    {
        "data": pl.Date,
        "municipio": pl.String,
        "valor": pl.Float64,
        "margem": pl.Float64,
        "qtd": pl.Int64,
        "ano": pl.Int64,
        "ativo": pl.Boolean,
    }
)


def _projeto(opcoes=None, receita=RECEITA, schema=SCHEMA):
    return projeto_pbip(
        "vendas",
        receita,
        schema,
        FonteM("csv", encoding="utf-8", separador=";", colunas=7),
        parametros_pbip(receita, r"C:\dados\vendas.csv"),
        opcoes,
    )


@pytest.fixture(scope="module")
def arquivos():
    return _projeto(OpcoesPbip(calendario=True))


def _tabela(arquivos):
    return arquivos["vendas.SemanticModel/definition/tables/Vendas Mensais.tmdl"]


# ---------------------------------------------------------------------------
# Estrutura e JSON
# ---------------------------------------------------------------------------


def test_arquivos_do_projeto(arquivos):
    pagina = next(k.split("/")[-2] for k in arquivos if k.endswith("/page.json"))
    assert re.fullmatch(r"[0-9a-f]{20}", pagina)
    assert sorted(arquivos) == sorted(
        [
            "vendas.pbip",
            "vendas.SemanticModel/.platform",
            "vendas.SemanticModel/definition.pbism",
            "vendas.SemanticModel/definition/database.tmdl",
            "vendas.SemanticModel/definition/model.tmdl",
            "vendas.SemanticModel/definition/expressions.tmdl",
            "vendas.SemanticModel/definition/relationships.tmdl",
            "vendas.SemanticModel/definition/tables/Vendas Mensais.tmdl",
            f"vendas.SemanticModel/definition/tables/{CALENDARIO}.tmdl",
            "vendas.Report/.platform",
            "vendas.Report/definition.pbir",
            "vendas.Report/definition/version.json",
            "vendas.Report/definition/report.json",
            "vendas.Report/definition/pages/pages.json",
            f"vendas.Report/definition/pages/{pagina}/page.json",
        ]
    )


def test_json_valido_contra_o_schema_oficial(arquivos):
    jsons = {k: v for k, v in arquivos.items() if k.endswith(JSONS)}
    assert len(jsons) == 9
    for caminho, texto in jsons.items():
        documento = json.loads(texto)
        url = documento["$schema"]
        assert url.startswith(PREFIXO_SCHEMA), caminho
        local = SCHEMAS / url.removeprefix(PREFIXO_SCHEMA)
        assert local.is_file(), f"{caminho}: baixe o schema {url} para {local}"
        schema = json.loads(local.read_text(encoding="utf-8"))
        jsonschema.validate(documento, schema)


def test_referencias_entre_arquivos(arquivos):
    pbip = json.loads(arquivos["vendas.pbip"])
    assert pbip["artifacts"] == [{"report": {"path": "vendas.Report"}}]
    pbir = json.loads(arquivos["vendas.Report/definition.pbir"])
    assert pbir["datasetReference"]["byPath"]["path"] == "../vendas.SemanticModel"
    paginas = json.loads(arquivos["vendas.Report/definition/pages/pages.json"])
    (pagina,) = paginas["pageOrder"]
    assert paginas["activePageName"] == pagina
    assert json.loads(arquivos[f"vendas.Report/definition/pages/{pagina}/page.json"])["name"] == pagina
    modelo = json.loads(arquivos["vendas.SemanticModel/.platform"])
    relatorio = json.loads(arquivos["vendas.Report/.platform"])
    assert modelo["metadata"]["type"] == "SemanticModel" and relatorio["metadata"]["type"] == "Report"
    assert modelo["config"]["logicalId"] != relatorio["config"]["logicalId"]


def test_mesma_receita_mesmos_arquivos(arquivos):
    assert _projeto(OpcoesPbip(calendario=True)) == arquivos


# ---------------------------------------------------------------------------
# TMDL
# ---------------------------------------------------------------------------


def test_indentacao_so_com_tabs(arquivos):
    for caminho, texto in arquivos.items():
        if caminho.endswith(".tmdl"):
            for linha in texto.splitlines():
                assert not linha.startswith(" "), f"{caminho}: {linha!r}"


def test_model_referencia_todas_as_tabelas(arquivos):
    modelo = arquivos["vendas.SemanticModel/definition/model.tmdl"]
    assert "\tculture: pt-BR" in modelo
    assert re.findall(r"^ref table (.+)$", modelo, flags=re.MULTILINE) == [
        "'Vendas Mensais'",
        tmdl_nome(CALENDARIO),
    ]
    declaradas = [
        re.match(r"table (.+)", texto).group(1)
        for caminho, texto in arquivos.items()
        if "/tables/" in caminho
    ]
    assert sorted(declaradas) == sorted(["'Vendas Mensais'", tmdl_nome(CALENDARIO)])
    assert 'PBI_QueryOrder = ["CaminhoArquivo","Vendas Mensais"]' in modelo


def _bloco(tmdl, cabecalho):
    """As linhas do objeto (coluna, medida) até o próximo do mesmo nível."""
    linhas = tmdl.splitlines()
    i = linhas.index(cabecalho)
    fim = next((j for j in range(i + 1, len(linhas)) if re.match(r"\t\S", linhas[j])), len(linhas))
    return "\n".join(linhas[i:fim])


def test_colunas_tipos_e_formatos(arquivos):
    tabela = _tabela(arquivos)
    assert tabela.startswith("table 'Vendas Mensais'\n")
    data = _bloco(tabela, "\tcolumn data")
    assert "dataType: dateTime" in data and "formatString: dd/MM/yyyy" in data
    assert "annotation UnderlyingDateTimeDataType = Date" in data
    valor = _bloco(tabela, "\tcolumn valor")
    assert (
        "dataType: double" in valor
        and f"formatString: {FORMATO_BRL}" in valor
        and "summarizeBy: sum" in valor
    )
    assert "formatString: 0.00%" in _bloco(tabela, "\tcolumn margem")
    assert "dataType: int64" in _bloco(tabela, "\tcolumn qtd")
    ano = _bloco(tabela, "\tcolumn ano")
    assert "dataType: int64" in ano and "summarizeBy: none" in ano  # ano não é métrica
    assert "dataType: string" in _bloco(tabela, "\tcolumn municipio")
    assert "dataType: boolean" in _bloco(tabela, "\tcolumn ativo")


def test_medidas(arquivos):
    medidas = re.findall(r"^\tmeasure (.+?) = (.+)$", _tabela(arquivos), flags=re.MULTILINE)
    assert medidas == [
        ("'Total valor'", "SUM('Vendas Mensais'[valor])"),
        ("'Total margem'", "SUM('Vendas Mensais'[margem])"),
        ("'Total qtd'", "SUM('Vendas Mensais'[qtd])"),
        ("'Contagem de linhas'", "COUNTROWS('Vendas Mensais')"),
    ]
    assert f"formatString: {FORMATO_BRL}" in _bloco(
        _tabela(arquivos), "\tmeasure 'Total valor' = SUM('Vendas Mensais'[valor])"
    )


def test_particao_com_o_m_da_receita_e_os_tipos(arquivos):
    tabela = _tabela(arquivos)
    assert "\tpartition 'Vendas Mensais' = m\n\t\tmode: import\n\t\tsource =\n" in tabela
    inicio = tabela.index("\t\tsource =\n") + len("\t\tsource =\n")
    fim = tabela.index("\n\n\tannotation PBI_ResultType")
    linhas = tabela[inicio:fim].splitlines()
    assert all(not linha or linha.startswith("\t\t\t\t") for linha in linhas)
    m = "\n".join(linha.removeprefix("\t\t\t\t") for linha in linhas)
    assert "CaminhoArquivo" in m and "// s2 parse_brl" in m
    assert 'Table.TransformColumnTypes(Receita, {{"data", type date}' in m
    assert '{"qtd", Int64.Type}' in m and '{"ativo", type logical}' in m
    parametro = arquivos["vendas.SemanticModel/definition/expressions.tmdl"]
    valor = re.match(r"expression CaminhoArquivo = (.+)$", parametro, flags=re.MULTILINE).group(1)
    assert valor.startswith('"C:\\dados\\vendas.csv" meta [IsParameterQuery = true')
    assert parse_m([m, valor]) == [{"ok": True}, {"ok": True}]


def test_calendario(arquivos):
    calendario = arquivos[f"vendas.SemanticModel/definition/tables/{CALENDARIO}.tmdl"]
    assert calendario.startswith(f"table {tmdl_nome(CALENDARIO)}\n\tdataCategory: Time\n")
    assert "\t\tisKey" in _bloco(calendario, "\tcolumn Data")
    for mes in ("janeiro", "fevereiro", "março", "dezembro", '"jan"', '"dez"'):
        assert mes in calendario
    assert "MIN('Vendas Mensais'[data])" in calendario
    assert "\t\tsortByColumn: 'Mês'" in _bloco(calendario, "\tcolumn 'Nome do mês'")
    relacao = arquivos["vendas.SemanticModel/definition/relationships.tmdl"]
    assert f"\tfromColumn: 'Vendas Mensais'.data\n\ttoColumn: {tmdl_nome(CALENDARIO)}.Data\n" in relacao


def test_sem_calendario():
    arquivos = _projeto()
    assert not any(CALENDARIO in k or "relationships" in k for k in arquivos)
    assert "ref table" in arquivos["vendas.SemanticModel/definition/model.tmdl"]


def test_calendario_sem_coluna_de_data():
    with pytest.raises(ExportError, match="coluna de data"):
        _projeto(OpcoesPbip(calendario=True), schema=pl.Schema({"municipio": pl.String}))


def test_parametro_do_depara():
    receita = _receita([{"op": "normalize_municipio", "col": "cidade"}], nome="t")
    parametros = parametros_pbip(receita, "C:/x.csv", {"CaminhoDeparaMunicipios": "C:/saida/depara.csv"})
    assert parametros == {"CaminhoArquivo": "C:/x.csv", "CaminhoDeparaMunicipios": "C:/saida/depara.csv"}


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [("valor", "valor"), ("Valor Total", "'Valor Total'"), ("d'água", "'d''água'"), ("Mês", "'Mês'")],
)
def test_tmdl_nome(nome, esperado):
    assert tmdl_nome(nome) == esperado


def test_nomes_hostis():
    """Aspas, colchete e apóstrofo no nome da receita e das colunas."""
    receita = _receita(nome="O'Brien [teste]")
    schema = pl.Schema({"a]b": pl.Float64, "x'y": pl.String, 'c"d': pl.Date})
    arquivos = _projeto(OpcoesPbip(calendario=True), receita=receita, schema=schema)
    tabela = arquivos["vendas.SemanticModel/definition/tables/O'Brien [teste].tmdl"]
    assert tabela.startswith("table 'O''Brien [teste]'\n")
    assert "SUM('O''Brien [teste]'[a]]b])" in tabela
    assert "\tcolumn 'x''y'" in tabela
    m = tabela[tabela.index("\t\tsource =\n") :]
    assert '{"c""d", type date}' in m


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------


def test_grava_e_sobrescreve_a_pasta(tmp_path, arquivos):
    escritas = {
        tmp_path / "vendas.pbip": lambda p: escrever_arquivo(arquivos["vendas.pbip"], p),
        tmp_path / "vendas.SemanticModel": lambda p: escrever_pasta(arquivos, "vendas.SemanticModel", p),
        tmp_path / "vendas.Report": lambda p: escrever_pasta(arquivos, "vendas.Report", p),
    }
    gravar_juntos(escritas)
    antigo = tmp_path / "vendas.SemanticModel" / "definition" / "tables" / "antiga.tmdl"
    antigo.write_text("table antiga", encoding="utf-8")
    gravar_juntos(escritas)
    assert not antigo.exists()  # a pasta é trocada inteira: nada de tabela velha
    gravados = sorted(
        str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file()
    )
    assert gravados == sorted(arquivos)
    bruto = (tmp_path / "vendas.SemanticModel" / "definition" / "model.tmdl").read_bytes()
    assert b"\r\n" in bruto and not bruto.startswith(b"\xef\xbb\xbf")
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".wolfz-export")]


def test_dados_de_exemplo_nao_entram():
    """O PBIP não leva dados: só o modelo (o Desktop carrega no refresh)."""
    arquivos = _projeto(OpcoesPbip(calendario=True))
    assert not any(k.endswith((".abf", ".parquet", ".csv")) for k in arquivos)
    assert date(2024, 1, 1).isoformat() not in "".join(arquivos.values())

"""Consulta Power Query M completa (F2.A): escapes, nomes de passo, fonte,
parâmetro ``CaminhoArquivo`` e validação de sintaxe com o parser oficial."""

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from m_parser import parse_m
from m_sintaxe import check_m

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.recipe import Recipe, Source, load_recipe, recipe_from_dict, registered_ops
from wolfz.export.m import (
    FonteM,
    m_identifier,
    m_list,
    m_value,
    parameter_to_m,
    recipe_to_m,
    source_from_file,
    source_from_project,
    step_names,
)

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
# Nomes que quebrariam o M se fossem concatenados sem escape (§11.5 do design).
HOSTIS = [
    'Nº "Pedido"',
    '#"',
    '" in 1 //',
    "linha\nquebrada",
    "a\r\nb\tc",
    "#(lf)",
    "😀 emoji",
    "let",
    "",
    "\u2028separador",
]


# ---------------------------------------------------------------------------
# Escapes (F2.A2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Fonte", "Fonte"),
        ("_s1", "_s1"),
        ("Linhas removidas", '#"Linhas removidas"'),
        ("Área", '#"Área"'),
        ("1a", '#"1a"'),
        ("let", '#"let"'),
        ("each", '#"each"'),
        ('a"b', '#"a""b"'),
        ('#"', '#"#"""'),
        ("x\ny", '#"x#(lf)y"'),
        ("#(tab)", '#"#(#)(tab)"'),
        ("😀", '#"😀"'),
    ],
)
def test_m_identifier(name, expected):
    assert m_identifier(name) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (3, "3"),
        (-1.5, "-1.5"),
        (float("nan"), "#nan"),
        (float("inf"), "#infinity"),
        (float("-inf"), "-#infinity"),
        ("a", '"a"'),
        ([1, None, "x", [True]], '{1, null, "x", {true}}'),
    ],
)
def test_m_value(value, expected):
    assert m_value(value) == expected


def test_m_value_recusa_tipo_desconhecido():
    with pytest.raises(TypeError, match="sem literal M"):
        m_value(object())


def test_m_list():
    assert m_list(["a", 'b"']) == '{"a", "b"""}'
    assert m_list([]) == "{}"


def test_escapes_hostis_passam_no_parser():
    """Cada nome hostil, como identificador, texto e item de lista, vira
    exatamente um token: o documento continua com um único passo."""
    documentos = []
    for nome in HOSTIS:
        ident = m_identifier(nome)
        documentos.append(f"let {ident} = {m_value(nome)}, b = {m_list([nome, nome])} in {ident}")
    for doc in documentos:
        check_m(doc)
    assert all(r["ok"] for r in parse_m(documentos)), documentos


# ---------------------------------------------------------------------------
# Nomes de passo (F2.A1) e comentários (F2.A4)
# ---------------------------------------------------------------------------


def _receita(steps, source=None, name="vendas") -> Recipe:
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": name,
            "created_at": "2026-01-01T00:00:00Z",
            "source": source or {"type": "excel", "sheet": "Vendas"},
            "steps": steps,
        }
    )


PASSOS = [
    {"id": "s1", "op": "select_range", "start": "A3", "end_detect": "auto"},
    {"id": "s2", "op": "header_rows", "n": 1},
    {"id": "s3", "op": "drop_rows_where", "col": "Região", "match": "equals", "value": "Total"},
    {"id": "s4", "op": "drop_rows_where", "col": "Região", "match": "starts_with", "value": "Sub"},
    {"id": "s5", "op": "parse_brl", "cols": ["Valor"]},
]


CATALOGO = {name: cls for name, cls in registered_ops().items() if cls.__module__.startswith("wolfz.")}


@pytest.mark.parametrize("name", sorted(CATALOGO))
def test_toda_operacao_tem_rotulo(name):
    assert CATALOGO[name].m_label, f"{name} precisa de m_label (nome do passo no M)"


def test_nomes_de_passo_legiveis_e_unicos():
    receita = _receita(PASSOS)
    nomes = step_names(receita.steps, {"Fonte"})
    assert nomes == {
        "s1": '#"Área recortada"',
        "s2": '#"Cabeçalhos promovidos"',
        "s3": '#"Linhas removidas"',
        "s4": '#"Linhas removidas 2"',
        "s5": '#"Valores em reais convertidos"',
    }
    assert len(set(nomes.values())) == len(nomes)


def test_nome_reservado_nao_e_reusado():
    receita = _receita([{"id": "s1", "op": "rename", "mapping": {"a": "b"}}])
    assert step_names(receita.steps, {"Colunas renomeadas"}) == {"s1": '#"Colunas renomeadas 2"'}


def test_consulta_let_in_com_comentarios():
    m = recipe_to_m(_receita(PASSOS))
    linhas = m.splitlines()
    for step in PASSOS:
        assert f"    // {step['id']} {step['op']}" in linhas
    i = linhas.index("    // s3 drop_rows_where")
    assert linhas[i + 1].startswith('    #"Linhas removidas" = Table.SelectRows(#"Cabeçalhos promovidos",')
    assert linhas[-2:] == ["in", '    #"Valores em reais convertidos"']
    check_m(m)


def test_passo_desativado_nao_entra():
    passos = [*PASSOS[:4], {**PASSOS[4], "enabled": False}]
    m = recipe_to_m(_receita(passos))
    assert "s5" not in m
    assert m.endswith('in\n    #"Linhas removidas 2"\n')


# ---------------------------------------------------------------------------
# Fonte (F2.A5) e parâmetro (F2.A3)
# ---------------------------------------------------------------------------


def test_fonte_excel():
    m = recipe_to_m(_receita(PASSOS), FonteM("excel", aba="Vendas", linha0=2, coluna0=1))
    assert "Arquivo = Excel.Workbook(File.Contents(CaminhoArquivo), null, true)," in m
    assert 'Aba = Arquivo{[Item = "Vendas", Kind = "Sheet"]}[Data],' in m
    assert "Fonte = WolfzGrade(Aba, 2, 1)," in m


def test_fonte_excel_sem_aba_usa_a_primeira_visivel():
    m = recipe_to_m(_receita(PASSOS), FonteM("excel"))
    assert '[Kind] = "Sheet" and not [Hidden]){0}[Data]' in m


def test_fonte_ods_avisa():
    m = recipe_to_m(_receita(PASSOS), FonteM("ods", aba="Vendas"))
    assert "não lê .ods" in m
    assert "Excel.Workbook" in m


@pytest.mark.parametrize(
    ("encoding", "codepage"),
    [("cp1252", 1252), ("utf-8", 65001), ("utf-8-sig", 65001), ("latin-1", 28591), (None, 65001)],
)
def test_fonte_csv_encoding(encoding, codepage):
    m = recipe_to_m(_receita(PASSOS), FonteM("csv", encoding=encoding, separador="\t", colunas=7))
    assert (
        "Arquivo = Csv.Document(File.Contents(CaminhoArquivo), "
        f'[Delimiter = "#(tab)", Columns = 7, Encoding = {codepage}, QuoteStyle = QuoteStyle.Csv]),'
    ) in m


def test_csv_com_cabecalho_quando_nao_comeca_pela_grade():
    """A mesma regra do ``wolfz.run``: CSV vem com cabeçalho, a não ser que a
    receita comece por ``select_range`` ou ``header_rows``."""
    com_cabecalho = recipe_to_m(_receita(PASSOS[2:]), FonteM("csv", encoding="cp1252", separador=";"))
    assert "Table.PromoteHeaders(Arquivo, [PromoteAllScalars = true])" in com_cabecalho
    assert "WolfzGradeCsv" not in com_cabecalho
    grade = recipe_to_m(_receita(PASSOS), FonteM("csv", encoding="cp1252", separador=";"))
    assert "Fonte = WolfzGradeCsv(Arquivo)," in grade
    assert "PromoteHeaders" not in grade


def test_source_from_project_acha_a_area_usada():
    grade = pl.DataFrame(
        {
            "B": [None, None, None, None],
            "C": [None, None, "título", "x"],
            "D": [None, None, None, "y"],
        }
    ).lazy()
    fonte = source_from_project({"format": "xlsx", "sheet": "Aba", "path": "C:\\a.xlsx"}, grade)
    assert fonte == FonteM("excel", aba="Aba", linha0=2, coluna0=2, caminho="C:\\a.xlsx")


def test_source_from_project_csv():
    grade = pl.DataFrame({"A": ["1"], "B": ["2"]}).lazy()
    fonte = source_from_project({"format": "csv", "encoding": "cp1252", "separator": ";"}, grade)
    assert fonte == FonteM("csv", encoding="cp1252", separador=";", colunas=2)


def test_parametro():
    m = parameter_to_m('C:\\Dados\\vendas "jan".xlsx', "vendas")
    assert m.endswith(
        '"C:\\Dados\\vendas ""jan"".xlsx" meta '
        '[IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
    )
    assert "Gerenciar Parâmetros" in m
    check_m(m)


# ---------------------------------------------------------------------------
# Injeção (§11.5): nomes hostis em toda parte que vira M
# ---------------------------------------------------------------------------


def _receita_hostil(nome: str) -> Recipe:
    col = nome or "vazio"
    return _receita(
        [
            {"id": "s1", "op": "header_rows", "n": 1},
            {"id": "s2", "op": "rename", "mapping": {"A": col}},
            {"id": "s3", "op": "drop_rows_where", "col": col, "match": "equals", "value": col},
            {"id": "s4", "op": "fill_null", "cols": [col], "value": nome},
        ],
        source={"type": "excel", "sheet": nome or None},
        name=nome or "receita",
    )


def test_nomes_hostis_nao_quebram_a_consulta():
    documentos = []
    for nome in HOSTIS:
        receita = _receita_hostil(nome)
        m = recipe_to_m(receita, FonteM("excel", aba=nome or None, caminho=nome))
        check_m(m)
        # O nome da receita vai num comentário: não pode abrir linha nova.
        assert sum(1 for linha in m.splitlines() if linha.startswith("let")) == 1
        assert m.splitlines()[-1] == '    #"Nulos preenchidos"'
        documentos += [m, parameter_to_m(nome, nome)]
    falhas = [(d, r) for d, r in zip(documentos, parse_m(documentos), strict=True) if not r["ok"]]
    assert not falhas


# ---------------------------------------------------------------------------
# Sintaxe no CI (F2.A6): o M de todas as receitas do corpus
# ---------------------------------------------------------------------------


def _receitas_do_corpus():
    casos = []
    for receita in sorted(CORPUS.glob("*/receita_esperada*.wolfz.json")):
        ops = {p["op"] for p in json.loads(receita.read_text(encoding="utf-8"))["steps"]}
        originais = sorted(receita.parent.glob("original.*"))
        if ops <= registered_ops().keys() and originais:
            casos.append((f"{receita.parent.name}/{receita.stem}", receita, originais[0]))
    return casos


def test_corpus_gera_m_valido():
    casos = _receitas_do_corpus()
    assert len(casos) >= 20
    documentos = {}
    for nome, receita, original in casos:
        recipe = load_recipe(receita)
        documentos[nome] = recipe_to_m(recipe, source_from_file(recipe, original))
        check_m(documentos[nome])
    resultados = parse_m(list(documentos.values()))
    falhas = {n: r["error"] for n, r in zip(documentos, resultados, strict=True) if not r["ok"]}
    assert not falhas


def test_receita_sem_passos():
    vazia = Recipe(
        wolfz_version="1.0",
        name="vazia",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source=Source(type="csv"),
    )
    m = recipe_to_m(vazia)
    assert "PromoteHeaders" in m
    assert m.endswith("in\n    Fonte\n")
    assert parse_m([m])[0]["ok"]

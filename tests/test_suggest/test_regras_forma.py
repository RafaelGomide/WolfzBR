"""Regras da 0.7 (pronto da Fase 2): tabela larga, linhas de região, sentinela,
decimal decidido pela tabela, inteiro, mês e ano, código e nome, coluna
constante e o "aceitar todas" por etapa."""

from datetime import date

import polars as pl
import pytest

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core import suggest as sug
from wolfz.core.suggest import Suggestion, suggest
from wolfz.core.suggest.regras import _periodo


def _df(**cols) -> pl.DataFrame:
    return pl.DataFrame(cols, schema=dict.fromkeys(cols, pl.String))


def _regra(df: pl.DataFrame, nome: str, steps=()) -> list[Suggestion]:
    return [s for s in suggest(df, steps=steps) if s.rule == nome]


def _unica(df: pl.DataFrame, nome: str, steps=()) -> Suggestion:
    (s,) = _regra(df, nome, steps)
    return s


# ---------------------------------------------------------------------------
# Tabela larga
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "tipo"),
    [
        ("jan", "mes"),
        ("mar/24", "mes"),
        ("Março", "mes"),
        ("2023", "ano"),
        ("2019/20", "safra"),
        ("2019/2020", "safra"),
        ("2023/24 (1)", "safra"),
        ("1997-01-01 00:00:00", "data"),
        ("31/12/2024", "data"),
        ("1º trim", "trimestre"),
        ("T2 2024", "trimestre"),
        ("UF", None),
        ("Total", None),
        ("1º Decêndio", None),
        ("123", None),
    ],
)
def test_tipo_de_periodo(nome, tipo):
    assert _periodo(nome) == tipo


@pytest.mark.parametrize(
    ("colunas", "variavel"),
    [
        (["2019/20", "2020/21", "2021/22 (1)"], "safra"),
        (["2021", "2022", "2023"], "ano"),
        (["1997-01-01 00:00:00", "1997-02-01 00:00:00", "1997-03-01 00:00:00"], "data"),
    ],
)
def test_periodos_lado_a_lado(colunas, variavel):
    df = _df(uf=["ES", "SP"], **{c: ["1", "2"] for c in colunas})
    s = _unica(df, "meses_lado_a_lado")
    assert s.steps == ({"op": "unpivot", "index": ["uf"], "variable_name": variavel, "value_name": "valor"},)


def test_periodos_com_coluna_de_total_tiram_o_total_antes():
    df = _df(receita=["a", "b"], JAN=["1", "2"], FEV=["3", "4"], MAR=["5", "6"], TOTAL=["9", "12"])
    s = _unica(df, "meses_lado_a_lado")
    assert s.steps == (
        {"op": "drop_cols", "cols": ["TOTAL"]},
        {"op": "unpivot", "index": ["receita"], "variable_name": "mes", "value_name": "valor"},
    )
    assert "soma das outras" in s.reason


def test_nome_da_variavel_nao_colide_com_coluna_fixa():
    df = _df(mes=["x"], jan=["1"], fev=["2"], mar=["3"])
    s = _unica(df, "meses_lado_a_lado")
    assert s.steps[-1]["variable_name"] == "mes_2"


def test_series_numeradas_lado_a_lado():
    df = _df(
        municipio=["Vitória", "Serra"],
        **{"1º Decêndio": ["10.5", "1"], "2º Decêndio": ["2", "3"], "3º Decêndio": ["4", "5"]},
    )
    s = _unica(df, "series_lado_a_lado")
    assert s.steps == (
        {"op": "unpivot", "index": ["municipio"], "variable_name": "decendio", "value_name": "valor"},
    )


def test_series_precisam_de_tres_colunas_numericas():
    assert not _regra(_df(a=["x"], **{"Parcela 1": ["1"], "Parcela 2": ["2"]}), "series_lado_a_lado")
    assert not _regra(_df(**{"Nome 1": ["a"], "Nome 2": ["b"], "Nome 3": ["c"]}), "series_lado_a_lado")


def test_categorias_somadas_na_coluna_total():
    df = _df(
        UF=["ES", "ES", "SP"],
        MUNICIPIO=["Vitória", "Serra", "Santos"],
        TOTAL=["6", "15", "0"],
        AUTOMOVEL=["1", "4", "0"],
        MOTO=["2", "5", "0"],
        ONIBUS=["3", "6", "0"],
    )
    s = _unica(df, "categorias_com_total")
    assert s.steps == (
        {"op": "drop_cols", "cols": ["TOTAL"]},
        {"op": "unpivot", "index": ["UF", "MUNICIPIO"], "variable_name": "categoria", "value_name": "valor"},
    )


def test_total_que_nao_e_a_soma_nao_vira_categoria():
    df = _df(item=["a", "b"], total=["100", "200"], peso=["1", "2"], volume=["3", "4"])
    assert not _regra(df, "categorias_com_total")


def test_categorias_por_bloco_do_cabecalho_multinivel():
    """Dois blocos ('Pré-escolar', 'Alfabetização'), cada um com o seu total;
    o '-' do IBGE conta zero na soma."""
    p, a = "Matrícula_Pré-escolar_", "Matrícula_Alfabetização_"
    df = _df(
        UF=["RO", "AC"],
        **{
            p + "Total": ["10", "5"],
            p + "Estadual": ["4", "-"],
            p + "Municipal": ["6", "5"],
            a + "Total": ["7", "3"],
            a + "Estadual": ["7", "1"],
            a + "Municipal": ["-", "2"],
        },
    )
    s = _unica(df, "categorias_com_total")
    assert s.steps[0] == {"op": "drop_cols", "cols": [p + "Total", a + "Total"]}
    assert s.steps[1]["index"] == ["UF"]


def test_niveis_do_cabecalho_viram_categoria():
    passos = [{"op": "header_rows", "n": 3, "separator": "_"}]
    df = _df(uf=["RO", "AC"], **{"Mat_Pré_Federal": ["1", "-"], "Mat_Pré_Estadual": ["2", "3"]})
    s = _unica(df, "niveis_de_cabecalho", passos)
    assert s.steps == (
        {"op": "unpivot", "index": ["uf"], "variable_name": "categoria", "value_name": "valor"},
    )
    # Sem cabeçalho de vários níveis na receita, o '_' é só parte do nome.
    assert not _regra(df, "niveis_de_cabecalho", [{"op": "header_rows", "n": 1}])


# ---------------------------------------------------------------------------
# Linhas
# ---------------------------------------------------------------------------


UFS = ["RO", "AC", "AM", "RR", "PA", "AP", "TO", "MA", "PI", "CE", "RN"]


def test_linhas_de_regiao_entre_as_ufs():
    df = _df(uf=["NORTE", *UFS, "Região Nordeste", "BRASIL"], v=[str(i) for i in range(len(UFS) + 3)])
    s = _unica(df, "linhas_de_regiao")
    assert s.steps == (
        {
            "op": "drop_rows_where",
            "col": "uf",
            "match": "in",
            "value": ["NORTE", "Região Nordeste", "BRASIL"],
        },
    )


def test_regiao_sem_ufs_suficientes_nao_e_sugerida():
    assert not _regra(_df(regiao=["Norte", "Sul", "ES"], v=["1", "2", "3"]), "linhas_de_regiao")


def test_linhas_vazias_e_duplicadas_sao_regras_diferentes():
    df = _df(a=["1", None, "1", " "], b=["x", None, "x", None])
    assert _unica(df, "linhas_vazias").steps == ({"op": "drop_empty_rows"},)
    assert "1 linha repetida" in _unica(df, "duplicadas").reason  # as vazias não contam


def test_coluna_constante():
    df = _df(variavel=["Frota"] * 10, ano=["2024"] * 10, uf=["ES"] * 10, v=[str(i) for i in range(10)])
    s = _unica(df, "coluna_constante")
    assert s.steps == ({"op": "drop_cols", "cols": ["variavel"]},)  # ano e UF diferenciam arquivos
    assert s.order > sug.FORMA


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------


def test_sentinela_vira_vazio():
    df = _df(
        temp=["21,5", "-9999", "23,0"], pressao=["887,1", "-9999", "886,0"], hora=["0000", "0100", "0200"]
    )
    s = _unica(df, "sentinela")
    assert s.steps == (
        {"op": "replace", "cols": ["temp", "pressao"], "old": "-9999", "new": None, "whole": True},
    )
    assert s.order < sug.CONVERSAO


def test_9999_dentro_da_faixa_nao_e_sentinela():
    assert not _regra(_df(v=["9999", "12000", "500"]), "sentinela")


def test_ponto_decimal_decidido_pela_tabela():
    """'104.000' sozinho seria cento e quatro mil; a outra coluna mostra que
    a fonte usa ponto decimal."""
    df = _df(volume=["104.000", "12.000"], cota=["0.5", "321.25"])
    s = _unica(df, "decimal_br")
    assert s.steps == ({"op": "parse_decimal_br", "cols": ["volume", "cota"], "decimal": "."},)


def test_virgula_em_alguma_coluna_fica_auto():
    df = _df(a=["104.000", "1.234,5"], b=["0.5", "2"])
    assert _unica(df, "decimal_br").steps[0]["decimal"] == "auto"


def test_inteiro_em_texto_e_em_decimal():
    df = pl.DataFrame(
        {
            "qtd": ["10", "200", "-3"],
            "pop": [1532.0, 7.0, None],
            "valor": [10.0, 20.0, 30.0],
            "nome": ["a", "b", "c"],
        }
    )
    s = _unica(df, "inteiro")
    assert s.steps == ({"op": "cast", "types": {"qtd": "int", "pop": "int"}},)  # valor é dinheiro
    assert not _regra(df, "decimal_br")  # a contagem não vira decimal


def test_mes_e_ano_em_colunas_separadas():
    df = _df(municipio=["a", "b"], ANO=["2024", "2024"], Mês=["1", "12"])
    s = _unica(df, "mes_e_ano")
    assert s.steps == (
        {"op": "merge_cols", "cols": ["Mês", "ANO"], "separator": "/", "into": "data"},
        {"op": "parse_month_year", "cols": ["data"]},
    )


def test_mes_e_ano_em_texto():
    s = _unica(_df(periodo=["jan/2024", "fev/2024", "Março 2024"]), "mes_ano")
    assert s.steps == ({"op": "parse_month_year", "cols": ["periodo"]},)


def test_nota_de_rodape_no_nome():
    df = _df(produto=["Abacaxi*", "Banana", "Café (1)", "Milho"])
    assert _unica(df, "notas_de_rodape").steps == ({"op": "strip_footnotes", "cols": ["produto"]},)


@pytest.mark.parametrize(
    ("valores", "separador"),
    [
        (["1. Automóvel", "2. Moto", "10. Outros"], ". "),
        (["3.1 - Pessoal", "3.2 - Juros", "4 - Investimentos"], " - "),
    ],
)
def test_codigo_e_nome_na_mesma_celula(valores, separador):
    s = _unica(_df(tipo=valores), "codigo_e_rotulo")
    assert s.steps == (
        {"op": "split_col", "col": "tipo", "separator": separador, "into": ["tipo_codigo", "tipo_nome"]},
    )


# ---------------------------------------------------------------------------
# "Aceitar todas" por etapa
# ---------------------------------------------------------------------------


def test_etapas():
    assert [
        sug.etapa(o) for o in (sug.LIMPEZA, sug.CONVERSAO, sug.FORMA, sug.FORMA + 5, sug.VERIFICACAO)
    ] == [
        0,
        0,
        1,
        1,
        2,
    ]


def test_sugestao_que_cita_coluna_tirada_na_mesma_etapa_espera():
    """Mês e ano viram 'data'; a sugestão de inteiro para ANO voltaria a
    falhar depois do merge, então fica para a próxima rodada."""
    df = _df(cidade=["a", "b"], ANO=["2024", "2025"], Mês=["1", "2"], qtd=["3", "4"])
    regras = {s.rule: s for s in suggest(df)}
    assert "mes_e_ano" in regras
    assert regras["inteiro"].steps == ({"op": "cast", "types": {"qtd": "int"}},)


def test_aceitar_etapa_por_etapa_roda():
    from wolfz.core.engine import collect
    from wolfz.core.recipe import recipe_from_dict

    df = _df(
        Município=["Vitória", "Serra"],
        ANO=["2024", "2024"],
        Mês=["1", "1"],
        **{"1º Decêndio": ["1.5", "2"], "2º Decêndio": ["3", "4"], "3º Decêndio": ["5", "6"]},
        Item=["FPM", "FPM"],
    )
    passos: list[dict] = []
    tabela = df
    for _ in range(3):
        sugestoes = [s for s in suggest(tabela, steps=passos) if s.kind == "passo"]
        if not sugestoes:
            break
        primeira = min(sug.etapa(s.order) for s in sugestoes)
        passos += [p for s in sugestoes if sug.etapa(s.order) == primeira for p in s.steps]
        receita = recipe_from_dict(
            {
                "wolfz_version": "1.0",
                "name": "x",
                "created_at": "2026-01-01T00:00:00Z",
                "source": {"type": "csv"},
                "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
            }
        )
        tabela = collect(receita, df.lazy())
    assert {"data", "decendio", "valor"} <= set(tabela.columns)
    assert tabela["data"].to_list()[0] == date(2024, 1, 1)

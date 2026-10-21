"""Sugestões automáticas (F2.E): estrutura, regras, rejeição e falha isolada."""

import json
import logging
from pathlib import Path

import polars as pl
import pytest

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core import suggest as sug
from wolfz.core.engine import collect
from wolfz.core.recipe import recipe_from_dict
from wolfz.core.suggest import Suggestion, registered_rules, rule, suggest

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


def _df(**cols) -> pl.DataFrame:
    return pl.DataFrame(cols, schema=dict.fromkeys(cols, pl.String))


def _por_regra(df: pl.DataFrame) -> dict[str, list[Suggestion]]:
    saida: dict[str, list[Suggestion]] = {}
    for s in suggest(df):
        saida.setdefault(s.rule, []).append(s)
    return saida


def _aplica(df: pl.DataFrame, sugestoes: list[Suggestion]) -> pl.DataFrame:
    """Aceita as sugestões (em ordem) e roda: os passos têm de validar."""
    passos = [p for s in sugestoes for p in s.steps]
    receita = recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )
    return collect(receita, df.lazy())


# ---------------------------------------------------------------------------
# Estrutura (F2.E1)
# ---------------------------------------------------------------------------


def test_regras_registradas():
    suggest(_df(a=["x"]))  # carrega as regras
    assert set(registered_rules()) >= {
        "moeda",
        "decimal_br",
        "data",
        "percentual",
        "coluna_vazia",
        "espacos",
        "duplicadas",
        "meses_lado_a_lado",
        "variacao_categoria",
        "documento",
        "cep",
        "codigo_zero_esquerda",
        "sinais_ibge",
        "mojibake",
    }


def test_sugestao_tem_passo_confianca_e_motivo():
    (s,) = suggest(_df(valor=["R$ 1.234,56", "R$ 10,00", "(5,00)"], nome=["a", "b", "c"]))
    assert s.rule == "moeda"
    assert s.steps == ({"op": "parse_brl", "cols": ["valor"]},)
    assert 0.6 <= s.confidence <= 1
    assert "'valor'" in s.reason and "R$ 1.234,56" in s.reason
    assert s.to_dict()["id"] == "moeda:valor"


def test_regra_com_erro_vai_para_o_log_e_as_outras_continuam(caplog):
    @rule
    def regra_quebrada(ctx):
        raise RuntimeError("bug na regra")

    try:
        with caplog.at_level(logging.ERROR, logger="wolfz.suggest"):
            sugestoes = suggest(_df(valor=["R$ 1,00", "R$ 2,00"]))
        assert [s.rule for s in sugestoes] == ["moeda"]
        assert "regra_quebrada" in caplog.text
        assert "bug na regra" in caplog.text
    finally:
        sug._REGRAS.pop("regra_quebrada")


def test_registrar_duas_regras_com_o_mesmo_nome():
    def moeda(ctx):
        return []

    with pytest.raises(ValueError, match="já registrada"):
        rule(moeda)


def test_rejeitada_por_coluna_e_por_regra():
    df = _df(a=["R$ 1,00", "R$ 2,00"], b=["R$ 3,00", "R$ 4,00"], c=["x", "y"])
    (s,) = suggest(df, rejected=[("moeda", "a")])
    assert s.cols == ("b",) and s.steps[0]["cols"] == ["b"]
    assert suggest(df, rejected=[("moeda", "a"), ("moeda", "b")]) == []
    assert suggest(df, rejected=[("moeda", None)]) == []


def test_ordem_limpar_converter_e_mudar_a_forma():
    df = _df(
        produto=[" Arroz", "Feijão", "Feijão"],
        jan=["1,5", "2,0", "2,0"],
        fev=["3,0", "4,0", "4,0"],
        mar=["5,0", "6,0", "6,0"],
    )
    sugestoes = suggest(df)
    assert [s.rule for s in sugestoes] == ["espacos", "decimal_br", "duplicadas", "meses_lado_a_lado"]
    saida = _aplica(df, sugestoes)
    assert saida.columns == ["produto", "mes", "valor"]
    assert saida.height == 6


# ---------------------------------------------------------------------------
# Regras (F2.E2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("colunas", "regra", "passo"),
    [
        (
            {"v": ["1.234,56", "10,5", "7"]},
            "decimal_br",
            {"op": "parse_decimal_br", "cols": ["v"], "decimal": "auto"},
        ),
        (
            {"saldo": ["5.000,00 D", "10,00 C", "1,00"]},
            "decimal_br",
            {"op": "parse_decimal_br", "cols": ["saldo"], "decimal": "auto", "debit_negative": True},
        ),
        ({"d": ["31/12/2024", "01/01/2025"]}, "data", {"op": "parse_date_br", "cols": ["d"]}),
        (
            {"d": ["20241231", "20250101"]},
            "data",
            {"op": "parse_date_br", "cols": ["d"], "eight_digits": "ymd"},
        ),
        (
            {"d": ["24102021", "31012020"]},
            "data",
            {"op": "parse_date_br", "cols": ["d"], "eight_digits": "dmy"},
        ),
        ({"p": ["12%", "3,5%"]}, "percentual", {"op": "parse_percent", "cols": ["p"]}),
        ({"a": ["x", "y"], "vazia": [None, "N/D"]}, "coluna_vazia", {"op": "drop_cols", "cols": ["vazia"]}),
        ({"t": [" a", "b"]}, "espacos", {"op": "trim", "cols": ["t"]}),
        (
            {"t": ["a  b", "c" + chr(0xA0) + "d"]},
            "espacos",
            {"op": "trim", "cols": ["t"], "collapse_spaces": True},
        ),
        ({"t": ["SÃ£o Paulo", "Rio"]}, "mojibake", {"op": "fix_mojibake", "cols": ["t"]}),
        (
            {"v": ["5556", "-", "..", "X", "12"]},
            "sinais_ibge",
            {"op": "parse_ibge_value", "cols": ["v"]},
        ),
        (
            {"cpf": ["529.982.247-25", "1234567890", "11144477735"]},
            "documento",
            {"op": "clean_cpf", "cols": ["cpf"]},
        ),
        (
            {"cnpj": ["11.222.333/0001-81", "191", "11222333000181"]},
            "documento",
            {"op": "clean_cnpj", "cols": ["cnpj"]},
        ),
        ({"CEP": ["29100-000", "1310100", "29100000"]}, "cep", {"op": "clean_cep", "cols": ["CEP"]}),
    ],
)
def test_regra(colunas, regra, passo):
    df = _df(**colunas)
    achadas = _por_regra(df).get(regra, [])
    assert [s.steps for s in achadas] == [(passo,)]
    _aplica(df, achadas)


def test_cpf_e_cnpj_na_mesma_coluna_com_tipo_de_pessoa():
    df = _df(
        doc=["529.982.247-25", "11.222.333/0001-81", "11144477735", "191"],
        tipo_pessoa=["F", "J", "F", "J"],
    )
    (s,) = _por_regra(df)["documento"]
    assert s.steps == ({"op": "clean_cpf_cnpj", "col": "doc", "person_type_col": "tipo_pessoa"},)


def test_variacao_de_caixa_e_acento():
    df = _df(uf=["São Paulo", "SAO PAULO", "são paulo", "Rio", "Rio", "Rio"])
    (s,) = _por_regra(df)["variacao_categoria"]
    assert s.steps == (
        {"op": "case", "cols": ["uf"], "mode": "title"},
        {"op": "remove_accents", "cols": ["uf"]},
    )
    assert _aplica(df, [s])["uf"].n_unique() == 2


def test_duplicadas_na_tabela_inteira():
    """A amostra pode não ver a linha repetida; a regra olha a tabela inteira."""
    df = _df(a=[str(i) for i in range(20_000)] + ["5"], b=["x"] * 20_001)
    (s,) = _por_regra(df)["duplicadas"]
    assert s.steps == ({"op": "dedupe"},)
    assert "1 linha repetida" in s.reason


def test_meses_lado_a_lado():
    df = _df(item=["a"], jan=["1"], fev=["2"], **{"mar/24": ["3"]})
    (s,) = _por_regra(df)["meses_lado_a_lado"]
    assert s.steps == ({"op": "unpivot", "index": ["item"], "variable_name": "mes", "value_name": "valor"},)


def test_codigo_com_zero_a_esquerda_e_aviso_sem_passo():
    df = _df(cod_ibge=["0012", "0034", "0101"], conta=["1", "12", "123"])
    avisos = _por_regra(df)["codigo_zero_esquerda"]
    assert all(s.kind == "aviso" and s.steps == () for s in avisos)
    assert [s.cols for s in avisos] == [("cod_ibge",), ("conta",)]
    assert "decimal_br" not in _por_regra(df)


# ---------------------------------------------------------------------------
# O que não pode ser sugerido
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "colunas",
    [
        {"Cód.": ["3205309", "3205200"]},  # código IBGE
        {"CD_MUN": ["1100015", "1100023"]},
        {"codTipoOrgao": ["1", "2"]},
        {"Id_SERVIDOR": ["123", "456"]},
        {"CNPJ": ["40884946000182", "11222333000181"]},  # já limpo
        {"cpf": ["52998224725", "11144477735"]},  # já limpo
    ],
)
def test_codigo_nao_vira_numero(colunas):
    regras = _por_regra(_df(**colunas))
    assert "decimal_br" not in regras and "documento" not in regras


def test_data_de_7_digitos_nao_e_cep():
    assert "cep" not in _por_regra(_df(DTNASC=["1032021", "24102021", "5012020"]))


def test_numero_de_casa_nao_tem_debito():
    (s,) = _por_regra(_df(numero=["123", "45C", "7"]))["decimal_br"] or [None]
    assert s is None or "debit_negative" not in s.steps[0]


def test_coluna_ja_convertida_nao_e_sugerida():
    df = pl.DataFrame({"v": [1.5, 2.0]})
    assert suggest(df) == []


def test_tabela_vazia():
    assert suggest(pl.DataFrame()) == []
    assert suggest(_df(a=[])) == []


# ---------------------------------------------------------------------------
# Corpus: aceitar todas as sugestões dá uma receita que roda
# ---------------------------------------------------------------------------


def _corpus():
    for pasta in sorted(CORPUS.iterdir()):
        if pasta.is_dir() and not pasta.name.startswith("_") and list(pasta.glob("original.*")):
            yield pytest.param(pasta, id=pasta.name)


@pytest.mark.parametrize("pasta", list(_corpus()))
def test_aceitar_todas_no_corpus(pasta):
    from wolfz.core.detect import detect_structure
    from wolfz.core.ingest import detect_format, read_sheet
    from wolfz.core.ingest.csv import open_csv_lazy

    aba = json.loads((pasta / "estrutura_esperada.json").read_text(encoding="utf-8"))["aba"]
    original = next(pasta.glob("original.*"))
    if detect_format(original) == "csv":
        with open_csv_lazy(original, has_header=False) as lf:
            df, estrutura = lf.collect(), None
    else:
        dados = read_sheet(original, aba)
        df, estrutura = dados.frame, dados.structure
    passos = detect_structure(df, estrutura).to_steps()
    inicial = recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )
    tabela = collect(inicial, df.lazy())
    # Como o "aceitar todas" da interface: uma etapa por vez (limpar e
    # converter, mudar a forma, verificar), recalculando entre elas.
    resultado, passos = tabela, list(inicial.model_dump(mode="json")["steps"])
    for _ in range(3):
        sugestoes = [s for s in suggest(resultado, steps=passos) if s.kind == "passo"]
        if not sugestoes:
            break
        primeira = min(sug.etapa(s.order) for s in sugestoes)
        da_etapa = [s for s in sugestoes if sug.etapa(s.order) == primeira]
        resultado = _aplica(resultado, da_etapa)
        passos += [p for s in da_etapa for p in s.steps]
    assert resultado.height > 0
    # Aceitas, as sugestões de passo não voltam (a não ser despivotar, que
    # gera colunas novas de texto).
    depois = {s.rule for s in suggest(resultado) if s.kind == "passo"}
    assert not depois & {"moeda", "decimal_br", "data", "percentual", "mojibake", "coluna_vazia"}

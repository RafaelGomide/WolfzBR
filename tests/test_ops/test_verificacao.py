"""``assert`` (F2.F1): reprova com mensagem, igual no motor e no script, e
no M vira um erro que derruba o refresh."""

import re
from datetime import date

import polars as pl
import pytest

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.engine import StepError, collect
from wolfz.core.recipe import RecipeError, recipe_from_dict
from wolfz.export.m import recipe_to_m
from wolfz.export.python import recipe_to_python


def _receita(**passo):
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": "s1", "op": "assert", **passo}],
        }
    )


def _script(receita, df):
    namespace: dict = {}
    exec(compile(recipe_to_python(receita), "<script>", "exec"), namespace)
    return namespace["transform"](df.lazy()).collect()


@pytest.mark.parametrize(
    ("passo", "df", "mensagem"),
    [
        (
            {"check": "not_null", "cols": ["cpf"]},
            pl.DataFrame({"cpf": ["1", " ", None]}),
            "'cpf' tem 2 linhas vazias: 2 e 3",
        ),
        (
            {"check": "unique", "cols": ["uf", "ano"]},
            pl.DataFrame({"uf": ["ES", "RJ", "ES"], "ano": ["2024", "2024", "2024"]}),
            "'uf', 'ano' se repete em 2 linhas: 1 e 3",
        ),
        (
            {"check": "in_range", "cols": ["v"], "min": 0, "max": 10},
            pl.DataFrame({"v": [5.0, None, 11.0, -1.0]}),
            "'v' tem 2 linhas fora da faixa 0.0 a 10.0: 3 e 4",
        ),
        (
            {"check": "in_range", "cols": ["d"], "min": "2024-01-01"},
            pl.DataFrame({"d": [date(2024, 5, 1), date(2023, 12, 31)]}),
            "'d' tem 1 linha fora da faixa 2024-01-01 a …: 2",
        ),
        (
            {"check": "matches", "cols": ["cep"], "pattern": r"\d{8}"},
            pl.DataFrame({"cep": ["29100000", "29100-000", None]}),
            "'cep' tem 1 linha fora do padrão: 2",
        ),
        (
            {"check": "row_count_min", "min_rows": 3},
            pl.DataFrame({"a": ["x"]}),
            "a tabela tem 1 linhas; o mínimo é 3",
        ),
    ],
)
def test_reprova_com_mensagem_no_motor_e_no_script(passo, df, mensagem):
    receita = _receita(**passo)
    with pytest.raises(StepError) as exc:
        collect(receita, df.lazy())
    assert exc.value.title == "Verificação reprovada"
    assert exc.value.step_id == "s1"
    assert mensagem in exc.value.message
    assert exc.value.verificacao["verificacao"] == passo["check"]
    with pytest.raises(AssertionError, match=re.escape(mensagem)):
        _script(receita, df)


def test_mensagem_sem_valor_de_celula_e_com_ate_5_linhas():
    """S2/R1: coluna, quantidade e até 5 linhas; o valor fica à parte, só
    para o --show-values do terminal."""
    df = pl.DataFrame({"cpf": ["080.637.303-21QXZ"] * 8})
    with pytest.raises(StepError) as exc:
        collect(_receita(check="unique", cols=["cpf"]), df.lazy())
    erro = exc.value
    assert erro.message.endswith("'cpf' se repete em 8 linhas: 1, 2, 3, 4, 5 e mais 3")
    assert "QXZ" not in erro.message and "080" not in erro.message
    assert erro.verificacao == {
        "verificacao": "unique",
        "coluna": "cpf",
        "quantidade": 8,
        "linhas": [1, 2, 3, 4, 5],
    }
    assert erro.valores[0] == "080.637.303-21QXZ"
    linhas = pl.DataFrame({"v": [f"x{i}QXZ" for i in range(1500)]})
    with pytest.raises(StepError) as exc:
        collect(_receita(check="matches", cols=["v"], pattern=r"\d+"), linhas.lazy())
    assert exc.value.message.endswith("'v' tem 1500 linhas fora do padrão: 1, 2, 3, 4, 5 e mais 1.495")
    assert "QXZ" not in exc.value.message


def test_aprovada_nao_muda_nada():
    df = pl.DataFrame({"v": [1.0, 2.0]})
    assert collect(_receita(check="in_range", cols=["v"], min=0), df.lazy()).equals(df)


def test_faixa_em_texto_pede_conversao():
    with pytest.raises(StepError, match="converta para número ou data"):
        collect(_receita(check="in_range", cols=["v"], max=1), pl.DataFrame({"v": ["1"]}).lazy())


@pytest.mark.parametrize(
    ("passo", "erro"),
    [
        ({"check": "not_null"}, "precisa de cols"),
        ({"check": "in_range", "cols": ["v"]}, "min, max"),
        ({"check": "matches", "cols": ["v"]}, "precisa de pattern"),
        ({"check": "matches", "cols": ["v"], "pattern": "("}, "pattern inválida"),
        ({"check": "row_count_min"}, "precisa de min_rows"),
        ({"check": "row_count_min", "min_rows": 0}, "greater than or equal"),
    ],
)
def test_parametros(passo, erro):
    with pytest.raises(RecipeError, match=erro):
        _receita(**passo)


def test_m_derruba_o_refresh_com_mensagem():
    m = recipe_to_m(_receita(check="not_null", cols=["cpf"]))
    assert 'error Error.Record("WolfzBR: verificação reprovada", mensagem' in m
    assert 'WolfzVazia(Record.Field(_, "cpf"))' in m
    assert "#date(2024, 1, 1)" in recipe_to_m(_receita(check="in_range", cols=["d"], min="2024-01-01"))


def test_m_nao_tem_regex_e_avisa():
    m = recipe_to_m(_receita(check="matches", cols=["cep"], pattern=r"\d{8}"))
    assert "matches não é verificado no Power Query" in m
    assert r"\d{8}" not in m  # o padrão não vai para o comentário

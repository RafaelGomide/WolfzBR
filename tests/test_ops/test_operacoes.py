"""Testes específicos de cada operação: validação dos parâmetros, casos de
borda e o M gerado. A equivalência Polars × Python fica em
``tests/test_export/test_equivalencia.py``."""

import polars as pl
import pytest

import wolfz.ops  # noqa: F401
from wolfz.core.recipe import RecipeError, recipe_from_dict
from wolfz.ops import DropRowsWhere, ParseBrl, Rename


def _errors(step: dict) -> list[str]:
    data = {
        "wolfz_version": "0.1",
        "name": "x",
        "created_at": "2026-01-01T00:00:00Z",
        "source": {"type": "csv"},
        "steps": [{"id": "s1", **step}],
    }
    with pytest.raises(RecipeError) as exc:
        recipe_from_dict(data)
    return exc.value.errors


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ({}, "s1.mapping: precisa de pelo menos 1 item(ns)"),
        ({"a": " "}, "s1.mapping: nome de coluna não pode ser vazio"),
        ({"a": "x", "b": "x"}, "s1.mapping: mais de uma coluna renomeada para 'x'"),
    ],
)
def test_rename_validacao(mapping, expected):
    assert _errors({"op": "rename", "mapping": mapping}) == [expected]


def test_rename_coluna_inexistente_falha_na_execucao():
    step = Rename(id="s1", op="rename", mapping={"nao_existe": "x"})
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        step.to_polars(pl.LazyFrame({"a": ["1"]})).collect()


def test_rename_m_escapa_nomes():
    step = Rename(id="s3", op="rename", mapping={'Nº "Pedido"': "pedido", "a#(b": "c\nd"})
    assert step.to_m("s2", "s3") == (
        's3 = Table.RenameColumns(s2, {{"Nº ""Pedido""", "pedido"}, {"a#(#)(b", "c#(lf)d"}})'
    )


# ---------------------------------------------------------------------------
# drop_rows_where
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            {"col": "a", "match": "in", "value": "x"},
            "s1: com match 'in', value deve ser uma lista não vazia",
        ),
        (
            {"col": "a", "match": "equals", "value": ["x"]},
            "s1: com match 'equals', value deve ser um texto não vazio",
        ),
        ({"col": "a", "match": "regex", "value": "x"}, "s1.match: valor inválido"),
        ({"col": "", "match": "equals", "value": "x"}, "s1.col: não pode ser vazio"),
    ],
)
def test_drop_rows_where_validacao(step, expected):
    errors = _errors({"op": "drop_rows_where", **step})
    assert len(errors) == 1
    assert errors[0].startswith(expected)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"match": "equals", "value": "x"}, 'v = "x"'),
        ({"match": "equals", "value": "x", "ignore_case": True}, 'Comparer.OrdinalIgnoreCase(v, "x") = 0'),
        ({"match": "starts_with", "value": "Total"}, 'Text.StartsWith(v, "Total")'),
        (
            {"match": "contains", "value": "a", "ignore_case": True},
            'Text.Contains(v, "a", Comparer.OrdinalIgnoreCase)',
        ),
        ({"match": "in", "value": ["a", 'b"']}, 'List.Contains({"a", "b"""}, v)'),
    ],
)
def test_drop_rows_where_m(params, expected):
    step = DropRowsWhere(id="s2", op="drop_rows_where", col="Região", **params)
    prefix = (
        's2 = Table.SelectRows(s1, each let v = Text.From(Record.Field(_, "Região")) in v = null or not ('
    )
    assert step.to_m("s1", "s2") == f"{prefix}{expected}))"


def test_drop_rows_where_coluna_numerica():
    step = DropRowsWhere(id="s1", op="drop_rows_where", col="n", match="equals", value="2")
    out = step.to_polars(pl.LazyFrame({"n": [1, 2, None]})).collect()
    assert out["n"].to_list() == [1, None]


# ---------------------------------------------------------------------------
# parse_brl
# ---------------------------------------------------------------------------


def test_parse_brl_validacao():
    assert _errors({"op": "parse_brl", "cols": []}) == ["s1.cols: precisa de pelo menos 1 item(ns)"]


def test_parse_brl_m():
    step = ParseBrl(id="s4", op="parse_brl", cols=["valor", 'a"b'], debit_negative=True)
    assert step.to_m("s3", "s4") == (
        "s4 = Table.TransformColumns(s3, {"
        '{"valor", each WolfzParseBrl(_, true), type nullable number}, '
        '{"a""b", each WolfzParseBrl(_, true), type nullable number}})'
    )
    assert "WolfzParseBrl" in step.m_helpers


def test_parse_brl_coluna_toda_nula():
    step = ParseBrl(id="s1", op="parse_brl", cols=["v"])
    out = step.to_polars(pl.LazyFrame({"v": [None, None]}, schema={"v": pl.String})).collect()
    assert out.schema["v"] == pl.Float64
    assert out["v"].to_list() == [None, None]

"""Operações de padrões brasileiros: aplicam as funções de ``wolfz.br`` em
colunas."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import polars as pl
from pydantic import Field

from wolfz.br.numeros import parse_brl
from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_text


def map_unique(fn: Callable[[Any], Any], dtype: pl.DataType) -> Callable[[pl.Series], pl.Series]:
    """Aplica uma função de valor a uma coluna rodando-a uma vez por valor
    distinto. Colunas de relatório repetem muito (datas, categorias), então
    é bem mais rápido que linha a linha."""

    def apply(s: pl.Series) -> pl.Series:
        uniques = s.drop_nulls().unique()
        mapped = pl.Series([fn(v) for v in uniques], dtype=dtype)
        return s.replace_strict(uniques, mapped, default=None, return_dtype=dtype)

    return apply


# Tradução para M da regra de ``parse_brl``, só para o padrão brasileiro.
# Diferenças conhecidas em relação ao Polars (validadas à mão no Power BI
# Desktop, F2.A): número no padrão americano ('1,234.56') vira null no M,
# e os símbolos de moeda são reconhecidos só em maiúsculas.
_M_PARSE_BRL = """
(valor as any, debitoNegativo as logical) as nullable number =>
    let
        semMoeda = if valor = null then "" else List.Accumulate(
            {"US$", "U$", "R$", "€", "BRL", "USD", "EUR", "$", "#(00A0)"},
            Text.From(valor),
            (texto, simbolo) => Text.Replace(texto, simbolo, " ")
        ),
        t0 = Text.Trim(semMoeda),
        ultimo = Text.Upper(Text.End(t0, 1)),
        temDC = Text.Length(t0) > 1 and (ultimo = "D" or ultimo = "C"),
        t1 = if temDC then Text.Trim(Text.Start(t0, Text.Length(t0) - 1)) else t0,
        parenteses = Text.StartsWith(t1, "(") and Text.EndsWith(t1, ")"),
        t2 = if parenteses then Text.Trim(Text.Middle(t1, 1, Text.Length(t1) - 2)) else t1,
        menosNoFim = Text.Length(t2) > 1 and Text.EndsWith(t2, "-"),
        t3 = Text.Remove(if menosNoFim then Text.Start(t2, Text.Length(t2) - 1) else t2, {" "}),
        sinais = List.Count(List.Select(
            {temDC and ultimo = "D" and debitoNegativo, parenteses, menosNoFim}, each _ = true
        )),
        numero =
            if t3 = "-" or t3 = "#(2013)" or t3 = "#(2014)" then 0
            else if t3 = "" or Text.Contains(t3, "%") then null
            else try Number.FromText(t3, "pt-BR") otherwise null
    in
        if numero = null then null else if Number.IsOdd(sinais) then -numero else numero
"""


@register_op
class ParseBrl(Op):
    """Converte moeda brasileira em número: 'R$ 1.234,56' -> 1234.56.

    Aceita negativo contábil '(1.234,56)', menos no fim (SAP), '-' como zero
    (formato contábil do Excel) e, com ``debit_negative``, sufixo D/C com
    débito negativo. Valor que não é moeda vira nulo, nunca um número
    errado (ver ``wolfz.br.numeros.parse_brl``)."""

    op: Literal["parse_brl"]
    cols: list[str] = Field(min_length=1)
    debit_negative: bool = False

    python_helpers = (parse_brl,)
    m_helpers = {"WolfzParseBrl": _M_PARSE_BRL}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["valor"]},
            "input": {
                "valor": ["R$ 1.234,56", "(1.234,56)", "1.234,56-", "R$ -", "#N/D", None, "12%", "1,5E+3"],
            },
            "expected": {"valor": [1234.56, -1234.56, -1234.56, 0.0, None, None, None, 1500.0]},
        },
        {
            "step": {"cols": ["debito", "credito"], "debit_negative": True},
            "input": {"debito": ["100,00 D", "50,00 C"], "credito": ["R$ 10", "abc"]},
            "expected": {"debito": [-100.0, 50.0], "credito": [10.0, None]},
        },
    )

    def _fn(self) -> Callable[[Any], float | None]:
        if self.debit_negative:
            return lambda v: parse_brl(v, debit_negative=True)
        return parse_brl

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        apply = map_unique(self._fn(), pl.Float64)
        return lf.with_columns(pl.col(c).map_batches(apply, return_dtype=pl.Float64) for c in self.cols)

    def to_m(self, prev: str, name: str) -> str:
        debit = "true" if self.debit_negative else "false"
        transforms = ", ".join(
            f"{{{m_text(c)}, each WolfzParseBrl(_, {debit}), type nullable number}}" for c in self.cols
        )
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"

    def to_python(self) -> str:
        fn = "lambda v: parse_brl(v, debit_negative=True)" if self.debit_negative else "parse_brl"
        return f"lf = lf.with_columns(pl.col({self.cols!r}).map_elements({fn}, return_dtype=pl.Float64))"

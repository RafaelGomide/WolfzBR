"""Operações de linha."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field, model_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_field, m_list, m_text


@register_op
class DropRowsWhere(Op):
    """Remove as linhas em que a coluna casa com a condição.

    Sem regex de propósito: Power Query M não tem expressão regular nativa,
    e toda operação precisa ter tradução fiel para M (ADR-2). Por isso a
    condição se limita ao que as funções de texto do M expressam:

    - ``equals``: valor igual a ``value``;
    - ``starts_with``: começa com ``value`` (``Text.StartsWith``);
    - ``contains``: contém ``value`` (``Text.Contains``);
    - ``in``: valor é um dos itens da lista ``value`` (``List.Contains``).

    A comparação é exata: espaços e acentos contam (normalize antes, se
    preciso). ``ignore_case`` ignora maiúsculas/minúsculas. Célula vazia
    (nula) nunca casa, então a linha fica."""

    op: Literal["drop_rows_where"]
    col: str = Field(min_length=1)
    match: Literal["equals", "starts_with", "contains", "in"]
    value: str | list[str]
    ignore_case: bool = False

    examples = (
        {
            "step": {"col": "regiao", "match": "starts_with", "value": "Total"},
            "input": {
                "regiao": ["Sul", "Total Sul", "Totalmente", None, "total"],
                "v": ["1", "2", "3", "4", "5"],
            },
            "expected": {"regiao": ["Sul", None, "total"], "v": ["1", "4", "5"]},
        },
        {
            "step": {"col": "regiao", "match": "contains", "value": "total", "ignore_case": True},
            "input": {"regiao": ["Sul", "Subtotal", "TOTAL", None], "v": ["1", "2", "3", "4"]},
            "expected": {"regiao": ["Sul", None], "v": ["1", "4"]},
        },
        {
            "step": {"col": "uf", "match": "equals", "value": "-"},
            "input": {"uf": ["ES", "-", " -", None]},
            "expected": {"uf": ["ES", " -", None]},
        },
        {
            "step": {"col": "uf", "match": "in", "value": ["xx", "Br"], "ignore_case": True},
            "input": {"uf": ["ES", "XX", "br", "SP"]},
            "expected": {"uf": ["ES", "SP"]},
        },
    )

    @model_validator(mode="after")
    def _value_combina_com_match(self) -> DropRowsWhere:
        if self.match == "in":
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("com match 'in', value deve ser uma lista não vazia")
        elif not isinstance(self.value, str) or not self.value:
            raise ValueError(f"com match {self.match!r}, value deve ser um texto não vazio")
        return self

    def _python_expr(self) -> str:
        """Condição como código Polars. É a mesma string que vai para o
        script exportado, e ``to_polars`` a monta igual."""
        col = f"pl.col({self.col!r}).cast(pl.String)"
        value = self.value
        if self.ignore_case:
            col += ".str.to_lowercase()"
            value = [v.lower() for v in value] if isinstance(value, list) else value.lower()
        method = {
            "equals": f" == {value!r}",
            "starts_with": f".str.starts_with({value!r})",
            "contains": f".str.contains({value!r}, literal=True)",
            "in": f".is_in({value!r})",
        }[self.match]
        return f"~({col}{method}).fill_null(False)"

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        col = pl.col(self.col).cast(pl.String)
        value = self.value
        if self.ignore_case:
            col = col.str.to_lowercase()
            value = [v.lower() for v in value] if isinstance(value, list) else value.lower()
        if self.match == "equals":
            cond = col == value
        elif self.match == "starts_with":
            cond = col.str.starts_with(value)
        elif self.match == "contains":
            cond = col.str.contains(value, literal=True)
        else:
            cond = col.is_in(value)
        return lf.filter(~cond.fill_null(False))

    def to_m(self, prev: str, name: str) -> str:
        comparer = ", Comparer.OrdinalIgnoreCase" if self.ignore_case else ""
        if self.match == "in":
            cond = f"List.Contains({m_list(self.value)}, v{comparer})"
        elif self.match == "equals":
            target = m_text(self.value)
            cond = f"Comparer.OrdinalIgnoreCase(v, {target}) = 0" if self.ignore_case else f"v = {target}"
        else:
            fn = "Text.StartsWith" if self.match == "starts_with" else "Text.Contains"
            cond = f"{fn}(v, {m_text(self.value)}{comparer})"
        value = f"Text.From({m_field(self.col)})"
        return f"{name} = Table.SelectRows({prev}, each let v = {value} in v = null or not ({cond}))"

    def to_python(self) -> str:
        return f"lf = lf.filter({self._python_expr()})"

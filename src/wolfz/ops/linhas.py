"""Operações de linha."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

import polars as pl
from pydantic import Field, model_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_field, m_list, m_text, m_value


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
    m_label = "Linhas removidas"
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


# ---------------------------------------------------------------------------
# Filtro, duplicatas, nulos e ordenação
# ---------------------------------------------------------------------------

Escalar = str | int | float | bool
_ISO = r"\d{4}-\d{2}-\d{2}"


def _alvo(valor: Any, dtype: Any) -> Any:
    """Valor da receita no tipo da coluna: data ISO ('2024-01-31') vira
    ``date`` quando a coluna é data."""
    if dtype == pl.Date and isinstance(valor, str) and re.fullmatch(_ISO, valor):
        return date.fromisoformat(valor)
    if isinstance(valor, list):
        return [_alvo(v, dtype) for v in valor]
    return valor


def filter_lf(lf: pl.LazyFrame, col: str, match: str, value: Any, ignore_case: bool) -> pl.LazyFrame:
    """Mantém as linhas em que a coluna casa com a condição. Célula nula só
    casa com ``is_null``."""
    alvo = _alvo(value, lf.collect_schema()[col])
    c = pl.col(col)
    if match in ("contains", "starts_with") or ignore_case:
        c = c.cast(pl.String)
        if ignore_case:
            c = c.str.to_lowercase()
            alvo = [str(v).lower() for v in alvo] if isinstance(alvo, list) else str(alvo).lower()
    if match == "is_null":
        cond = c.is_null()
    elif match == "not_null":
        cond = c.is_not_null()
    elif match == "contains":
        cond = c.str.contains(alvo, literal=True)
    elif match == "starts_with":
        cond = c.str.starts_with(alvo)
    elif match == "in":
        cond = c.is_in(alvo)
    elif match == "not_in":
        cond = ~c.is_in(alvo)
    else:
        cond = {
            "equals": c == alvo,
            "not_equals": c != alvo,
            "gt": c > alvo,
            "ge": c >= alvo,
            "lt": c < alvo,
            "le": c <= alvo,
        }[match]
    if match not in ("is_null", "not_null"):
        cond = c.is_not_null() & cond
    return lf.filter(cond.fill_null(False))


def _m_alvo(valor: Any) -> str:
    """Literal M; data ISO vira #date quando a célula é data."""
    if isinstance(valor, str) and re.fullmatch(_ISO, valor):
        a, m, d = (int(x) for x in valor.split("-"))
        return f"(if v is date then #date({a}, {m}, {d}) else {m_text(valor)})"
    return m_value(valor)


@register_op
class Filter(Op):
    """Mantém as linhas que atendem a uma condição sobre uma coluna.

    É uma DSL pequena, traduzível para M, e não uma expressão livre:
    ``equals``, ``not_equals``, ``gt``, ``ge``, ``lt``, ``le``, ``in``,
    ``not_in``, ``contains``, ``starts_with``, ``is_null`` e ``not_null``.
    Data é comparada com texto ISO ('2024-01-31'). Célula nula só passa em
    ``is_null``."""

    op: Literal["filter"]
    m_label = "Linhas filtradas"
    col: str = Field(min_length=1)
    match: Literal[
        "equals",
        "not_equals",
        "gt",
        "ge",
        "lt",
        "le",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "is_null",
        "not_null",
    ]
    value: Escalar | list[Escalar] | None = None
    ignore_case: bool = False

    python_helpers = (filter_lf,)
    examples = (
        {
            "step": {"col": "mes", "match": "in", "value": ["JAN", "FEV"]},
            "input": {"mes": ["JAN", "ANO", None, "FEV"], "v": ["1", "2", "3", "4"]},
            "expected": {"mes": ["JAN", "FEV"], "v": ["1", "4"]},
        },
        {
            "step": {"col": "v", "match": "ge", "value": 2},
            "input": {"v": [1, 2, None, 5]},
            "expected": {"v": [2, 5]},
        },
        {
            "step": {"col": "d", "match": "lt", "value": "2024-06-01"},
            "input": {
                "d": [__import__("datetime").date(2024, 1, 1), __import__("datetime").date(2025, 1, 1)]
            },
            "expected": {"d": [__import__("datetime").date(2024, 1, 1)]},
        },
        {
            "step": {"col": "nome", "match": "contains", "value": "silva", "ignore_case": True},
            "input": {"nome": ["Ana Silva", "Bia", None]},
            "expected": {"nome": ["Ana Silva"]},
        },
        {
            "step": {"col": "obs", "match": "is_null"},
            "input": {"obs": [None, "x"], "id": ["1", "2"]},
            "expected": {"obs": [None], "id": ["1"]},
        },
    )

    @model_validator(mode="after")
    def _valor_combina(self) -> Filter:
        if self.match in ("is_null", "not_null"):
            if self.value is not None:
                raise ValueError(f"{self.match} não usa value")
        elif self.match in ("in", "not_in"):
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"com {self.match}, value deve ser uma lista não vazia")
        elif self.value is None or isinstance(self.value, list):
            raise ValueError(f"com {self.match}, value deve ser um valor (texto, número ou booleano)")
        if self.match in ("contains", "starts_with") and not isinstance(self.value, str):
            raise ValueError(f"com {self.match}, value deve ser texto")
        return self

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return filter_lf(lf, self.col, self.match, self.value, self.ignore_case)

    def to_python(self) -> str:
        return f"lf = filter_lf(lf, {self.col!r}, {self.match!r}, {self.value!r}, {self.ignore_case!r})"

    def to_m(self, prev: str, name: str) -> str:
        v = "v"
        if self.match in ("contains", "starts_with") or self.ignore_case:
            v = "Text.From(v)"
        comparer = ", Comparer.OrdinalIgnoreCase" if self.ignore_case else ""
        if self.match == "is_null":
            cond = "v = null"
        elif self.match == "not_null":
            cond = "v <> null"
        else:
            alvo = _m_alvo(self.value)
            cond = {
                "equals": f"Value.Equals({v}, {alvo}{comparer})",
                "not_equals": f"not Value.Equals({v}, {alvo}{comparer})",
                "gt": f"v > {alvo}",
                "ge": f"v >= {alvo}",
                "lt": f"v < {alvo}",
                "le": f"v <= {alvo}",
                "in": f"List.Contains({alvo}, {v}{comparer})",
                "not_in": f"not List.Contains({alvo}, {v}{comparer})",
                "contains": f"Text.Contains({v}, {alvo}{comparer})",
                "starts_with": f"Text.StartsWith({v}, {alvo}{comparer})",
            }[self.match]
            cond = f"v <> null and {cond}"
        return f"{name} = Table.SelectRows({prev}, each let v = {m_field(self.col)} in {cond})"


@register_op
class Dedupe(Op):
    """Remove linhas repetidas, mantendo a primeira. Com ``cols``, compara
    só essas colunas; sem, a linha inteira."""

    op: Literal["dedupe"]
    m_label = "Duplicatas removidas"
    full_checkpoint = True  # compara a tabela inteira
    cols: list[str] | None = None

    examples = (
        {
            "step": {},
            "input": {"a": ["1", "1", "2", "1"], "b": ["x", "x", "y", "z"]},
            "expected": {"a": ["1", "2", "1"], "b": ["x", "y", "z"]},
        },
        {
            "step": {"cols": ["a"]},
            "input": {"a": ["1", "1", "2"], "b": ["x", "y", "z"]},
            "expected": {"a": ["1", "2"], "b": ["x", "z"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.unique(subset=self.cols, keep="first", maintain_order=True)

    def to_python(self) -> str:
        return f"lf = lf.unique(subset={self.cols!r}, keep='first', maintain_order=True)"

    def to_m(self, prev: str, name: str) -> str:
        if self.cols is None:
            return f"{name} = Table.Distinct({prev})"
        return f"{name} = Table.Distinct({prev}, {m_list(self.cols)})"


@register_op
class FillNull(Op):
    """Preenche células nulas com um valor fixo."""

    op: Literal["fill_null"]
    m_label = "Nulos preenchidos"
    cols: list[str] = Field(min_length=1)
    value: Escalar

    examples = (
        {
            "step": {"cols": ["obs"], "value": "sem observação"},
            "input": {"obs": [None, "ok"]},
            "expected": {"obs": ["sem observação", "ok"]},
        },
        {"step": {"cols": ["q"], "value": 0}, "input": {"q": [None, 3]}, "expected": {"q": [0, 3]}},
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.with_columns(pl.col(c).fill_null(pl.lit(self.value)) for c in self.cols)

    def to_python(self) -> str:
        return f"lf = lf.with_columns(pl.col(c).fill_null(pl.lit({self.value!r})) for c in {self.cols!r})"

    def to_m(self, prev: str, name: str) -> str:
        args = f"null, {m_value(self.value)}, Replacer.ReplaceValue, {m_list(self.cols)}"
        return f"{name} = Table.ReplaceValue({prev}, {args})"


@register_op
class Sort(Op):
    """Ordena pelas colunas de ``by``. ``descending`` vale para todas ou é
    uma lista, uma por coluna. Nulos ficam como no Power Query: no começo da
    ordem crescente e no fim da decrescente. Empate mantém a ordem original."""

    op: Literal["sort"]
    m_label = "Linhas classificadas"
    full_checkpoint = True  # reordena a tabela inteira
    by: list[str] = Field(min_length=1)
    descending: bool | list[bool] = False

    examples = (
        {
            "step": {"by": ["uf", "v"], "descending": [False, True]},
            "input": {"uf": ["SP", "ES", None, "ES"], "v": [1, 2, 3, 5]},
            "expected": {"uf": [None, "ES", "ES", "SP"], "v": [3, 5, 2, 1]},
        },
        {
            "step": {"by": ["v"], "descending": True},
            "input": {"v": [1, None, 3]},
            "expected": {"v": [3, 1, None]},
        },
    )

    @model_validator(mode="after")
    def _tamanhos(self) -> Sort:
        if isinstance(self.descending, list) and len(self.descending) != len(self.by):
            raise ValueError("descending precisa ter um valor por coluna de by")
        return self

    def _desc(self) -> list[bool]:
        return self.descending if isinstance(self.descending, list) else [self.descending] * len(self.by)

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        desc = self._desc()
        return lf.sort(self.by, descending=desc, nulls_last=desc, maintain_order=True)

    def to_python(self) -> str:
        desc = self._desc()
        return f"lf = lf.sort({self.by!r}, descending={desc!r}, nulls_last={desc!r}, maintain_order=True)"

    def to_m(self, prev: str, name: str) -> str:
        ordens = ", ".join(
            f"{{{m_text(c)}, {'Order.Descending' if d else 'Order.Ascending'}}}"
            for c, d in zip(self.by, self._desc(), strict=True)
        )
        return f"{name} = Table.Sort({prev}, {{{ordens}}})"

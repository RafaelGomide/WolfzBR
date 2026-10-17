"""Operações de coluna."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field, field_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_field, m_list, m_text


@register_op
class Rename(Op):
    """Renomeia colunas. Coluna de origem inexistente é erro na execução:
    a receita nunca renomeia "nada" em silêncio quando a planilha muda."""

    op: Literal["rename"]
    mapping: dict[str, str] = Field(
        min_length=1,
        description="Nome atual -> nome novo.",
        json_schema_extra={"examples": [{"Vlr": "valor"}]},
    )

    examples = (
        {
            "step": {"mapping": {"Vlr Venda": "valor", 'Nº "Pedido"': "pedido"}},
            "input": {"Vlr Venda": ["1"], 'Nº "Pedido"': ["7"], "UF": ["ES"]},
            "expected": {"valor": ["1"], "pedido": ["7"], "UF": ["ES"]},
        },
    )

    @field_validator("mapping")
    @classmethod
    def _nomes_validos(cls, mapping: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() for name in [*mapping, *mapping.values()]):
            raise ValueError("nome de coluna não pode ser vazio")
        targets = list(mapping.values())
        if dup := sorted({t for t in targets if targets.count(t) > 1}):
            raise ValueError(f"mais de uma coluna renomeada para {', '.join(map(repr, dup))}")
        return mapping

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.rename(self.mapping, strict=True)

    def to_m(self, prev: str, name: str) -> str:
        pairs = ", ".join(f"{{{m_text(a)}, {m_text(b)}}}" for a, b in self.mapping.items())
        return f"{name} = Table.RenameColumns({prev}, {{{pairs}}})"

    def to_python(self) -> str:
        return f"lf = lf.rename({self.mapping!r}, strict=True)"


# ---------------------------------------------------------------------------
# Funções auxiliares (copiadas para o script Python exportado)
# ---------------------------------------------------------------------------

NUMERO_PONTO = r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$"


def cast_expr(col: str, tipo: str) -> pl.Expr:
    """Conversão de uma coluna de texto (como a leitura entrega: ponto
    decimal, data ISO, 'true'/'false'). Valor que não converte vira nulo."""
    texto = pl.col(col).cast(pl.String).str.strip_chars()
    if tipo == "text":
        return pl.col(col).cast(pl.String)
    numero = pl.when(texto.str.contains(NUMERO_PONTO)).then(texto).cast(pl.Float64, strict=False)
    if tipo == "float":
        return numero
    if tipo == "int":
        return pl.when(numero == numero.floor()).then(numero).cast(pl.Int64, strict=False)
    if tipo == "date":
        return texto.str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False)
    minusculo = texto.str.to_lowercase()
    return pl.when(minusculo == "true").then(True).when(minusculo == "false").then(False)


def split_col_lf(lf: pl.LazyFrame, col: str, delimiter: str, into: list[str]) -> pl.LazyFrame:
    """Divide a coluna no lugar dela. A última parte fica com o resto do
    texto ('a;b;c' em 2 partes: 'a' e 'b;c'); parte que falta fica nula."""
    nomes = lf.collect_schema().names()
    if repetidos := sorted(set(into) & (set(nomes) - {col})):
        raise ValueError(f"já existem colunas chamadas {', '.join(map(repr, repetidos))}")
    pos = nomes.index(col)
    partes = pl.col(col).cast(pl.String).str.splitn(delimiter, len(into)).struct.rename_fields(into)
    lf = lf.with_columns(partes.alias("__partes__")).drop(col).unnest("__partes__")
    return lf.select([*nomes[:pos], *into, *nomes[pos + 1 :]])


def merge_cols_lf(lf: pl.LazyFrame, cols: list[str], separator: str, into: str, keep: bool) -> pl.LazyFrame:
    """Junta as colunas em ``into``, na posição da primeira delas. Célula
    nula é pulada (não deixa separador sobrando)."""
    nomes = lf.collect_schema().names()
    pos = min(nomes.index(c) for c in cols)
    juntas = pl.concat_str([pl.col(c).cast(pl.String) for c in cols], separator=separator, ignore_nulls=True)
    resto = list(nomes) if keep else [c for c in nomes if c not in cols]
    if into in resto:
        raise ValueError(f"já existe uma coluna chamada {into!r}")
    ordem = [*resto[:pos], into, *resto[pos:]]
    return lf.with_columns(juntas.alias(into)).select(ordem)


# ---------------------------------------------------------------------------
# Operações
# ---------------------------------------------------------------------------


@register_op
class DropCols(Op):
    """Remove colunas. Coluna inexistente é erro: a receita nunca remove
    "nada" em silêncio quando a planilha muda."""

    op: Literal["drop_cols"]
    cols: list[str] = Field(min_length=1)

    examples = (
        {
            "step": {"cols": ["obs", "id"]},
            "input": {"id": ["1"], "nome": ["Ana"], "obs": ["x"]},
            "expected": {"nome": ["Ana"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.drop(self.cols, strict=True)

    def to_python(self) -> str:
        return f"lf = lf.drop({self.cols!r}, strict=True)"

    def to_m(self, prev: str, name: str) -> str:
        return f"{name} = Table.RemoveColumns({prev}, {m_list(self.cols)})"


@register_op
class Reorder(Op):
    """Põe as colunas na ordem pedida. Com ``keep_rest`` (padrão), as
    colunas não citadas vêm depois, na ordem em que estavam; sem ele, saem."""

    op: Literal["reorder"]
    cols: list[str] = Field(min_length=1)
    keep_rest: bool = True

    examples = (
        {
            "step": {"cols": ["valor", "data"]},
            "input": {"data": ["d"], "uf": ["ES"], "valor": ["1"], "obs": ["o"]},
            "expected": {"valor": ["1"], "data": ["d"], "uf": ["ES"], "obs": ["o"]},
        },
        {
            "step": {"cols": ["valor", "data"], "keep_rest": False},
            "input": {"data": ["d"], "uf": ["ES"], "valor": ["1"]},
            "expected": {"valor": ["1"], "data": ["d"]},
        },
    )

    @field_validator("cols")
    @classmethod
    def _sem_repeticao(cls, cols: list[str]) -> list[str]:
        if len(set(cols)) != len(cols):
            raise ValueError("coluna repetida em cols")
        return cols

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        if not self.keep_rest:
            return lf.select(self.cols)
        return lf.select([*self.cols, pl.exclude(self.cols)])

    def to_python(self) -> str:
        if not self.keep_rest:
            return f"lf = lf.select({self.cols!r})"
        return f"lf = lf.select([*{self.cols!r}, pl.exclude({self.cols!r})])"

    def to_m(self, prev: str, name: str) -> str:
        cols = m_list(self.cols)
        if not self.keep_rest:
            return f"{name} = Table.SelectColumns({prev}, {cols})"
        resto = f"List.Difference(Table.ColumnNames({prev}), {cols})"
        return f"{name} = Table.SelectColumns({prev}, {cols} & {resto})"


Tipo = Literal["text", "int", "float", "date", "bool"]

_M_CAST = {
    "text": ('if _ = null then null else Text.From(_, "en-US")', "type nullable text"),
    "float": ("WolfzNumeroPonto(_)", "type nullable number"),
    "int": (
        "let x = WolfzNumeroPonto(_) in if x <> null and Number.Round(x) = x "
        "then try Int64.From(x) otherwise null else null",
        "Int64.Type",
    ),
    "date": (
        "if _ is date then _ else if _ is datetime then Date.From(_) else if _ = null then null else "
        'try Date.FromText(Text.Start(Text.Trim(Text.From(_)), 10), [Format="yyyy-MM-dd", Culture="en-US"]) '
        "otherwise null",
        "type nullable date",
    ),
    "bool": (
        "if _ is logical then _ else if _ = null then null else "
        'let t = Text.Lower(Text.Trim(Text.From(_))) in if t = "true" then true '
        'else if t = "false" then false else null',
        "type nullable logical",
    ),
}

# Número com ponto decimal, como a leitura entrega ('1234.5', '-3', '1e3').
# Vírgula de milhar não é aceita, para bater com o Polars.
_M_NUMERO_PONTO = """
(v as any) as nullable number =>
    if v is number then v
    else if v = null then null
    else
        let t = Text.Trim(Text.From(v))
        in if t = "" or Text.Contains(t, ",") or Text.Contains(t, " ")
            or not List.Contains({"0".."9", "."}, Text.End(t, 1))
        then null
        else try Number.FromText(t, "en-US") otherwise null
"""

_DATA = __import__("datetime").date


@register_op
class Cast(Op):
    """Converte o tipo das colunas: ``text``, ``int``, ``float``, ``date``
    ou ``bool``. Pensado para os valores como a leitura entrega (número com
    ponto decimal, data ISO, 'true'/'false'). Para número e data em formato
    brasileiro, use ``parse_decimal_br`` e ``parse_date_br``. Valor que não
    converte vira nulo; ``int`` com casas decimais também."""

    op: Literal["cast"]
    types: dict[str, Tipo] = Field(min_length=1)

    python_helpers = (cast_expr,)
    m_helpers = {"WolfzNumeroPonto": _M_NUMERO_PONTO}  # noqa: RUF012
    examples = (
        {
            "step": {"types": {"q": "int", "v": "float", "d": "date", "b": "bool", "t": "text"}},
            "input": {
                "q": ["12", " 3 ", "1.5", "abc", None],
                "v": ["1234.5", "-0.25", "1e3", "1,234", "inf"],
                "d": ["2024-01-31 00:00:00", "2024-02-29", "31/01/2024", None, "2023-02-30"],
                "b": ["true", "FALSE", "sim", None, ""],
                "t": ["a", None, "1", "b", "c"],
            },
            "expected": {
                "q": [12, 3, None, None, None],
                "v": [1234.5, -0.25, 1000.0, None, None],
                "d": [_DATA(2024, 1, 31), _DATA(2024, 2, 29), None, None, None],
                "b": [True, False, None, None, None],
                "t": ["a", None, "1", "b", "c"],
            },
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.with_columns(cast_expr(c, t).alias(c) for c, t in self.types.items())

    def to_python(self) -> str:
        return f"lf = lf.with_columns(cast_expr(c, t).alias(c) for c, t in {self.types!r}.items())"

    def to_m(self, prev: str, name: str) -> str:
        transforms = ", ".join(
            f"{{{m_text(c)}, each {_M_CAST[t][0]}, {_M_CAST[t][1]}}}" for c, t in self.types.items()
        )
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"


@register_op
class SplitCol(Op):
    """Divide uma coluna por um delimitador literal (não é regex) em
    ``into`` colunas, no lugar da original. A última parte fica com o resto
    do texto; parte que falta fica nula."""

    op: Literal["split_col"]
    col: str = Field(min_length=1)
    delimiter: str = Field(min_length=1)
    into: list[str] = Field(min_length=2)

    python_helpers = (split_col_lf,)
    examples = (
        {
            "step": {"col": "mun_uf", "delimiter": " - ", "into": ["municipio", "uf"]},
            "input": {"id": ["1", "2", "3", "4"], "mun_uf": ["Vitória - ES", "Serra", None, "A - B - C"]},
            "expected": {
                "id": ["1", "2", "3", "4"],
                "municipio": ["Vitória", "Serra", None, "A"],
                "uf": ["ES", None, None, "B - C"],
            },
        },
    )

    @field_validator("into")
    @classmethod
    def _nomes(cls, into: list[str]) -> list[str]:
        if len(set(into)) != len(into) or any(not n.strip() for n in into):
            raise ValueError("into precisa de nomes distintos e não vazios")
        return into

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return split_col_lf(lf, self.col, self.delimiter, self.into)

    def to_python(self) -> str:
        return f"lf = split_col_lf(lf, {self.col!r}, {self.delimiter!r}, {self.into!r})"

    def to_m(self, prev: str, name: str) -> str:
        delimitadores = m_list([self.delimiter] * (len(self.into) - 1))
        splitter = f"Splitter.SplitTextByEachDelimiter({delimitadores})"
        return f"{name} = Table.SplitColumn({prev}, {m_text(self.col)}, {splitter}, {m_list(self.into)})"


@register_op
class MergeCols(Op):
    """Junta colunas em uma só (``into``), na posição da primeira delas,
    com ``separator`` entre os valores. Célula nula é pulada. Com ``keep``,
    as colunas originais ficam."""

    op: Literal["merge_cols"]
    cols: list[str] = Field(min_length=2)
    separator: str = ""
    into: str = Field(min_length=1)
    keep: bool = False

    python_helpers = (merge_cols_lf,)
    examples = (
        {
            "step": {"cols": ["mes", "ano"], "separator": "/", "into": "competencia"},
            "input": {"id": ["1", "2", "3"], "mes": ["JAN", None, "MAR"], "ano": ["2024", "2024", None]},
            "expected": {"id": ["1", "2", "3"], "competencia": ["JAN/2024", "2024", "MAR"]},
        },
        {
            "step": {"cols": ["a", "b"], "separator": "-", "into": "ab", "keep": True},
            "input": {"a": ["1"], "b": ["2"]},
            "expected": {"ab": ["1-2"], "a": ["1"], "b": ["2"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return merge_cols_lf(lf, self.cols, self.separator, self.into, self.keep)

    def to_python(self) -> str:
        return f"lf = merge_cols_lf(lf, {self.cols!r}, {self.separator!r}, {self.into!r}, {self.keep!r})"

    def to_m(self, prev: str, name: str) -> str:
        campos = ", ".join(m_field(c) for c in self.cols)
        valores = f'List.Transform({{{campos}}}, (v) => if v = null then null else Text.From(v, "en-US"))'
        texto = f"each Text.Combine({valores}, {m_text(self.separator)})"
        juntas = f"Table.AddColumn({prev}, {m_text(self.into)}, {texto}, type text)"
        cols = m_list(self.cols)
        nomes = f"Table.ColumnNames({prev})"
        posicao = f"List.Min(List.Transform({cols}, each List.PositionOf({nomes}, _)))"
        resto = nomes if self.keep else f"List.RemoveItems({nomes}, {cols})"
        ordem = f"List.InsertRange({resto}, {posicao}, {{{m_text(self.into)}}})"
        return f"{name} = Table.SelectColumns({juntas}, {ordem})"

"""Funções de tabela (``DataFrame`` Polars) herdadas de ``Functions/cleaning.py``.

Aplicam as funções de valor de ``wolfz.br`` em colunas inteiras e cuidam de
estrutura (cabeçalho, totais, linhas vazias). Ainda não são operações de
receita: cada uma vira uma operação registrada, com M e Python, em F0.F e
F1.E.
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from wolfz.br.booleanos import parse_bool_br
from wolfz.br.datas import parse_date_br, parse_month_year
from wolfz.br.numeros import parse_brl, parse_number_br, parse_percent_br
from wolfz.core.naming import dedupe_names, to_snake_case
from wolfz.core.text import is_null_token, normalize_spaces

_DTYPES: dict[Callable, pl.DataType] = {
    parse_number_br: pl.Float64, parse_brl: pl.Float64, parse_percent_br: pl.Float64,
    parse_date_br: pl.Date, parse_month_year: pl.Date, parse_bool_br: pl.Boolean,
}


def apply_parser(
    df: pl.DataFrame,
    columns: str | list[str],
    parser: Callable[[object], object],
    dtype: pl.DataType | None = None,
    suffix: str | None = None,
) -> pl.DataFrame:
    """Aplica uma função de valor a colunas inteiras.

    O parser roda uma vez por valor DISTINTO e o resultado é mapeado de
    volta, o que é ordens de grandeza mais rápido que linha a linha em
    colunas repetitivas (datas, categorias, UFs). Com ``suffix`` a coluna
    original é mantida e a convertida ganha um nome novo
    ('valor' -> 'valor_num'), para auditar o antes/depois.

    Ex.: apply_parser(df, ["valor_venda"], parse_brl)
         apply_parser(df, "data", lambda v: parse_date_br(v, eight_digits="dmy"), pl.Date)"""
    columns = [columns] if isinstance(columns, str) else columns
    dtype = dtype or _DTYPES.get(parser, pl.String)
    exprs = []
    for col in columns:
        uniques = df.get_column(col).drop_nulls().unique().to_list()
        mapping = {u: parser(u) for u in uniques}
        exprs.append(
            pl.col(col)
            .replace_strict(list(mapping), list(mapping.values()), default=None, return_dtype=dtype)
            .alias(f"{col}{suffix}" if suffix else col)
        )
    return df.with_columns(exprs)


def clean_column_names(df: pl.DataFrame) -> pl.DataFrame:
    """Nomes de coluna em snake_case, sem acento, sem BOM, sem repetição.

    'Valor de Venda' -> 'valor_de_venda'; '\\ufeffRegiao - Sigla' ->
    'regiao_sigla'; duas colunas 'Valor' -> 'valor', 'valor_2'."""
    names = dedupe_names([to_snake_case(c) for c in df.columns])
    return df.rename(dict(zip(df.columns, names)))


def normalize_text_columns(
    df: pl.DataFrame,
    columns: list[str] | None = None,
    extra_nulls: frozenset[str] | set[str] = frozenset(),
) -> pl.DataFrame:
    """``clean_text`` vetorizado em todas as colunas de texto.

    Espaços, caracteres invisíveis e acentos decompostos são tratados
    no Polars; marcadores de nulo são identificados entre os valores
    distintos de cada coluna e trocados por null."""
    columns = columns or [c for c, t in df.schema.items() if t == pl.String]
    df = df.with_columns(
        pl.col(c)
        .str.normalize("NFC")
        .str.replace_all("[​‌‍⁠﻿­]", "")
        .str.replace_all(r"[\s    　]+", " ")
        .str.strip_chars()
        for c in columns
    )
    exprs = []
    for c in columns:
        tokens = [v for v in df.get_column(c).drop_nulls().unique().to_list() if is_null_token(v, extra_nulls)]
        if tokens:
            exprs.append(pl.when(pl.col(c).is_in(tokens)).then(None).otherwise(pl.col(c)).alias(c))
    return df.with_columns(exprs) if exprs else df


def _is_blank(col: str) -> pl.Expr:
    return pl.col(col).is_null() | (pl.col(col).cast(pl.String).str.strip_chars() == "")


def drop_empty_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Remove linhas em que todas as células estão vazias."""
    return df.filter(~pl.all_horizontal(_is_blank(c) for c in df.columns))


def drop_empty_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Remove colunas 100% vazias (colunas de espaçamento de relatório,
    'Valor de Compra' que nunca é preenchido)."""
    keep = [c for c in df.columns if not df.select(_is_blank(c).all()).item()]
    return df.select(keep)


def drop_repeated_headers(df: pl.DataFrame, min_match: float = 0.8) -> pl.DataFrame:
    """Remove linhas que repetem o cabeçalho no meio dos dados.

    Aparece quando vários relatórios paginados ou vários arquivos mensais
    são colados um embaixo do outro. Use antes de ``clean_column_names``:
    a comparação é com o nome original da coluna."""
    hits = pl.sum_horizontal(
        (pl.col(c).cast(pl.String).str.strip_chars().str.to_lowercase() == c.strip().lower()).fill_null(False)
        for c in df.columns
    )
    return df.filter(hits < max(1, round(min_match * len(df.columns))))


_TOTAL_LABEL = r"(?i)^\s*((sub\s*-?\s*)?total|soma|consolidado)\b"


def drop_total_rows(
    df: pl.DataFrame,
    label_columns: list[str] | None = None,
    pattern: str = _TOTAL_LABEL,
    return_removed: bool = False,
) -> pl.DataFrame | tuple[pl.DataFrame, pl.DataFrame]:
    """Remove linhas de total/subtotal ('Total', 'TOTAL GERAL', 'Subtotal
    Região Sul', 'Soma').

    Procura o rótulo nas duas primeiras colunas de texto (ou em
    ``label_columns``): com células mescladas, o 'Total' costuma cair na
    segunda coluna. 'Totalmente' não casa, mas uma empresa chamada 'Total
    Distribuidora' casaria — por isso ``return_removed=True`` devolve também
    as linhas descartadas, para conferência."""
    if label_columns is None:
        label_columns = [c for c, t in df.schema.items() if t == pl.String][:2]
    is_total = pl.any_horizontal(pl.col(c).str.contains(pattern).fill_null(False) for c in label_columns)
    kept = df.filter(~is_total)
    return (kept, df.filter(is_total)) if return_removed else kept


def fill_down(df: pl.DataFrame, columns: str | list[str]) -> pl.DataFrame:
    """Preenche para baixo células vazias de colunas de categoria.

    Desfaz célula mesclada na vertical ('Região' mesclada sobre 5 linhas) e
    relatório agrupado que só escreve o grupo na primeira linha."""
    columns = [columns] if isinstance(columns, str) else columns
    return df.with_columns(
        pl.when(_is_blank(c)).then(None).otherwise(pl.col(c)).forward_fill().alias(c) for c in columns
    )


def promote_header(df: pl.DataFrame, n_rows: int = 1, sep: str = "_") -> pl.DataFrame:
    """Usa as ``n_rows`` primeiras linhas como cabeçalho.

    Para tabela lida com ``has_header=False`` ou que tem título acima do
    cabeçalho real (corte as linhas de título antes com ``df.slice``). Com
    2+ linhas, as superiores são preenchidas para a direita (célula mesclada
    na horizontal) e as partes são unidas:
        | 2024 |      | 2025 |      |        ->  2024_Jan | 2024_Fev | ...
        | Jan  | Fev  | Jan  | Fev  |"""
    header = [list(r) for r in df.head(n_rows).iter_rows()]
    for row in header[:-1]:
        last = None
        for j, v in enumerate(row):
            if v is None or str(v).strip() == "":
                row[j] = last
            else:
                last = v
    names = []
    for j in range(df.width):
        parts: list[str] = []
        for row in header:
            v = row[j]
            if v is not None and (p := normalize_spaces(str(v))) and (not parts or parts[-1] != p):
                parts.append(p)
        names.append(sep.join(parts) or f"coluna_{j + 1}")
    names = dedupe_names(names)
    return df.slice(n_rows).rename(dict(zip(df.columns, names)))

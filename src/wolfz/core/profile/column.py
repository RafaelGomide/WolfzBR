"""Perfil de coluna (F1.D): o que a interface e o ``wolfz inspect`` mostram.

Para cada coluna: tipo brasileiro inferido, nulos, marcadores de nulo
('-', 'N/D', '#N/D'…), distintos, formas mais comuns (``value_shape``),
exemplos e, quando o tipo é número, moeda, percentual ou data, mínimo e
máximo já convertidos.

Tabelas grandes são perfiladas numa amostra (10 mil linhas por padrão). A
amostra é aleatória mas determinística (semente fixa) e mantém a ordem
original das linhas, para que os exemplos sejam os mesmos a cada execução.
``TableProfile.is_sample`` diz se o perfil é de amostra.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import polars as pl

from wolfz.br.datas import parse_date_br, parse_month_year
from wolfz.br.numeros import parse_brl, parse_number_br, parse_percent_br
from wolfz.core.profile.infer import infer_br_type
from wolfz.core.profile.quick import value_shape
from wolfz.core.text import clean_text, is_null_token

SAMPLE_SIZE = 10_000
SEED = 0
TOP_SHAPES = 3
EXAMPLES = 3

# Tipo inferido -> conversor usado para mínimo e máximo.
_ORDENAVEIS: dict[str, Callable[[str], float | date | None]] = {
    "numero": parse_number_br,
    "moeda": parse_brl,
    "percentual": parse_percent_br,
    "data": lambda v: parse_date_br(v, accept_excel_serial=False),
    "mes_ano": parse_month_year,
}


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    inferred_type: str
    type_rate: float  # fração dos valores preenchidos que casam com o tipo
    rows: int  # linhas analisadas
    nulls: int  # células vazias
    null_markers: int  # preenchidas, mas com marcador de nulo ('-', 'N/D'…)
    distinct: int
    top_shapes: list[tuple[str, int]]
    examples: list[str]
    minimum: float | date | None = None
    maximum: float | date | None = None

    @property
    def null_pct(self) -> float:
        return self.nulls / self.rows if self.rows else 0.0

    @property
    def null_marker_pct(self) -> float:
        return self.null_markers / self.rows if self.rows else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["top_shapes"] = [{"shape": s, "count": c} for s, c in self.top_shapes]
        for key in ("minimum", "maximum"):
            if isinstance(data[key], date):
                data[key] = data[key].isoformat()
        return data | {"null_pct": self.null_pct, "null_marker_pct": self.null_marker_pct}


@dataclass(frozen=True)
class TableProfile:
    columns: list[ColumnProfile]
    total_rows: int
    sampled_rows: int

    @property
    def is_sample(self) -> bool:
        return self.sampled_rows < self.total_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "sampled_rows": self.sampled_rows,
            "is_sample": self.is_sample,
            "columns": [c.to_dict() for c in self.columns],
        }


def profile_column(series: pl.Series) -> ColumnProfile:
    """Perfil de uma coluna (os valores são tratados como texto)."""
    values = series.cast(pl.String).to_list()
    filled = [v for v in values if v is not None]
    markers = [v for v in filled if is_null_token(v)]
    shapes = Counter(value_shape(v) for v in filled)
    examples = [str(v) for v in dict.fromkeys(v for v in filled if not is_null_token(v))][:EXAMPLES]
    inferred, rate = infer_br_type(values, sample=len(values) or 1)

    minimum = maximum = None
    if series.dtype.is_numeric() or series.dtype == pl.Date:
        # Já convertida: o mínimo e o máximo são os da coluna. Relida como
        # texto, '0.087' seria 87 (ponto de milhar).
        preenchida = series.drop_nulls()
        if series.dtype.is_numeric():
            preenchida = preenchida.cast(pl.Float64).filter(preenchida.cast(pl.Float64).is_finite())
        if preenchida.len():
            minimum, maximum = preenchida.min(), preenchida.max()
    elif convert := _ORDENAVEIS.get(inferred):
        converted = [c for v in filled if (s := clean_text(v)) is not None and (c := convert(s)) is not None]
        if converted:
            minimum, maximum = min(converted), max(converted)

    return ColumnProfile(
        name=series.name,
        inferred_type=inferred,
        type_rate=rate,
        rows=len(values),
        nulls=len(values) - len(filled),
        null_markers=len(markers),
        distinct=series.n_unique(),
        top_shapes=shapes.most_common(TOP_SHAPES),
        examples=examples,
        minimum=minimum,
        maximum=maximum,
    )


def sample_rows(df: pl.DataFrame, size: int = SAMPLE_SIZE, seed: int = SEED) -> pl.DataFrame:
    """Amostra aleatória determinística, na ordem original das linhas."""
    if df.height <= size:
        return df
    picked = df.with_row_index("__linha__").sample(size, seed=seed).sort("__linha__")
    return picked.drop("__linha__")


def profile_table(data: pl.DataFrame | pl.LazyFrame, sample_size: int = SAMPLE_SIZE) -> TableProfile:
    """Perfil de todas as colunas, numa amostra de até ``sample_size`` linhas."""
    df = data.collect() if isinstance(data, pl.LazyFrame) else data
    sample = sample_rows(df, sample_size)
    return TableProfile([profile_column(sample[c]) for c in sample.columns], df.height, sample.height)

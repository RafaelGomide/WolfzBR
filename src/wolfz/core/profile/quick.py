"""Inspeção rápida de colunas durante o desenvolvimento."""

from __future__ import annotations

import re
from collections import Counter

import polars as pl

from wolfz.core.text import is_null_token


def value_shape(value: str | None, max_len: int = 30) -> str:
    """Forma de um valor: dígito vira '9', letra vira 'a', resto fica.

    '123.456.789-09' -> '999.999.999-99'; 'R$ 1.234,56' -> 'a$ 9.999,99'.
    Agrupar uma coluna por forma revela em segundos os formatos misturados
    (CPF com e sem máscara, datas em dois padrões, zeros perdidos)."""
    if value is None:
        return "<null>"
    s = re.sub(r"\d", "9", str(value))
    s = re.sub(r"[^\W\d_]", "a", s)
    return s[:max_len]


def quick_profile(df: pl.DataFrame, top: int = 3) -> pl.DataFrame:
    """Perfil rápido de todas as colunas: nulos, vazios, distintos, formas
    mais comuns e exemplos. Pensado para uso interativo em notebook."""
    rows = []
    for name in df.columns:
        s = df[name].cast(pl.String)
        values = s.to_list()
        non_null = [v for v in values if v is not None]
        shapes = Counter(value_shape(v) for v in non_null)
        rows.append({
            "coluna": name,
            "nulos": s.null_count(),
            "vazios_ou_marcadores": sum(is_null_token(v) for v in non_null),
            "distintos": s.n_unique(),
            "formas": " | ".join(f"{k} ({c})" for k, c in shapes.most_common(top)),
            "exemplos": " | ".join(str(v)[:30] for v in list(dict.fromkeys(non_null))[:top]),
        })
    return pl.DataFrame(rows)

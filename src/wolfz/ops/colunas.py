"""Operações de coluna."""

from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import Field, field_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_text


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

"""Operações de teste registradas no catálogo.

Os nomes começam com ``teste_`` para não colidir com as operações reais
que entram em F0.F.
"""

from typing import Literal

import polars as pl
import pytest
from pydantic import Field

from wolfz.core.recipe import Op, register_op


@register_op
class RenomearDeTeste(Op):
    op: Literal["teste_renomear"]
    mapping: dict[str, str] = Field(min_length=1)

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.rename(self.mapping)

    def to_m(self, prev: str, name: str) -> str:
        pairs = ", ".join(f'{{"{a}", "{b}"}}' for a, b in self.mapping.items())
        return f"{name} = Table.RenameColumns({prev}, {{{pairs}}})"

    def to_python(self) -> str:
        return f"lf = lf.rename({self.mapping!r})"


@register_op
class RemoverDeTeste(Op):
    op: Literal["teste_remover"]
    cols: list[str] = Field(min_length=1)
    strict: bool = True

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.drop(self.cols, strict=self.strict)

    def to_m(self, prev: str, name: str) -> str:
        return f"{name} = Table.RemoveColumns({prev}, {self.cols!r})"

    def to_python(self) -> str:
        return f"lf = lf.drop({self.cols!r})"


@pytest.fixture
def recipe_dict():
    return {
        "wolfz_version": "0.1",
        "name": "Vendas mensais",
        "created_at": "2026-10-16T14:00:00Z",
        "source": {"type": "excel", "sheet": "Vendas", "match": {"sheet_name_regex": r"Vendas \d{4}"}},
        "steps": [
            {"id": "s1", "op": "teste_renomear", "mapping": {"Vlr": "valor"}},
            {"id": "s2", "op": "teste_remover", "cols": ["obs"]},
        ],
    }

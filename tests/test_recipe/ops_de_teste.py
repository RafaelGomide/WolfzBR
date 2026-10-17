"""Operações de teste registradas no catálogo.

Ficam num módulo de nome único, e não no ``conftest.py``: cada pasta de
testes tem o seu ``conftest``, e ``from conftest import`` pega o que o pytest
carregou primeiro (no Linux, o de ``tests/test_api``).

Os nomes começam com ``teste_`` para não colidir com as operações reais
que entram em F0.F.
"""

from typing import Literal

import polars as pl
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

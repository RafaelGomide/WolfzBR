"""Matriz de células: o que a detecção enxerga de uma aba.

Cada célula tem valor (sempre texto), tipo, se está mesclada e se está em
negrito. A posição é a da planilha original: linha 0 é a linha 1 do Excel,
coluna 0 é a coluna A. A matriz é montada a partir do ``raw.parquet`` (os
valores) e do ``structure.json`` (a formatação), só para as linhas que a
detecção pede.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import polars as pl
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter

if TYPE_CHECKING:
    from wolfz.core.ingest.structure import SheetStructure


class CellType(StrEnum):
    EMPTY = "empty"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    BOOL = "bool"
    ERROR = "error"


_NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d+)?)?")
# Em inglês (como o arquivo guarda) e em português (como o Excel em pt-BR
# exibe e exporta para CSV).
_ERRORS = frozenset(
    {"#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!"}
    | {"#N/D", "#VALOR!", "#NOME?", "#NÚM!", "#NULO!", "#DESPEJAR!", "#CALC!"}
)


def infer_type(value: str | None) -> CellType:
    """Tipo de uma célula a partir do texto que a leitura produziu.

    Vale para o formato que ``fastexcel``/``calamine`` geram (ponto decimal,
    data ISO); ``1.234,56`` de um CSV é texto aqui — reconhecer número
    brasileiro é trabalho da detecção, com ``wolfz.br``."""
    if value is None or not value.strip():
        return CellType.EMPTY
    if _NUMBER.fullmatch(value):
        return CellType.NUMBER
    if _DATE.fullmatch(value):
        return CellType.DATE
    if value in ("true", "false"):
        return CellType.BOOL
    if value in _ERRORS:
        return CellType.ERROR
    return CellType.TEXT


def column_letter(col: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    return get_column_letter(col + 1)


def column_index(letter: str) -> int:
    """A -> 0, AA -> 26."""
    return column_index_from_string(letter) - 1


def to_a1(row: int, col: int) -> str:
    return f"{column_letter(col)}{row + 1}"


def from_a1(ref: str) -> tuple[int, int]:
    letter, row = coordinate_from_string(ref)
    return row - 1, column_index(letter)


@dataclass(frozen=True, slots=True)
class Cell:
    value: str | None
    type: CellType
    merged: bool = False
    bold: bool = False


class CellMatrix:
    """Janela de linhas de uma aba, com posições absolutas.

    ``row_numbers`` são as linhas (0-based) presentes, em ordem; podem ter
    buraco (as primeiras N e as últimas M linhas, por exemplo).
    ``col_offset`` é a coluna da primeira coluna da matriz."""

    def __init__(self, rows: list[list[Cell]], row_numbers: list[int], col_offset: int = 0):
        if len(rows) != len(row_numbers):
            raise ValueError("rows e row_numbers precisam ter o mesmo tamanho")
        self._rows = rows
        self._index = {r: i for i, r in enumerate(row_numbers)}
        self.row_numbers = row_numbers
        self.col_offset = col_offset
        self.width = max((len(r) for r in rows), default=0)

    @property
    def height(self) -> int:
        return len(self._rows)

    def row(self, row: int) -> list[Cell]:
        return self._rows[self._index[row]]

    def cell(self, row: int, col: int) -> Cell:
        cells = self.row(row)
        j = col - self.col_offset
        if 0 <= j < len(cells):
            return cells[j]
        return Cell(None, CellType.EMPTY)

    def __iter__(self) -> Iterator[tuple[int, list[Cell]]]:
        return iter(zip(self.row_numbers, self._rows, strict=True))

    @classmethod
    def from_frame(
        cls,
        df: pl.DataFrame,
        structure: SheetStructure | None = None,
        rows: Iterable[int] | None = None,
    ) -> CellMatrix:
        """Monta a matriz a partir do ``raw`` (colunas com nome de letra, linha
        i = linha i da planilha) e, se houver, da estrutura.

        ``rows`` limita às linhas pedidas; por padrão, as linhas amostradas
        pela estrutura, ou a tabela inteira se não houver estrutura."""
        if rows is None:
            rows = structure.sampled_row_numbers(df.height) if structure else range(df.height)
        wanted = [r for r in rows if 0 <= r < df.height]
        offset = column_index(df.columns[0]) if df.width else 0
        merged = structure.merged_cells(wanted) if structure else set()
        bold = structure.bold_cells() if structure else set()
        types = structure.cell_types() if structure else {}
        picked = df[wanted].rows() if wanted else []
        matrix: list[list[Cell]] = []
        for r, values in zip(wanted, picked, strict=True):
            line = []
            for j, value in enumerate(values):
                pos = (r, offset + j)
                kind = infer_type(value)
                if kind is not CellType.EMPTY:
                    kind = types.get(pos, kind)
                line.append(Cell(value, kind, pos in merged, pos in bold))
            matrix.append(line)
        return cls(matrix, wanted, offset)

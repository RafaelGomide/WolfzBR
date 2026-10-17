"""Catálogo de operações: schema + Polars + M + Python para cada passo de receita.

Importar este pacote registra todas as operações (``@register_op``).
"""

from wolfz.ops.br import (
    CleanCep,
    CleanCnpj,
    CleanCpf,
    NormalizeUf,
    ParseBoolBr,
    ParseBrl,
    ParseDateBr,
    ParseDecimalBr,
    ParseMonthYear,
    ParsePercent,
)
from wolfz.ops.colunas import Cast, DropCols, MergeCols, Rename, Reorder, SplitCol
from wolfz.ops.estrutura import DropEmptyCols, DropEmptyRows, FillDown, HeaderRows, SelectRange, Unpivot
from wolfz.ops.linhas import Dedupe, DropRowsWhere, FillNull, Filter, Sort
from wolfz.ops.texto import Case, RemoveAccents, Replace, Trim

__all__ = [
    "Case",
    "Cast",
    "CleanCep",
    "CleanCnpj",
    "CleanCpf",
    "Dedupe",
    "DropCols",
    "DropEmptyCols",
    "DropEmptyRows",
    "DropRowsWhere",
    "FillDown",
    "FillNull",
    "Filter",
    "HeaderRows",
    "MergeCols",
    "NormalizeUf",
    "ParseBoolBr",
    "ParseBrl",
    "ParseDateBr",
    "ParseDecimalBr",
    "ParseMonthYear",
    "ParsePercent",
    "RemoveAccents",
    "Rename",
    "Reorder",
    "Replace",
    "SelectRange",
    "Sort",
    "SplitCol",
    "Trim",
    "Unpivot",
]

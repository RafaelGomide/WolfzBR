"""Catálogo de operações: schema + Polars + M + Python para cada passo de receita.

Importar este pacote registra todas as operações (``@register_op``).
"""

from wolfz.ops.br import (
    CleanCep,
    CleanCnpj,
    CleanCpf,
    CleanCpfCnpj,
    CleanPhone,
    FixMojibake,
    NormalizeUf,
    ParseBoolBr,
    ParseBrl,
    ParseDateBr,
    ParseDecimalBr,
    ParseIbgeValue,
    ParseMonthYear,
    ParsePercent,
    ScaleByUnit,
    SplitMunicipioUf,
    StripFootnotes,
)
from wolfz.ops.colunas import Cast, DropCols, MergeCols, Rename, Reorder, SplitCol
from wolfz.ops.estrutura import DropEmptyCols, DropEmptyRows, FillDown, HeaderRows, SelectRange, Unpivot
from wolfz.ops.linhas import Dedupe, DropRowsWhere, FillNull, Filter, Sort
from wolfz.ops.municipio import NormalizeMunicipio
from wolfz.ops.texto import Case, RemoveAccents, Replace, Trim

__all__ = [
    "Case",
    "Cast",
    "CleanCep",
    "CleanCnpj",
    "CleanCpf",
    "CleanCpfCnpj",
    "CleanPhone",
    "Dedupe",
    "DropCols",
    "DropEmptyCols",
    "DropEmptyRows",
    "DropRowsWhere",
    "FillDown",
    "FillNull",
    "Filter",
    "FixMojibake",
    "HeaderRows",
    "MergeCols",
    "NormalizeMunicipio",
    "NormalizeUf",
    "ParseBoolBr",
    "ParseBrl",
    "ParseDateBr",
    "ParseDecimalBr",
    "ParseIbgeValue",
    "ParseMonthYear",
    "ParsePercent",
    "RemoveAccents",
    "Rename",
    "Reorder",
    "Replace",
    "ScaleByUnit",
    "SelectRange",
    "Sort",
    "SplitCol",
    "SplitMunicipioUf",
    "StripFootnotes",
    "Trim",
    "Unpivot",
]

"""Carregamento de um arquivo para inspeção (``wolfz inspect``, F1.D3).

CSV vem com o cabeçalho da primeira linha. Planilha vem como grade
(``wolfz.core.ingest``) e precisa de uma linha de cabeçalho: até a detecção
existir (F1.C), é a primeira linha não vazia, ou a que o usuário indicar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from wolfz.core.ingest import SheetInfo, list_sheets, open_file, read_sheet
from wolfz.core.ingest.csv import read_csv_raw
from wolfz.core.ingest.formats import Format
from wolfz.core.naming import dedupe_names


@dataclass
class LoadedTable:
    path: Path
    format: Format
    frame: pl.DataFrame
    header_row: int  # 1-based, como o usuário vê na planilha
    sheet: str | None = None
    sheets: list[SheetInfo] = field(default_factory=list)


def apply_header(grid: pl.DataFrame, header_row: int | None = None) -> tuple[pl.DataFrame, int]:
    """Usa uma linha da grade como cabeçalho e devolve o corpo da tabela.

    ``header_row`` é 1-based; sem ele, vale a primeira linha não vazia.
    Célula de cabeçalho vazia fica com a letra da coluna; nome repetido ganha
    sufixo (``dedupe_names``). Linhas inteiramente vazias do corpo saem."""
    if grid.height == 0:
        raise ValueError("a aba está vazia")
    if header_row is None:
        filled = grid.select(pl.any_horizontal(pl.all().is_not_null())).to_series()
        idx = filled.arg_true()[0] if filled.any() else 0
    else:
        idx = header_row - 1
        if not 0 <= idx < grid.height:
            raise ValueError(f"a linha de cabeçalho {header_row} não existe (a aba tem {grid.height} linhas)")
    labels = [
        str(v).strip() if v is not None and str(v).strip() else letter
        for v, letter in zip(grid.row(idx), grid.columns, strict=True)
    ]
    body = grid.slice(idx + 1)
    body = body.filter(pl.any_horizontal(pl.all().is_not_null())) if body.width else body
    return body.rename(dict(zip(grid.columns, dedupe_names(labels), strict=True))), idx + 1


def load_table(path: str | Path, sheet: str | None = None, header_row: int | None = None) -> LoadedTable:
    """Lê um arquivo para inspeção. Erros de leitura são ``IngestError``;
    linha de cabeçalho inválida é ``ValueError``."""
    path, fmt, _ = open_file(path)
    if fmt == "csv":
        if sheet is not None:
            raise ValueError("CSV não tem abas")
        if header_row not in (None, 1):
            raise ValueError("em CSV o cabeçalho é sempre a linha 1")
        return LoadedTable(path, fmt, read_csv_raw(path), 1)
    sheets = list_sheets(path, fmt)
    data = read_sheet(path, sheet, fmt, sheets=sheets)
    frame, row = apply_header(data.frame, header_row)
    return LoadedTable(path, fmt, frame, row, data.sheet, sheets)

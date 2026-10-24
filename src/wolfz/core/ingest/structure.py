"""Metadados estruturais de uma aba: mesclagens, negrito, fórmulas e tipos.

São os sinais que os valores sozinhos não dão: título mesclado sobre a
tabela, cabeçalho e linha de total em negrito. Ler a formatação é a parte
mais cara da importação (``openpyxl`` cria um objeto Python por célula,
§3.5 do design), então só são lidas as primeiras ``head_rows`` linhas e as
últimas ``tail_rows`` — onde ficam título, cabeçalho, totais e rodapé.

- ``.xlsx``: ``openpyxl`` em modo ``read_only`` (memória constante) para
  negrito, fórmulas e tipos; as mesclagens vêm do XML da aba, lido em
  streaming, porque o modo ``read_only`` não as expõe.
- ``.xls`` e ``.ods``: tipos via ``python-calamine``, mais as mesclagens no
  ``.xls`` (o ``calamine`` não as lê no ``.ods``). Não há negrito nem
  fórmula; ``formatting`` fica ``False`` e a detecção segue só com os sinais
  de valor (§10.5).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import IO, Any
from xml.etree.ElementTree import iterparse

import openpyxl
from openpyxl.utils.cell import range_boundaries

from wolfz.core.ingest.cells import CellType, from_a1, to_a1

HEAD_ROWS = 50
TAIL_ROWS = 20

_OPENPYXL_TYPES = {"n": CellType.NUMBER, "s": CellType.TEXT, "d": CellType.DATE, "b": CellType.BOOL}
_OPENPYXL_TYPES |= {"e": CellType.ERROR, "inlineStr": CellType.TEXT, "str": CellType.TEXT}


@dataclass(frozen=True)
class MergedRange:
    """Intervalo mesclado, 0-based e inclusivo."""

    first_row: int
    first_col: int
    last_row: int
    last_col: int

    @classmethod
    def from_a1(cls, ref: str) -> MergedRange:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        return cls(min_row - 1, min_col - 1, max_row - 1, max_col - 1)

    def to_a1(self) -> str:
        return f"{to_a1(self.first_row, self.first_col)}:{to_a1(self.last_row, self.last_col)}"


@dataclass
class SheetStructure:
    """Conteúdo do ``structure.json``. Células em notação A1 no JSON, para
    ser legível; em posições 0-based na memória."""

    sheet: str | None
    formatting: bool = False  # negrito e fórmulas foram lidos?
    merged: list[MergedRange] = field(default_factory=list)
    bold: list[tuple[int, int]] = field(default_factory=list)
    formulas: dict[tuple[int, int], str] = field(default_factory=dict)
    types: dict[tuple[int, int], CellType] = field(default_factory=dict)
    sampled_rows: list[tuple[int, int]] = field(default_factory=list)  # intervalos 0-based, inclusivos
    warnings: list[str] = field(default_factory=list)

    def sampled_row_numbers(self, height: int) -> list[int]:
        return sorted({r for a, b in self.sampled_rows for r in range(a, min(b, height - 1) + 1)})

    def merged_cells(self, rows: Iterable[int]) -> set[tuple[int, int]]:
        wanted = set(rows)
        cells: set[tuple[int, int]] = set()
        for m in self.merged:
            for r in range(m.first_row, m.last_row + 1):
                if r in wanted:
                    cells.update((r, c) for c in range(m.first_col, m.last_col + 1))
        return cells

    def bold_cells(self) -> set[tuple[int, int]]:
        return set(self.bold)

    def cell_types(self) -> dict[tuple[int, int], CellType]:
        return self.types

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "formatting": self.formatting,
            "sampled_rows": [[a + 1, b + 1] for a, b in self.sampled_rows],
            "merged": [m.to_a1() for m in self.merged],
            "bold": [to_a1(*p) for p in self.bold],
            "formulas": {to_a1(*p): f for p, f in self.formulas.items()},
            "types": {to_a1(*p): str(t) for p, t in self.types.items()},
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SheetStructure:
        return cls(
            sheet=data.get("sheet"),
            formatting=data.get("formatting", False),
            sampled_rows=[(a - 1, b - 1) for a, b in data.get("sampled_rows", [])],
            merged=[MergedRange.from_a1(m) for m in data.get("merged", [])],
            bold=[from_a1(c) for c in data.get("bold", [])],
            formulas={from_a1(c): f for c, f in data.get("formulas", {}).items()},
            types={from_a1(c): CellType(t) for c, t in data.get("types", {}).items()},
            warnings=list(data.get("warnings", [])),
        )


def sample_windows(
    total_rows: int, head_rows: int = HEAD_ROWS, tail_rows: int = TAIL_ROWS
) -> list[tuple[int, int]]:
    """Intervalos 0-based (inclusivos) das primeiras e das últimas linhas."""
    if total_rows <= 0:
        return []
    head_end = min(head_rows, total_rows) - 1
    tail_start = max(head_end + 1, total_rows - tail_rows)
    windows = [(0, head_end)] if head_end >= 0 else []
    if tail_start <= total_rows - 1:
        windows.append((tail_start, total_rows - 1))
    return windows


def _xlsx_merges(xml: IO[bytes]) -> list[MergedRange]:
    """Lê só os ``<mergeCell>`` do XML da aba, em streaming."""
    merges: list[MergedRange] = []
    for _, elem in iterparse(xml, events=("end",)):
        if elem.tag.endswith("}mergeCell") and (ref := elem.get("ref")):
            merges.append(MergedRange.from_a1(ref))
        elem.clear()
    return merges


_BLOCO_XML = 4 << 20
_R_DA_LINHA = re.compile(rb'\sr="(\d+)"')


def _xml_das_janelas(xml: IO[bytes], windows: list[tuple[int, int]]) -> bytes | None:
    """O XML da aba só com as linhas das janelas e o que vem depois de
    ``<sheetData>`` (mesclagens). O ``openpyxl`` percorre a aba desde o
    começo para chegar às últimas linhas e cria um objeto por célula; com
    o XML recortado, uma aba de 1 milhão de linhas custa o mesmo que uma de
    100. ``None`` quando o XML foge do que o Excel grava (linha sem ``r``,
    prefixo de namespace): aí a leitura é a de sempre."""
    manter = [(a + 1, b + 1) for a, b in windows]
    buf = b""
    while (i := buf.find(b"<sheetData")) < 0 or (gt := buf.find(b">", i)) < 0:
        if not (bloco := xml.read(_BLOCO_XML)):
            return None
        buf += bloco
    if buf[gt - 1 : gt] == b"/":  # <sheetData/>: aba vazia
        return None
    partes = [buf[: gt + 1]]
    buf, pos, eof = buf[gt + 1 :], 0, False
    while True:
        i = buf.find(b"<", pos)
        if i >= 0 and buf.startswith(b"</sheetData>", i):
            partes.append(buf[i:])
            partes.extend(iter(lambda: xml.read(_BLOCO_XML), b""))
            return b"".join(partes)
        final = -1
        if i >= 0 and (gt := buf.find(b">", i)) >= 0:
            if not buf.startswith(b"<row", i) or buf[i + 4 : i + 5] not in (b" ", b">", b"/"):
                return None
            if buf[gt - 1 : gt] == b"/":
                final = gt + 1
            elif (e := buf.find(b"</row>", gt)) >= 0:
                final = e + len(b"</row>")
        if final < 0:  # linha cortada entre dois blocos
            if eof:
                return None
            bloco = xml.read(_BLOCO_XML)
            eof = not bloco
            buf, pos = buf[i if i >= 0 else len(buf) :] + bloco, 0
            continue
        if (r := _R_DA_LINHA.search(buf, i, gt)) is None:
            return None
        if any(a <= int(r[1]) <= b for a, b in manter):
            partes.append(buf[i:final])
        pos = final


def read_xlsx_structure(
    path: Path, sheet: str, total_rows: int, head_rows: int = HEAD_ROWS, tail_rows: int = TAIL_ROWS
) -> SheetStructure:
    windows = sample_windows(total_rows, head_rows, tail_rows)
    structure = SheetStructure(sheet, formatting=True, sampled_rows=windows)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        ws = wb[sheet]
        with zipfile.ZipFile(path) as zf, zf.open(ws._worksheet_path.lstrip("/")) as xml:
            recortado = _xml_das_janelas(xml, windows)
        if recortado is not None:
            ws._get_source = lambda: io.BytesIO(recortado)
        for first, last in windows:
            for row in ws.iter_rows(min_row=first + 1, max_row=last + 1):
                for cell in row:
                    if cell.value is None or not hasattr(cell, "column"):
                        continue
                    pos = (cell.row - 1, cell.column - 1)
                    if cell.data_type == "f":
                        structure.formulas[pos] = str(cell.value)
                    elif kind := _OPENPYXL_TYPES.get(cell.data_type):
                        structure.types[pos] = kind
                    if cell.font is not None and cell.font.b:
                        structure.bold.append(pos)
        with ws._get_source() as xml:
            structure.merged = _xlsx_merges(xml)
    finally:
        wb.close()
    return structure


def _python_type(value: Any) -> CellType | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return CellType.BOOL
    if isinstance(value, int | float):
        return CellType.NUMBER
    if isinstance(value, datetime | date | time | timedelta):
        return CellType.DATE
    return CellType.TEXT


_CALAMINE_WARNING = {
    "xls": "Negrito e fórmulas não são lidos em .xls; a detecção usa só os valores e as mesclagens.",
    "ods": "Negrito, fórmulas e mesclagens não são lidos em .ods; a detecção usa só os valores.",
}


def calamine_structure(
    sheet: str,
    grid: list[list[Any]],
    merged: list[tuple[tuple[int, int], tuple[int, int]]] | None,
    fmt: str = "xls",
    head_rows: int = HEAD_ROWS,
    tail_rows: int = TAIL_ROWS,
) -> SheetStructure:
    """Estrutura de uma aba ``.xls``/``.ods`` a partir da grade que o
    ``python-calamine`` já leu para os valores (sem reler o arquivo)."""
    windows = sample_windows(len(grid), head_rows, tail_rows)
    structure = SheetStructure(
        sheet,
        formatting=False,
        sampled_rows=windows,
        warnings=[_CALAMINE_WARNING.get(fmt, _CALAMINE_WARNING["xls"])],
    )
    for first, last in windows:
        for r in range(first, last + 1):
            for c, value in enumerate(grid[r]):
                if kind := _python_type(value):
                    structure.types[(r, c)] = kind
    structure.merged = [MergedRange(a[0], a[1], b[0], b[1]) for a, b in merged or []]
    return structure

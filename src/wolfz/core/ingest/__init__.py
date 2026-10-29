"""Ingestão: abrir o arquivo, detectar encoding/separador e ler os valores como texto.

``import_file`` é o caminho completo da importação (§6.5 do design, sem a
detecção): valida limites e formato, lê a aba e grava no workspace
``raw.parquet`` (a grade, tudo como texto), ``structure.json`` (mesclagens,
negrito, fórmulas) e ``project.json``. O mesmo arquivo, com a mesma aba,
reaproveita o ``raw.parquet`` de um projeto anterior pelo hash (§4.4).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from wolfz.core.ingest import errors
from wolfz.core.ingest.cells import Cell, CellMatrix, CellType
from wolfz.core.ingest.csv import open_csv_lazy, sniff_csv
from wolfz.core.ingest.errors import IngestError
from wolfz.core.ingest.excel import SheetInfo, list_sheets, read_sheet, read_sheet_raw, resolve_sheet
from wolfz.core.ingest.formats import Format, detect_format, ensure_readable
from wolfz.core.ingest.limits import DEFAULT_LIMITS, Limits, check_file_size, check_zip
from wolfz.core.ingest.structure import SheetStructure, sample_windows
from wolfz.core.workspace import (
    PROJECT_FILE,
    RAW_FILE,
    STRUCTURE_FILE,
    Workspace,
    cache_key,
    file_sha256,
    link_or_copy,
    write_json_atomic,
)

__all__ = [
    "ABAS_DIR",
    "Cell",
    "CellMatrix",
    "CellType",
    "ImportResult",
    "IngestError",
    "Limits",
    "SheetInfo",
    "SheetStructure",
    "detect_format",
    "import_file",
    "list_sheets",
    "open_file",
    "read_sheet",
    "read_sheet_raw",
]


@dataclass
class ImportResult:
    project_id: str
    path: Path
    project: dict[str, Any]
    structure: SheetStructure
    reused: bool  # raw.parquet reaproveitado de outro projeto (mesmo hash)

    def raw(self) -> pl.LazyFrame:
        return pl.scan_parquet(self.path / RAW_FILE)

    def cells(self, rows: list[int] | None = None) -> CellMatrix:
        """Matriz de células para a detecção; por padrão, as linhas amostradas."""
        return CellMatrix.from_frame(self.raw().collect(), self.structure, rows)


def open_file(path: str | Path, limits: Limits = DEFAULT_LIMITS) -> tuple[Path, Format, int]:
    """Verificações baratas antes de qualquer leitura pesada: o arquivo
    existe e abre, cabe nos limites e é mesmo uma planilha. Devolve
    ``(caminho, formato, tamanho)``."""
    path = Path(path).expanduser()
    if not path.name.startswith("~$") and not path.is_file():
        raise errors.not_found(path.name)
    ensure_readable(path)
    size = check_file_size(path, limits)
    if size == 0:
        raise errors.empty_file(path.name)
    fmt = detect_format(path)
    if fmt in ("xlsx", "ods"):
        check_zip(path, limits)
    return path.resolve(), fmt, size


def _write_parquet(df: pl.DataFrame | pl.LazyFrame, dest: Path) -> None:
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        if isinstance(df, pl.LazyFrame):
            df.sink_parquet(tmp)
        else:
            df.write_parquet(tmp)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _raw_shape(raw: Path) -> tuple[int, list[str]]:
    lf = pl.scan_parquet(raw)
    return lf.select(pl.len()).collect().item(), lf.collect_schema().names()


ABAS_DIR = "abas"


def _gravar_abas(
    path: Path, fmt: Format, sha: str, sheets: list[SheetInfo], folder: Path
) -> list[dict[str, Any]]:
    """Grava a grade de cada aba visível em ``abas/<i>.parquet`` (F3): o
    arquivo enviado pela interface é apagado depois da importação, e a regra
    de abas da receita pode mudar depois. Aba oculta não é gravada (R6)."""
    (folder / ABAS_DIR).mkdir()
    abas = []
    for i, s in enumerate(x for x in sheets if not x.hidden):
        destino = folder / ABAS_DIR / f"{i}.parquet"
        _write_parquet(read_sheet_raw(path, s.name), destino)
        rows, _ = _raw_shape(destino)
        abas.append(
            {
                "name": s.name,
                "file": f"{ABAS_DIR}/{i}.parquet",
                "cache_key": cache_key(sha, s.name, None),
                "rows": rows,
            }
        )
    return abas


def import_file(
    source: str | Path,
    sheet: str | int | None = None,
    workspace: Workspace | None = None,
    limits: Limits = DEFAULT_LIMITS,
    all_sheets: bool = False,
) -> ImportResult:
    """Importa um arquivo para um projeto novo no workspace.

    Com ``all_sheets`` (juntar abas, F3), também grava a grade de cada aba
    visível, em ``project.json → abas``; ``raw.parquet`` continua sendo a da
    aba escolhida. Qualquer falha levanta ``IngestError`` e não deixa
    projeto pela metade."""
    path, fmt, size = open_file(source, limits)
    sha = file_sha256(path)
    sheets = list_sheets(path, fmt, limits) if fmt != "csv" else []
    sheet_name = resolve_sheet(path, sheets, sheet) if fmt != "csv" else None
    # A área ainda é a aba inteira; a detecção (F1.C) passa a restringi-la.
    area = None
    key = cache_key(sha, sheet_name, area)

    ws = workspace or Workspace()
    project_id, folder = ws.new_project()
    try:
        with ws.lock(project_id):
            src_meta: dict[str, Any] = {}
            cached = ws.find_cached_raw(key, exclude=project_id)
            if cached is not None:
                link_or_copy(cached / RAW_FILE, folder / RAW_FILE)
                link_or_copy(cached / STRUCTURE_FILE, folder / STRUCTURE_FILE)
                structure = SheetStructure.from_dict(
                    json.loads((folder / STRUCTURE_FILE).read_text(encoding="utf-8"))
                )
                old = json.loads((cached / PROJECT_FILE).read_text(encoding="utf-8"))["source"]
                src_meta = {k: old[k] for k in ("encoding", "separator") if k in old}
            elif fmt == "csv":
                encoding, separator = sniff_csv(path)
                src_meta = {"encoding": encoding, "separator": separator}
                with open_csv_lazy(path, encoding, separator, has_header=False, tmp_dir=folder) as lf:
                    _write_parquet(lf, folder / RAW_FILE)
                height, _ = _raw_shape(folder / RAW_FILE)
                structure = SheetStructure(None, sampled_rows=sample_windows(height))
            else:
                data = read_sheet(path, sheet_name, fmt, sheets=sheets)
                _write_parquet(data.frame, folder / RAW_FILE)
                structure = data.structure
            if cached is None:
                write_json_atomic(folder / STRUCTURE_FILE, structure.to_dict())

            rows, columns = _raw_shape(folder / RAW_FILE)
            project = {
                "id": project_id,
                "name": path.name,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "source": {
                    "path": str(path),
                    "name": path.name,
                    "format": fmt,
                    "size": size,
                    "sha256": sha,
                    "sheet": sheet_name,
                    "area": area,
                    "cache_key": key,
                    **src_meta,
                },
                "sheets": [s.to_dict() for s in sheets],
                "raw": {"rows": rows, "columns": columns},
            }
            if all_sheets and fmt != "csv":
                project["abas"] = _gravar_abas(path, fmt, sha, sheets, folder)
            write_json_atomic(folder / PROJECT_FILE, project)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return ImportResult(project_id, folder, project, structure, reused=cached is not None)

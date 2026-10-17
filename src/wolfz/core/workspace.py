"""Workspace local: ``~/.wolfz/projects/<ulid>/`` (§4.2 do design).

Só o arquivo original e a receita são fonte de verdade; tudo o que fica
aqui é derivado e pode ser reconstruído. A pasta raiz pode ser trocada pela
variável de ambiente ``WOLFZ_HOME`` (testes, instalação portátil).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from filelock import FileLock
from ulid import ULID

PROJECT_ID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

PROJECT_FILE = "project.json"
RAW_FILE = "raw.parquet"
STRUCTURE_FILE = "structure.json"
LOCK_FILE = ".lock"


def default_root() -> Path:
    return Path(os.environ.get("WOLFZ_HOME") or Path.home() / ".wolfz")


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    """Hash do arquivo original, lido em blocos."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, data: Any) -> None:
    """Grava em temporário e renomeia: uma falha no meio nunca deixa um JSON
    pela metade (§9)."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def link_or_copy(src: Path, dest: Path) -> None:
    """Hard link quando o sistema de arquivos permite (os derivados nunca são
    alterados no lugar), cópia quando não."""
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


class Workspace:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_root()

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    def project_dir(self, project_id: str) -> Path:
        """Pasta do projeto. O ID é validado antes de virar caminho, o que
        fecha path traversal (§4.3)."""
        if not PROJECT_ID.fullmatch(project_id):
            raise ValueError(f"ID de projeto inválido: {project_id!r}")
        return self.projects_dir / project_id

    def new_project(self) -> tuple[str, Path]:
        project_id = str(ULID())
        path = self.project_dir(project_id)
        path.mkdir(parents=True)
        return project_id, path

    def lock(self, project_id: str) -> FileLock:
        """Lock do sistema operacional por projeto (§9)."""
        return FileLock(self.project_dir(project_id) / LOCK_FILE)

    def projects(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """``(id, project.json)`` de cada projeto legível, do mais antigo ao
        mais novo (o ULID ordena por criação)."""
        if not self.projects_dir.is_dir():
            return
        for entry in sorted(self.projects_dir.iterdir()):
            meta = entry / PROJECT_FILE
            if not PROJECT_ID.fullmatch(entry.name) or not meta.is_file():
                continue
            try:
                yield entry.name, json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

    def find_cached_raw(self, cache_key: str, exclude: str | None = None) -> Path | None:
        """Pasta de um projeto que já tem o ``raw.parquet`` desta chave
        (hash do arquivo + aba + área, §4.4)."""
        for project_id, meta in self.projects():
            if project_id == exclude or meta.get("source", {}).get("cache_key") != cache_key:
                continue
            folder = self.project_dir(project_id)
            if (folder / RAW_FILE).is_file() and (folder / STRUCTURE_FILE).is_file():
                return folder
        return None


def cache_key(sha256: str, sheet: str | None, area: str | None) -> str:
    """Chave do ``raw.parquet``: o mesmo arquivo, aba e área produzem a mesma
    tabela crua."""
    return hashlib.sha256(f"{sha256}\0{sheet or ''}\0{area or ''}".encode()).hexdigest()

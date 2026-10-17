"""Checkpoints do preview (F1.F, §4.4 e §8.4 do design).

Cada passo da receita tem uma chave de conteúdo encadeada::

    chave(raw)  = sha256("raw" + chave do raw.parquet)
    chave(s_N)  = sha256(chave(s_N-1) + passo N serializado, sem o id)

Editar o passo N muda a chave de N em diante e não toca nas anteriores:
"editar o passo N invalida os checkpoints de N em diante" sem nenhuma lógica
de invalidação. Renumerar ids não muda nada; mudar um parâmetro, sim.

O que fica em ``checkpoints/<chave>/``:

- ``meta.json``: total de linhas e esquema da tabela depois do passo;
- ``pagina_<offset>_<limit>.parquet``: as páginas já pedidas (é só isso que
  se materializa para passos baratos);
- ``completo.parquet``: a tabela inteira, só para passos com
  ``full_checkpoint`` (``unpivot``, ``dedupe``, ``sort`` e os que rodam
  função Python por valor). Os passos seguintes partem dele.

Cada uso toca a data de modificação da pasta; a limpeza (``recolher``)
apaga as menos usadas até o cache inteiro do workspace caber no limite.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from filelock import FileLock, Timeout

from wolfz.core.recipe import Op

LIMITE_CACHE = 2 * 1024**3  # 2 GB (F0.A3, §8.4)
PASTA = "checkpoints"


def chave_raw(raw_key: str) -> str:
    return hashlib.sha256(f"raw\0{raw_key}".encode()).hexdigest()


def chave_passo(anterior: str, passo: Op) -> str:
    """Chave do passo a partir da chave do anterior. O ``id`` não entra."""
    conteudo = json.dumps(passo.model_dump(mode="json", exclude={"id"}), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{anterior}\0{conteudo}".encode()).hexdigest()


def chaves(raw_key: str, passos: list[Op]) -> list[str]:
    """Chave do raw seguida da chave de cada passo, em ordem."""
    lista = [chave_raw(raw_key)]
    for passo in passos:
        lista.append(chave_passo(lista[-1], passo))
    return lista


def _grava_atomico(destino: Path, escrever) -> None:
    tmp = destino.with_name(f".{destino.name}.tmp")
    try:
        escrever(tmp)
        tmp.replace(destino)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class Checkpoints:
    """Cache de um projeto: ``<projeto>/checkpoints/``."""

    raiz: Path

    def pasta(self, chave: str) -> Path:
        return self.raiz / chave

    def _usar(self, chave: str) -> Path:
        pasta = self.pasta(chave)
        pasta.mkdir(parents=True, exist_ok=True)
        os.utime(pasta)  # marca o uso para o LRU
        return pasta

    # Tabela inteira -------------------------------------------------------

    def completo(self, chave: str) -> Path | None:
        path = self.pasta(chave) / "completo.parquet"
        if path.is_file():
            self._usar(chave)
            return path
        return None

    def grava_completo(self, chave: str, lf: pl.LazyFrame) -> Path:
        destino = self._usar(chave) / "completo.parquet"
        _grava_atomico(destino, lambda tmp: lf.sink_parquet(tmp))
        return destino

    # Página e metadados ---------------------------------------------------

    def pagina(self, chave: str, offset: int, limit: int) -> pl.DataFrame | None:
        path = self.pasta(chave) / f"pagina_{offset}_{limit}.parquet"
        if path.is_file():
            self._usar(chave)
            return pl.read_parquet(path)
        return None

    def grava_pagina(self, chave: str, offset: int, limit: int, df: pl.DataFrame) -> None:
        destino = self._usar(chave) / f"pagina_{offset}_{limit}.parquet"
        _grava_atomico(destino, lambda tmp: df.write_parquet(tmp))

    def meta(self, chave: str) -> dict[str, Any] | None:
        path = self.pasta(chave) / "meta.json"
        if path.is_file():
            self._usar(chave)
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def grava_meta(self, chave: str, meta: dict[str, Any]) -> None:
        destino = self._usar(chave) / "meta.json"
        _grava_atomico(destino, lambda tmp: tmp.write_text(json.dumps(meta), encoding="utf-8"))


# ---------------------------------------------------------------------------
# Limpeza (F1.F4)
# ---------------------------------------------------------------------------


def _tamanho(pasta: Path) -> int:
    return sum(p.stat().st_size for p in pasta.rglob("*") if p.is_file())


def projeto_travado(projeto: Path) -> bool:
    """Projeto aberto em alguma instância (lock do SO ativo, §9)."""
    lock_path = projeto / ".lock"
    if not lock_path.exists():
        return False
    lock = FileLock(lock_path)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True
    lock.release()
    return False


def _entradas(projects_dir: Path) -> Iterator[tuple[Path, Path]]:
    if not projects_dir.is_dir():
        return
    for projeto in projects_dir.iterdir():
        cache = projeto / PASTA
        if cache.is_dir():
            for pasta in cache.iterdir():
                if pasta.is_dir():
                    yield projeto, pasta


@dataclass
class Recolhimento:
    antes: int
    depois: int
    apagados: int
    pulados_por_lock: int


def recolher(
    projects_dir: Path, limite: int = LIMITE_CACHE, protegidos: set[Path] | None = None
) -> Recolhimento:
    """Apaga checkpoints, do uso mais antigo para o mais recente, até o
    cache de todos os projetos caber em ``limite``. Só checkpoints: o
    ``raw.parquet`` e a receita nunca são tocados. Projetos com lock ativo
    (abertos em outra instância) e os de ``protegidos`` (o que esta
    instância está editando) ficam de fora."""
    protegidos = {p.resolve() for p in protegidos or set()}
    entradas = [
        (projeto, pasta, _tamanho(pasta), pasta.stat().st_mtime) for projeto, pasta in _entradas(projects_dir)
    ]
    total = sum(t for _, _, t, _ in entradas)
    antes, apagados, pulados = total, 0, 0
    travados: dict[Path, bool] = {}
    for projeto, pasta, tamanho, _ in sorted(entradas, key=lambda e: e[3]):
        if total <= limite:
            break
        if projeto.resolve() in protegidos:
            continue
        if travados.setdefault(projeto, projeto_travado(projeto)):
            pulados += 1
            continue
        shutil.rmtree(pasta, ignore_errors=True)
        total -= tamanho
        apagados += 1
    return Recolhimento(antes, total, apagados, pulados)

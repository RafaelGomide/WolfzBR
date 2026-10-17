"""Preview paginado com checkpoints (F1.F1–F1.F3).

``preview`` devolve a página ``offset..offset+limit`` da tabela depois de um
passo da receita, materializando só essa página. Passos caros
(``full_checkpoint``) gravam a tabela inteira uma vez; o plano lazy da página
parte do último deles que ainda vale. Editar o último passo, o caso mais
comum, recalcula só a partir do checkpoint mais próximo.

A reaplicação (``wolfz run``) não usa nada disto (§4.5): lê o arquivo novo e
roda a receita inteira num único plano.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from wolfz.core.engine import StepError, collect, run
from wolfz.core.engine.cache import LIMITE_CACHE, Checkpoints, chaves, recolher
from wolfz.core.recipe import Op, Recipe
from wolfz.core.workspace import PROJECT_FILE, RAW_FILE

LIMITE_PAGINA = 1000  # §5: limit máximo do GET /preview


@dataclass
class Page:
    frame: pl.DataFrame
    total_rows: int
    offset: int
    # De onde veio: "pagina" (cache da página), "checkpoint:<i>" (partiu do
    # checkpoint completo do passo i) ou "raw". Usado no benchmark.
    origem: str = "raw"
    checkpoints_gravados: list[int] = field(default_factory=list)

    @property
    def columns(self) -> list[dict[str, str]]:
        return [{"name": n, "dtype": str(t)} for n, t in self.frame.schema.items()]

    def to_dict(self) -> dict[str, Any]:
        """Corpo da resposta do ``GET /preview`` (§5)."""
        return {
            "columns": self.columns,
            "rows": [list(r) for r in self.frame.rows()],
            "total_rows": self.total_rows,
            "offset": self.offset,
        }


def _passos(recipe: Recipe, step: str | None) -> list[Op]:
    """Passos até ``step`` (inclusive). ``None``: a receita inteira;
    ``"raw"``: nenhum."""
    if step is None:
        return list(recipe.steps)
    if step == "raw":
        return []
    ids = [s.id for s in recipe.steps]
    if step not in ids:
        raise ValueError(f"a receita não tem o passo {step!r} (passos: {', '.join(ids) or 'nenhum'})")
    return list(recipe.steps[: ids.index(step) + 1])


def _sub(recipe: Recipe, passos: list[Op]) -> Recipe:
    return recipe.model_copy(update={"steps": passos})


def _executa(fn: Callable[[], Any], recipe: Recipe, lf: pl.LazyFrame) -> Any:
    """Roda ``fn``; se falhar com os dados, descobre o passo culpado
    (``collect`` reexecuta passo a passo e levanta ``StepError``)."""
    try:
        return fn()
    except StepError:
        raise
    except Exception:
        collect(recipe, lf)
        raise


def preview(
    raw: Path,
    raw_key: str,
    recipe: Recipe,
    step: str | None = None,
    offset: int = 0,
    limit: int = 200,
    cache: Checkpoints | None = None,
) -> Page:
    """Página da tabela depois de ``step``.

    ``raw`` é o ``raw.parquet`` do projeto e ``raw_key`` a chave dele (a
    ``cache_key`` do ``project.json``). Sem ``cache``, calcula tudo do zero
    e não grava nada."""
    if offset < 0 or not 1 <= limit <= LIMITE_PAGINA:
        raise ValueError(f"offset deve ser >= 0 e limit entre 1 e {LIMITE_PAGINA}")
    passos = _passos(recipe, step)
    ks = chaves(raw_key, passos)
    alvo = ks[-1]

    if cache is not None:
        pagina, meta = cache.pagina(alvo, offset, limit), cache.meta(alvo)
        if pagina is not None and meta is not None:
            return Page(pagina, meta["total_rows"], offset, origem="pagina")

    # Parte do raw e atravessa os checkpoints completos, gravando os que faltam.
    lf, inicio, origem, gravados = pl.scan_parquet(raw), 0, "raw", []
    for i, passo in enumerate(passos, start=1):
        if not passo.full_checkpoint or cache is None:
            continue
        caminho = cache.completo(ks[i])
        if caminho is None:
            trecho = _sub(recipe, passos[inicio:i])
            plano = run(trecho, lf)
            caminho = _executa(lambda c=ks[i], p=plano: cache.grava_completo(c, p), trecho, lf)
            gravados.append(i)
        lf, inicio, origem = pl.scan_parquet(caminho), i, f"checkpoint:{i}"

    resto = _sub(recipe, passos[inicio:])
    plano = run(resto, lf)
    meta = cache.meta(alvo) if cache is not None else None
    if meta is None:
        total = _executa(lambda: plano.select(pl.len()).collect().item(), resto, lf)
        meta = {"total_rows": total}
        if cache is not None:
            cache.grava_meta(alvo, meta)
    pagina = _executa(lambda: plano.slice(offset, limit).collect(), resto, lf)
    if cache is not None:
        cache.grava_pagina(alvo, offset, limit, pagina)
    return Page(pagina, meta["total_rows"], offset, origem=origem, checkpoints_gravados=gravados)


def preview_project(
    project_dir: Path,
    recipe: Recipe,
    step: str | None = None,
    offset: int = 0,
    limit: int = 200,
    limite_cache: int = LIMITE_CACHE,
) -> Page:
    """``preview`` de um projeto do workspace, com o cache em
    ``<projeto>/checkpoints/``. Depois de gravar um checkpoint completo (o
    que mais ocupa disco), recolhe o cache do workspace até
    ``limite_cache``, sem tocar no projeto aberto (F1.F4)."""
    meta = json.loads((project_dir / PROJECT_FILE).read_text(encoding="utf-8"))
    page = preview(
        project_dir / RAW_FILE,
        meta["source"]["cache_key"],
        recipe,
        step,
        offset,
        limit,
        Checkpoints(project_dir / "checkpoints"),
    )
    if page.checkpoints_gravados:
        recolher(project_dir.parent, limite_cache, protegidos={project_dir})
    return page

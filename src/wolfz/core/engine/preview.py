"""Preview paginado com checkpoints (F1.F1–F1.F3).

``preview`` devolve a página ``offset..offset+limit`` da tabela depois de um
passo da receita, materializando só essa página. Passos caros
(``full_checkpoint``) gravam a tabela inteira uma vez; o plano lazy da página
parte do último deles que ainda vale. Editar o último passo, o caso mais
comum, recalcula só a partir do checkpoint mais próximo.

``contagens`` faz a reconciliação de linhas da receita (F1 da 1.1) sobre o
mesmo cache: a contagem de cada passo fica no ``meta.json`` dele, e só os
passos que mudam o número de linhas são contados. Ela fica fora do
``preview`` para a grade não esperar a contagem.

A reaplicação (``wolfz run``) não usa nada disto (§4.5): lê o arquivo novo e
roda a receita inteira num único plano.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from wolfz.core.engine import StepError, collect, conta_area, run
from wolfz.core.engine.cache import LIMITE_CACHE, Checkpoints, chaves, recolher
from wolfz.core.engine.reconcilia import OutsideColumn, Reconciliation, StepCount, conta_passo
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
    ``"raw"``: nenhum. Passos desativados ficam de fora."""
    if step is None:
        return recipe.active_steps
    if step == "raw":
        return []
    ids = [s.id for s in recipe.steps]
    if step not in ids:
        raise ValueError(f"a receita não tem o passo {step!r} (passos: {', '.join(ids) or 'nenhum'})")
    return [s for s in recipe.steps[: ids.index(step) + 1] if s.enabled]


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


def _grava_meta(cache: Checkpoints | None, chave: str, meta: dict[str, Any]) -> None:
    if cache is not None:
        cache.grava_meta(chave, {**(cache.meta(chave) or {}), **meta})


def contagens(raw: Path, raw_key: str, recipe: Recipe, cache: Checkpoints | None = None) -> Reconciliation:
    """A reconciliação de linhas da receita inteira, a mesma do
    ``wolfz.run_report`` no mesmo arquivo.

    Parte do ``raw.parquet`` e atravessa os checkpoints completos, como o
    ``preview`` (e grava os que faltam). Cada passo que não é ``mantem`` é
    contado com ``select(pl.len())`` a partir do último checkpoint, e a
    contagem fica no ``meta.json`` do passo: depois de editar o passo N, só
    os passos de N em diante voltam a ser contados. As linhas lidas ficam no
    ``meta.json`` do raw. Falhou um passo: ``StepError`` com
    ``contagem_parcial``, como em ``reconciliar``."""
    from wolfz.ops.estrutura import (
        ColunaFora,
        ContagemArea,
        linhas_nao_vazias,
    )  # wolfz.ops importa wolfz.core

    passos = recipe.active_steps
    ks = chaves(raw_key, passos)
    lf, inicio = pl.scan_parquet(raw), 0
    meta0 = (cache.meta(ks[0]) if cache is not None else None) or {}
    altura = meta0.get("total_rows")
    if altura is None:
        altura = lf.select(pl.len()).collect().item()
    lidas: int | None = meta0.get("linhas_nao_vazias")
    lista: list[StepCount] = []
    fora: list[OutsideColumn] = []
    fins: dict[str, tuple[int | None, int | None]] = {}
    unpivot_antes = False
    try:
        for i, passo in enumerate(passos, start=1):
            caminho = None
            if passo.full_checkpoint and cache is not None:
                caminho = cache.completo(ks[i])
                if caminho is None:
                    trecho = _sub(recipe, passos[inicio:i])
                    plano = run(trecho, lf)
                    caminho = _executa(lambda c=ks[i], p=plano: cache.grava_completo(c, p), trecho, lf)
            if passo.efeito_linhas == "mantem":
                lista.append(conta_passo(passo, altura, altura))
            else:
                meta = (cache.meta(ks[i]) if cache is not None else None) or {}
                area_dict = meta.get("area")
                saida = meta.get("total_rows")
                if saida is None or (passo.op == "select_range" and area_dict is None):
                    if caminho is not None:  # a contagem sai do metadado do Parquet
                        saida = pl.scan_parquet(caminho).select(pl.len()).collect().item()
                    else:
                        trecho = _sub(recipe, passos[inicio:i])
                        plano = run(trecho, lf)
                        saida = _executa(lambda p=plano: p.select(pl.len()).collect().item(), trecho, lf)
                    novo: dict[str, Any] = {"total_rows": saida}
                    if passo.op == "select_range":
                        grade = run(_sub(recipe, passos[inicio : i - 1]), lf)
                        area_dict = asdict(passo.contagem_da_area(grade))  # type: ignore[attr-defined]
                        novo["area"] = area_dict
                    _grava_meta(cache, ks[i], novo)
                if area_dict is None:
                    lista.append(conta_passo(passo, altura, saida, unpivot_antes=unpivot_antes))
                else:
                    area = ContagemArea(
                        **{
                            **area_dict,
                            "colunas_fora": tuple(ColunaFora(**c) for c in area_dict["colunas_fora"]),
                        }
                    )
                    contagem, cols, fim = conta_area(passo, altura, saida, area)
                    lista.append(contagem)
                    fora += cols
                    fins.update(fim)
                    if lidas is None and i == 1:
                        lidas = area.nao_vazias
                unpivot_antes = unpivot_antes or passo.op == "unpivot"
                altura = saida
            if caminho is not None:
                lf, inicio = pl.scan_parquet(caminho), i
        # Os passos mantem do fim não foram contados nem rodados: monta o
        # plano deles (sem ler dados) para o erro de coluna aparecer aqui.
        run(_sub(recipe, passos[inicio:]), lf)
    except StepError as exc:
        ids = [c.id for c in lista]
        feitos = lista[: ids.index(exc.step_id)] if exc.step_id in ids else lista
        if lidas is None:
            lidas = linhas_nao_vazias(pl.scan_parquet(raw))
        exc.contagem_parcial = (lidas, tuple(feitos))
        raise
    if lidas is None:
        lidas = linhas_nao_vazias(pl.scan_parquet(raw))
    if "linhas_nao_vazias" not in meta0:
        total_raw = meta0.get("total_rows", pl.scan_parquet(raw).select(pl.len()).collect().item())
        _grava_meta(cache, ks[0], {"total_rows": total_raw, "linhas_nao_vazias": lidas})
    return Reconciliation(lidas, altura, tuple(lista), tuple(fora), fins)


def contagens_project(project_dir: Path, recipe: Recipe, limite_cache: int = LIMITE_CACHE) -> Reconciliation:
    """``contagens`` de um projeto do workspace, com o cache do preview."""
    meta = json.loads((project_dir / PROJECT_FILE).read_text(encoding="utf-8"))
    cache = Checkpoints(project_dir / "checkpoints")
    antes = {p.name for p in cache.raiz.glob("*")} if cache.raiz.is_dir() else set()
    resultado = contagens(project_dir / RAW_FILE, meta["source"]["cache_key"], recipe, cache)
    if cache.raiz.is_dir() and {p.name for p in cache.raiz.glob("*")} - antes:
        recolher(project_dir.parent, limite_cache, protegidos={project_dir})
    return resultado

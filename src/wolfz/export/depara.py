"""Tabelas de-para exportadas junto com o M e o script Python (ADR-7).

Operação sem tradução fiel em M (o fuzzy de ``normalize_municipio``) é
resolvida pelo WolfzBR sobre os dados do projeto; o M e o script fazem join
exato com o resultado, gravado em ``depara_municipios.csv``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from wolfz.core.recipe import Recipe

ARQUIVO_DEPARA = "depara_municipios.csv"


def depara_municipios(recipe: Recipe, lf: pl.LazyFrame) -> pl.DataFrame | None:
    """De-para de todos os passos ``normalize_municipio`` ativos, cada um
    calculado sobre a tabela que chega a ele. ``None`` se não há nenhum."""
    passos = recipe.active_steps
    ultimo = max((i for i, s in enumerate(passos) if s.op == "normalize_municipio"), default=-1)
    partes = []
    # Só até o último município, e sem as verificações: elas não mudam a
    # tabela, e uma reprovada nos dados de hoje não pode impedir a exportação
    # do M (no Power BI ela vale para o arquivo do mês que vier).
    for step in passos[: ultimo + 1]:
        if step.op == "normalize_municipio":
            partes.append(step.depara(lf))  # type: ignore[attr-defined]
        elif step.op != "assert":
            lf = step.to_polars(lf)
    return pl.concat(partes) if partes else None


def gravar_depara(depara: pl.DataFrame, path: Path) -> None:
    """CSV com ``;``, UTF-8 com BOM: abre certo no Excel e no ``Csv.Document``."""
    depara.write_csv(path, separator=";", include_bom=True)

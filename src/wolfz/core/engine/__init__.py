"""Motor: compõe os passos da receita em um plano lazy do Polars.

- ``run(recipe, lf)``: monta o plano, validando passo a passo que cada um
  se aplica à tabela (colunas existem etc.), sem ler os dados.
- ``collect(recipe, lf)``: executa o plano; se algo falhar com os dados,
  descobre em qual passo foi.
- ``run_file(recipe, arquivo)``: a função pública ``wolfz.run``, para
  notebook e scripts.

Toda falha vira ``StepError``, com o id do passo e as colunas disponíveis.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from wolfz.core.engine.errors import StepError, missing_column
from wolfz.core.ingest.csv import read_csv_raw
from wolfz.core.recipe import Op, Recipe, load_recipe

__all__ = ["StepError", "collect", "run", "run_file"]


def _where(previous: Op | None) -> str:
    return f"após o passo {previous.id}" if previous else "na tabela de entrada"


def _step_error(step: Op, previous: Op | None, columns: list[str], exc: Exception) -> StepError:
    if isinstance(exc, pl.exceptions.ColumnNotFoundError):
        name = missing_column(exc)
        what = f"a coluna {name!r}" if name else "uma coluna"
        return StepError(
            step.id,
            step.op,
            f"O passo {step.id} ({step.op}) referencia {what}, que não existe {_where(previous)}.",
            columns,
            title="Coluna não encontrada",
        )
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return StepError(step.id, step.op, f"O passo {step.id} ({step.op}) falhou: {reason}", columns)


def run(recipe: Recipe, lf: pl.LazyFrame) -> pl.LazyFrame:
    """Compõe ``to_polars`` de cada passo, em ordem. Resolve o schema depois
    de cada passo (barato, não lê dados) para que o erro aponte o passo
    certo, e não apareça só no ``collect`` sem dizer de onde veio."""
    previous: Op | None = None
    for step in recipe.steps:
        columns = lf.collect_schema().names()
        try:
            lf = step.to_polars(lf)
            lf.collect_schema()
        except StepError:
            raise
        except Exception as exc:
            raise _step_error(step, previous, columns, exc) from exc
        previous = step
    return lf


def collect(recipe: Recipe, lf: pl.LazyFrame) -> pl.DataFrame:
    """Executa a receita inteira. Erro que só aparece com os dados (um
    parser que falha em certo valor, por exemplo) é localizado
    reexecutando os passos um a um — custo pago só quando algo falha."""
    plan = run(recipe, lf)
    try:
        return plan.collect()
    except Exception as exc:
        original = exc
    partial = lf
    previous: Op | None = None
    for step in recipe.steps:
        columns = partial.collect_schema().names()
        partial = step.to_polars(partial)
        try:
            partial.collect()
        except Exception as exc:
            raise _step_error(step, previous, columns, exc) from exc
        previous = step
    raise original  # não reproduziu passo a passo: devolve o erro como veio


def run_file(recipe: Recipe | str | Path, input_path: str | Path) -> pl.DataFrame:
    """Aplica a receita a um arquivo e devolve a tabela limpa.

    Exposta como ``wolfz.run``::

        df = wolfz.run("vendas.wolfz.json", "vendas_jan.csv")

    Por enquanto lê só CSV (tudo como texto, com encoding e separador
    detectados). Excel e ODS entram com a ingestão completa (F1.A)."""
    if not isinstance(recipe, Recipe):
        recipe = load_recipe(recipe)
    path = Path(input_path)
    if path.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError(f"por enquanto só arquivos CSV; {path.suffix or 'sem extensão'} entra na versão 0.2")
    return collect(recipe, read_csv_raw(path).lazy())

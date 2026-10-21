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

import re
from pathlib import Path

import polars as pl

from wolfz.core.engine.errors import StepError, missing_column
from wolfz.core.ingest import list_sheets, open_file, read_sheet_raw
from wolfz.core.ingest.csv import open_csv_lazy, read_csv_raw
from wolfz.core.recipe import Op, Recipe, load_recipe

__all__ = ["StepError", "collect", "read_input", "run", "run_file"]


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
    if isinstance(exc, AssertionError):  # passo assert (F2.F1): o arquivo não é o esperado
        return StepError(
            step.id,
            step.op,
            f"O passo {step.id} (verificação) reprovou: {reason}",
            columns,
            title="Verificação reprovada",
        )
    return StepError(step.id, step.op, f"O passo {step.id} ({step.op}) falhou: {reason}", columns)


def run(recipe: Recipe, lf: pl.LazyFrame) -> pl.LazyFrame:
    """Compõe ``to_polars`` de cada passo, em ordem. Resolve o schema depois
    de cada passo (barato, não lê dados) para que o erro aponte o passo
    certo, e não apareça só no ``collect`` sem dizer de onde veio."""
    previous: Op | None = None
    for step in recipe.active_steps:
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
    for step in recipe.active_steps:
        columns = partial.collect_schema().names()
        partial = step.to_polars(partial)
        try:
            partial.collect()
        except Exception as exc:
            raise _step_error(step, previous, columns, exc) from exc
        previous = step
    raise original  # não reproduziu passo a passo: devolve o erro como veio


# Passos que trabalham sobre a grade crua: se a receita começa por um deles,
# o CSV é lido sem cabeçalho, como uma aba de planilha.
_PASSOS_DE_GRADE = {"select_range", "header_rows"}


def _sheet(recipe: Recipe, path: Path) -> str | None:
    """Aba da receita; se ela não existe no arquivo novo, a primeira que
    casa com ``source.match.sheet_name_regex`` (o nome mudou de um mês para
    o outro: 'Vendas 2024' -> 'Vendas 2025')."""
    sheet, match = recipe.source.sheet, recipe.source.match
    if match is None or match.sheet_name_regex is None:
        return sheet
    nomes = [s.name for s in list_sheets(path)]
    if sheet in nomes:
        return sheet
    return next((n for n in nomes if re.fullmatch(match.sheet_name_regex, n)), sheet)


def read_input(recipe: Recipe, input_path: str | Path) -> pl.DataFrame:
    """Lê o arquivo de entrada como a receita espera, tudo como texto.

    Planilha (``.xlsx``, ``.xls``, ``.ods``) vem como grade: colunas com o
    nome da letra e linha i = linha i + 1 da planilha. CSV vem com o
    cabeçalho da primeira linha, a não ser que a receita comece por
    ``select_range`` ou ``header_rows``; aí também vem como grade. Erros de
    leitura são ``IngestError``, com mensagem para o usuário."""
    path, fmt, _ = open_file(input_path)
    if fmt != "csv":
        return read_sheet_raw(path, _sheet(recipe, path))
    if recipe.active_steps and recipe.active_steps[0].op in _PASSOS_DE_GRADE:
        with open_csv_lazy(path, has_header=False) as lf:
            return lf.collect()
    return read_csv_raw(path)


def run_file(recipe: Recipe | str | Path, input_path: str | Path) -> pl.DataFrame:
    """Aplica a receita a um arquivo e devolve a tabela limpa.

    Exposta como ``wolfz.run``::

        df = wolfz.run("vendas.wolfz.json", "vendas_jan.xlsx")

    Lê CSV, ``.xlsx``, ``.xls`` e ``.ods`` (ver ``read_input``)."""
    if not isinstance(recipe, Recipe):
        recipe = load_recipe(recipe)
    return collect(recipe, read_input(recipe, input_path).lazy())

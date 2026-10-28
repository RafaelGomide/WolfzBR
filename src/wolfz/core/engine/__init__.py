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
from typing import Any

import polars as pl

from wolfz.core.engine.errors import StepError, missing_column
from wolfz.core.engine.reconcilia import OutsideColumn, RunReport, StepCount, conta_passo
from wolfz.core.ingest import list_sheets, open_file, read_sheet_raw
from wolfz.core.ingest.csv import open_csv_lazy, read_csv_raw
from wolfz.core.recipe import Op, Recipe, load_recipe

__all__ = [
    "RunReport",
    "StepCount",
    "StepError",
    "collect",
    "conta_area",
    "read_input",
    "reconciliar",
    "run",
    "run_file",
    "run_report",
]


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
        erro = StepError(
            step.id,
            step.op,
            f"O passo {step.id} (verificação) reprovou: {reason}",
            columns,
            title="Verificação reprovada",
        )
        erro.verificacao = getattr(exc, "verificacao", None)
        erro.valores = list(getattr(exc, "valores", []))
        return erro
    erro = StepError(step.id, step.op, f"O passo {step.id} ({step.op}) falhou: {reason}", columns)
    erro.detalhe_seguro = not isinstance(exc, pl.exceptions.PolarsError)
    return erro


def _run_steps(steps: list[Op], lf: pl.LazyFrame, previous: Op | None = None) -> pl.LazyFrame:
    for step in steps:
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


def run(recipe: Recipe, lf: pl.LazyFrame) -> pl.LazyFrame:
    """Compõe ``to_polars`` de cada passo, em ordem. Resolve o schema depois
    de cada passo (barato, não lê dados) para que o erro aponte o passo
    certo, e não apareça só no ``collect`` sem dizer de onde veio."""
    return _run_steps(recipe.active_steps, lf)


def _collect_steps(steps: list[Op], lf: pl.LazyFrame, previous: Op | None = None) -> pl.DataFrame:
    plan = _run_steps(steps, lf, previous)
    try:
        return plan.collect()
    except Exception as exc:
        original = exc
    partial = lf
    for step in steps:
        columns = partial.collect_schema().names()
        partial = step.to_polars(partial)
        try:
            partial.collect()
        except Exception as exc:
            raise _step_error(step, previous, columns, exc) from exc
        previous = step
    raise original  # não reproduziu passo a passo: devolve o erro como veio


def collect(recipe: Recipe, lf: pl.LazyFrame) -> pl.DataFrame:
    """Executa a receita inteira. Erro que só aparece com os dados (um
    parser que falha em certo valor, por exemplo) é localizado
    reexecutando os passos um a um — custo pago só quando algo falha."""
    return _collect_steps(recipe.active_steps, lf)


def conta_area(
    step: Op, rows_in: int, rows_out: int, area: Any
) -> tuple[StepCount, list[OutsideColumn], dict[str, tuple[int | None, int | None]]]:
    """A contagem de um ``select_range`` a partir da ``ContagemArea`` dele:
    o passo, as colunas fora da área e onde terminam a área e a grade."""
    contagem = conta_passo(
        step,
        rows_in,
        rows_out,
        acima=area.acima,
        vazias_abaixo=area.vazias_abaixo,
        fora=area.preenchidas_abaixo,
        colunas_fora=len(area.colunas_fora),
    )
    cols = [OutsideColumn(c.letra, c.celulas, c.cabecalho, step.id, area.area) for c in area.colunas_fora]
    fim = {step.id: (area.ultima_linha_area, area.ultima_linha_preenchida)} if area.preenchidas_abaixo else {}
    return contagem, cols, fim


def reconciliar(recipe: Recipe, grade: pl.DataFrame) -> RunReport:
    """Executa a receita contando as linhas (ADR-10).

    A receita é cortada depois de cada passo que muda o número de linhas
    (``efeito_linhas`` diferente de ``mantem``); cada trecho é um plano lazy
    coletado uma vez, e a altura do resultado é a contagem. Antes de um
    ``select_range``, a grade que entra nele é conferida pela
    ``contagem_da_area``. Falhou um passo: o ``StepError`` sai com
    ``contagem_parcial`` (linhas lidas e os passos que deram certo)."""
    from wolfz.ops.estrutura import linhas_nao_vazias  # wolfz.ops importa wolfz.core

    atual, altura = grade, grade.height
    lidas: int | None = None
    contagens: list[StepCount] = []
    fora: list[OutsideColumn] = []
    fins: dict[str, tuple[int | None, int | None]] = {}
    trecho: list[Op] = []
    anterior: Op | None = None
    unpivot_antes = False

    def coleta(passos: list[Op]) -> pl.DataFrame:
        nonlocal anterior
        df = _collect_steps(passos, atual.lazy(), anterior)
        anterior = passos[-1]
        return df

    try:
        for step in recipe.active_steps:
            if step.efeito_linhas == "mantem":
                trecho.append(step)
                contagens.append(conta_passo(step, altura, altura))
                continue
            area = None
            if step.op == "select_range":
                if trecho:  # a área é conferida na grade que entra no passo
                    atual, trecho = coleta(trecho), []
                novo = coleta([step])
                area = step.contagem_da_area(atual.lazy())  # type: ignore[attr-defined]
                if lidas is None and step is recipe.active_steps[0]:
                    lidas = area.nao_vazias
            else:
                novo = coleta([*trecho, step])
            trecho = []
            if area is None:
                contagem = conta_passo(step, altura, novo.height, unpivot_antes=unpivot_antes)
            else:
                contagem, cols, fim = conta_area(step, altura, novo.height, area)
                fora += cols
                fins.update(fim)
            contagens.append(contagem)
            unpivot_antes = unpivot_antes or step.op == "unpivot"
            atual, altura = novo, novo.height
        if trecho:
            atual = coleta(trecho)
    except StepError as exc:
        ids = [c.id for c in contagens]  # um passo mantem é contado antes de o trecho rodar
        feitos = contagens[: ids.index(exc.step_id)] if exc.step_id in ids else contagens
        exc.contagem_parcial = (
            lidas if lidas is not None else linhas_nao_vazias(grade.lazy()),
            tuple(feitos),
        )
        raise
    if lidas is None:
        lidas = linhas_nao_vazias(grade.lazy())
    return RunReport(lidas, atual.height, tuple(contagens), tuple(fora), fins, table=atual)


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


def run_report(recipe: Recipe | str | Path, input_path: str | Path) -> RunReport:
    """Como ``run_file``, mas conta as linhas de cada passo (ADR-10).

    Exposta como ``wolfz.run_report``::

        r = wolfz.run_report("vendas.wolfz.json", "vendas_mar.xlsx")
        r.table          # o mesmo DataFrame de wolfz.run
        r.rows_read, r.rows_written, r.alert
        r.to_dict()      # o JSON do --report

    Roda a receita em trechos, por isso custa um pouco mais que
    ``wolfz.run``; a tabela é a mesma."""
    if not isinstance(recipe, Recipe):
        recipe = load_recipe(recipe)
    return reconciliar(recipe, read_input(recipe, input_path))

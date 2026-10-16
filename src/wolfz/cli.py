"""CLI ``wolfz``: argumentos, saída no terminal e códigos de retorno.

Sem regra de negócio; os comandos chamam o núcleo (``wolfz.core``). As
mensagens de erro são as mesmas que a API devolve (``StepError.message``,
``RecipeError.errors``), para que interface e terminal falhem com o mesmo
texto (§5.4).
"""

from __future__ import annotations

import json
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import polars as pl
import typer

from wolfz import __version__
from wolfz.core.engine import StepError, collect
from wolfz.core.ingest.csv import read_csv_raw
from wolfz.core.recipe import RecipeError, load_recipe, recipe_json_schema


class ExitCode(IntEnum):
    OK = 0
    STEP_ERROR = 1  # um passo não se aplica a este arquivo
    INVALID_RECIPE = 2  # receita inválida ou ilegível, ou uso incorreto
    UNREADABLE_INPUT = 3  # arquivo de entrada ilegível


class Formato(StrEnum):
    csv = "csv"
    parquet = "parquet"


app = typer.Typer(
    name="wolfz",
    help="Limpeza de planilhas brasileiras com receitas reproduzíveis.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wolfz {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Mostra a versão e sai."
    ),
) -> None:
    """Limpeza de planilhas brasileiras com receitas reproduzíveis."""


def _fail(code: ExitCode, *lines: str) -> NoReturn:
    for line in lines:
        typer.echo(line, err=True)
    raise typer.Exit(int(code))


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _output_path(saida: str, arquivo: Path, formato: Formato) -> Path:
    """``-o`` pode ser um arquivo ou uma pasta (existente ou terminada em
    barra); numa pasta, o nome vem do arquivo de entrada. Recebe texto, e
    não ``Path``, porque ``Path`` descarta a barra final."""
    if saida.endswith(("/", "\\")) or Path(saida).is_dir():
        return Path(saida) / f"{arquivo.stem}.{formato.value}"
    return Path(saida)


def _write(df: pl.DataFrame, path: Path, formato: Formato) -> None:
    """Grava em arquivo temporário e renomeia: uma falha no meio nunca deixa
    uma saída pela metade (§9)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        if formato is Formato.csv:
            df.write_csv(tmp)
        else:
            df.write_parquet(tmp)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


_EPILOG = (
    "Códigos de saída: 0 ok · 1 um passo falhou neste arquivo · "
    "2 receita inválida ou uso incorreto · 3 arquivo de entrada ilegível."
)


@app.command(epilog=_EPILOG)
def run(
    receita: Annotated[Path, typer.Argument(help="Receita .wolfz.json.", show_default=False)],
    arquivo: Annotated[
        Path, typer.Argument(help="Planilha a limpar (por enquanto, só CSV).", show_default=False)
    ],
    saida: Annotated[
        str,
        typer.Option(
            "--output", "-o", help="Arquivo de saída, ou pasta (o nome vem da entrada).", show_default=False
        ),
    ],
    formato: Annotated[Formato, typer.Option("--format", "-f", help="Formato da saída.")] = Formato.csv,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Sobrescreve a saída se ela já existir.")
    ] = False,
) -> None:
    """Aplica uma receita a uma planilha e grava a tabela limpa.

    Nada é gravado se algum passo falhar.
    """
    try:
        recipe = load_recipe(receita)
    except FileNotFoundError:
        _fail(ExitCode.INVALID_RECIPE, f"Receita não encontrada: {receita}")
    except RecipeError as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Receita inválida: {receita}", *(f"  {e}" for e in exc.errors))
    except (UnicodeDecodeError, OSError) as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Não foi possível ler a receita {receita}: {_first_line(exc)}")

    destino = _output_path(saida, arquivo, formato)
    if destino.exists() and not overwrite:
        _fail(ExitCode.INVALID_RECIPE, f"A saída já existe: {destino}", "Use --overwrite para substituir.")

    if not arquivo.is_file():
        _fail(ExitCode.UNREADABLE_INPUT, f"Arquivo não encontrado: {arquivo}")
    if arquivo.suffix.lower() not in {".csv", ".txt"}:
        _fail(
            ExitCode.UNREADABLE_INPUT,
            f"Formato ainda não suportado: {arquivo.suffix or 'sem extensão'}. Por enquanto, só CSV "
            "(Excel e ODS entram na versão 0.2).",
        )
    try:
        df = read_csv_raw(arquivo)
    except (OSError, pl.exceptions.PolarsError) as exc:
        _fail(ExitCode.UNREADABLE_INPUT, f"Não foi possível ler {arquivo}: {_first_line(exc)}")

    try:
        result = collect(recipe, df.lazy())
    except StepError as exc:
        columns = ", ".join(exc.available_columns) or "(nenhuma)"
        _fail(
            ExitCode.STEP_ERROR,
            f"{exc.title}: {exc.message}",
            f"Colunas disponíveis antes do passo {exc.step_id}: {columns}",
            "Nada foi gravado.",
        )

    _write(result, destino, formato)
    typer.echo(f"{result.height} linhas, {result.width} colunas -> {destino}")


@app.command()
def schema() -> None:
    """Imprime o JSON Schema da receita (wolfz schema > recipe.schema.json)."""
    # ASCII puro: redirecionar para arquivo no Windows não depende do encoding do console.
    typer.echo(json.dumps(recipe_json_schema(), indent=2, sort_keys=True))

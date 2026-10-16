"""CLI ``wolfz``: argumentos, saída no terminal e códigos de retorno.

Sem regra de negócio; os comandos chamam o núcleo (``wolfz.core``). ``run``
e ``inspect`` entram em F0.H.
"""

from __future__ import annotations

import json

import typer

from wolfz import __version__
from wolfz.core.recipe import recipe_json_schema

app = typer.Typer(
    name="wolfz",
    help="Limpeza de planilhas brasileiras com receitas reproduzíveis.",
    no_args_is_help=True,
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


@app.command()
def schema() -> None:
    """Imprime o JSON Schema da receita (wolfz schema > recipe.schema.json)."""
    # ASCII puro: redirecionar para arquivo no Windows não depende do encoding do console.
    typer.echo(json.dumps(recipe_json_schema(), indent=2, sort_keys=True))

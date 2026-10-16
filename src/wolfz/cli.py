"""CLI ``wolfz``: argumentos, saída no terminal e códigos de retorno.

Sem regra de negócio; os comandos chamam o núcleo (``wolfz.core``). Por
enquanto só ``--version``: ``run``, ``inspect`` e ``schema`` entram em F0.H.
"""

from __future__ import annotations

import typer

from wolfz import __version__

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

"""Notas do GitHub Release tiradas do ``CHANGELOG.md`` (FH.E1).

Imprime a seção ``## [X.Y.Z]`` da versão pedida, sem o título, e o comando de
instalação. Versão de teste (``1.0.0rc1``, ``1.0.0b1``) que ainda não tem
seção própria usa a ``## [Não publicado]``. Versão final sem seção é erro:
publicar sem notas não pode passar em silêncio::

    uv run python scripts/notas_da_versao.py 1.0.0 > notas.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
REPOSITORIO = "https://github.com/RafaelGomide/WolfzBR"
PRE_RELEASE = re.compile(r"\d+\.\d+\.\d+(a|b|rc)\d+")


def secao(texto: str, titulo: str) -> str | None:
    """Corpo da seção ``## [titulo]``, até a próxima ``## `` ou os links do fim."""
    m = re.search(rf"^## \[{re.escape(titulo)}\][^\n]*\n(.*?)(?=^## |^\[[^\]]+\]: )", texto, re.M | re.S)
    return m[1].strip() if m else None


def notas(versao: str, texto: str | None = None) -> str:
    texto = texto if texto is not None else CHANGELOG.read_text(encoding="utf-8")
    corpo = secao(texto, versao)
    pre = PRE_RELEASE.fullmatch(versao) is not None
    if corpo is None and pre:
        corpo = secao(texto, "Não publicado")
    if not corpo:
        raise SystemExit(f"CHANGELOG.md não tem a seção ## [{versao}]")
    # Link relativo do CHANGELOG (docs/receita.md) não funciona na página do
    # Release: aponta para o arquivo na tag.
    corpo = re.sub(
        r"\]\((?!https?://|#)([^)]+)\)", lambda m: f"]({REPOSITORIO}/blob/v{versao}/{m[1]})", corpo
    )
    instalar = f'pipx install "wolfzbr=={versao}"' if pre else "pipx install wolfzbr"
    aviso = "Versão de teste: não use em produção.\n\n" if pre else ""
    return f"{aviso}{corpo}\n\n## Instalação\n\n```bash\n{instalar}\n```\n"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("uso: notas_da_versao.py <versão, sem o v>", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(notas(args[0].removeprefix("v")), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

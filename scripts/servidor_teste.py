"""Sobe a API local para desenvolvimento da interface e para o Playwright.

Não é o ``wolfz ui`` (F1.J1): aqui a porta, o workspace e o token podem ser
fixados, o que só faz sentido em teste. O token vem da variável
``WOLFZ_E2E_TOKEN`` (nunca da linha de comando, para não ficar no
histórico); sem ela, é gerado um novo, como no uso normal::

    python scripts/servidor_teste.py --port 8799 --home /tmp/wolfz-e2e
    WOLFZ_DEV=1 python scripts/servidor_teste.py --port 8799   # com o Vite

Imprime a URL de abertura (com o token no fragmento) e fica no ar até
Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from wolfz.api.app import create_app
from wolfz.api.security import Settings, novo_token
from wolfz.api.server import HOST
from wolfz.core.workspace import Workspace


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--home", type=Path, help="workspace (padrão: WOLFZ_HOME ou ~/.wolfz)")
    args = parser.parse_args(argv)
    settings = Settings(
        workspace=Workspace(args.home) if args.home else Workspace(),
        port=args.port,
        token=os.environ.get("WOLFZ_E2E_TOKEN") or novo_token(),
        dev=os.environ.get("WOLFZ_DEV") == "1",
    )
    print(f"WolfzBR em http://{HOST}:{settings.port}/#token={settings.token}", flush=True)
    uvicorn.run(create_app(settings), host=HOST, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()

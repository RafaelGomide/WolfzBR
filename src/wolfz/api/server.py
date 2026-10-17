"""Subir a API local: porta livre em 127.0.0.1, token novo e uvicorn."""

from __future__ import annotations

import os
import socket

import uvicorn

from wolfz.api.app import create_app
from wolfz.api.security import Settings
from wolfz.core.workspace import Workspace

HOST = "127.0.0.1"  # nunca 0.0.0.0 (§11.1)


def porta_livre() -> int:
    """Porta livre escolhida pelo sistema, só no loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def criar_servidor(
    workspace: Workspace | None = None, port: int = 0, dev: bool | None = None
) -> tuple[uvicorn.Server, str]:
    """Servidor pronto para ``run()`` e o endereço que abre a interface.

    O token vai no fragmento da URL (``#token=``): o navegador não o envia ao
    servidor, então ele não aparece em log de acesso nem em histórico de
    requisição."""
    dev = os.environ.get("WOLFZ_DEV") == "1" if dev is None else dev
    settings = Settings(workspace=workspace or Workspace(), port=port or porta_livre(), dev=dev)
    app = create_app(settings)
    config = uvicorn.Config(app, host=HOST, port=settings.port, log_level="warning", access_log=False)
    return uvicorn.Server(config), f"http://{HOST}:{settings.port}/#token={settings.token}"

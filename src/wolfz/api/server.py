"""Subir a API local: porta livre em 127.0.0.1, token novo e uvicorn."""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from collections.abc import Callable

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


def porta_disponivel(porta: int) -> bool:
    """A porta está livre no loopback?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, porta))
        except OSError:
            return False
    return True


def abrir_quando_pronto(
    servidor: uvicorn.Server,
    url: str,
    abrir: Callable[[str], object] | None = None,
    espera: float = 15.0,
) -> threading.Thread:
    """Abre ``url`` no navegador assim que o servidor aceitar conexões (numa
    thread, porque ``servidor.run()`` ocupa a principal). Se ele não subir a
    tempo, não abre nada: o endereço já foi impresso no terminal."""

    def esperar() -> None:
        fim = time.monotonic() + espera
        while not servidor.started and not servidor.should_exit and time.monotonic() < fim:
            time.sleep(0.05)
        if servidor.started:
            (abrir or webbrowser.open)(url)

    thread = threading.Thread(target=esperar, name="wolfz-navegador", daemon=True)
    thread.start()
    return thread


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

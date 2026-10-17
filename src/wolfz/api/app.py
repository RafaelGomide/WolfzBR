"""Aplicação FastAPI: rotas em ``/api``, a SPA compilada na raiz."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import wolfz.ops  # noqa: F401  (registra o catálogo de operações)
from wolfz import __version__
from wolfz.api import problems, security
from wolfz.api.projetos import Projetos
from wolfz.api.rotas import router
from wolfz.api.security import Settings

_SEM_INTERFACE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>WolfzBR</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto">
<h1>WolfzBR</h1>
<p>A API está no ar, mas a interface ainda não foi compilada neste pacote.</p>
</body></html>
"""


def create_app(settings: Settings) -> FastAPI:
    projetos = Projetos(settings.workspace, settings.port)

    @asynccontextmanager
    async def ciclo(app: FastAPI) -> AsyncIterator[None]:
        yield
        projetos.fechar_todos()  # libera os locks ao encerrar

    app = FastAPI(
        title="WolfzBR Local API",
        version=__version__,
        lifespan=ciclo,
        docs_url="/api/docs" if settings.dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.dev else None,
    )
    app.state.settings = settings
    app.state.projetos = projetos
    problems.install(app)
    security.install(app, settings)
    app.include_router(router(settings, projetos))

    if (settings.static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")
    else:

        @app.get("/", include_in_schema=False)
        def sem_interface() -> HTMLResponse:
            return HTMLResponse(_SEM_INTERFACE)

    return app

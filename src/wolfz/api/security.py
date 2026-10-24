"""Segurança da API local (§11 do design).

O modelo de ameaça é outro software na mesma máquina, em especial uma
página web maliciosa aberta em outra aba tentando ler dados pela API local.
As defesas, cada uma com teste:

- bind só em ``127.0.0.1`` e porta livre aleatória (``server.py``);
- token de sessão ``secrets.token_urlsafe(32)``, novo a cada start, nunca
  gravado em disco nem em log, exigido em toda chamada a ``/api`` no header
  ``Authorization: Bearer``;
- header ``Host`` só ``127.0.0.1:<porta>`` ou ``localhost:<porta>``: barra o
  DNS rebinding, em que um domínio externo passa a resolver para o loopback;
- sem CORS; com ``WOLFZ_DEV=1``, só a origem do servidor do Vite;
- upload acima do limite recusado pelo ``Content-Length``, antes de ler o
  corpo (e de novo durante a cópia, para quem mente o tamanho).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from wolfz.api.problems import problem_response
from wolfz.core.ingest import Limits
from wolfz.core.ingest.limits import DEFAULT_LIMITS, too_large_message
from wolfz.core.workspace import Workspace

ORIGENS_VITE = ("http://localhost:5173", "http://127.0.0.1:5173")
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
# Folga para o envelope multipart em volta do arquivo.
FOLGA_MULTIPART = 64 * 1024


def novo_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class Settings:
    workspace: Workspace
    port: int
    token: str = field(default_factory=novo_token, repr=False)
    dev: bool = False
    limits: Limits = DEFAULT_LIMITS
    static_dir: Path = STATIC_DIR

    @property
    def hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


def _token_valido(request: Request, token: str) -> bool:
    cabecalho = request.headers.get("authorization", "")
    esquema, _, valor = cabecalho.partition(" ")
    return esquema.lower() == "bearer" and secrets.compare_digest(valor.strip().encode(), token.encode())


def install(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def seguranca(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.headers.get("host", "") not in settings.hosts:
            return problem_response(
                request, 403, "Host não permitido", "A API do WolfzBR só atende em 127.0.0.1 e localhost."
            )
        if request.url.path.startswith("/api"):
            if not _token_valido(request, settings.token):
                resposta = problem_response(
                    request,
                    401,
                    "Token de sessão ausente ou inválido",
                    "Abra o WolfzBR pelo endereço que o `wolfz ui` mostrou: ele leva o token da sessão.",
                )
                resposta.headers["WWW-Authenticate"] = "Bearer"
                return resposta
            tamanho = request.headers.get("content-length")
            limite = settings.limits.max_file_bytes + FOLGA_MULTIPART
            if request.method == "POST" and tamanho and tamanho.isdigit() and int(tamanho) > limite:
                return problem_response(
                    request,
                    413,
                    "Arquivo grande demais",
                    # O Content-Length inclui o envelope do multipart: o tamanho é aproximado.
                    too_large_message(settings.limits.max_file_bytes, int(tamanho)),
                    code="file_too_large",
                )
        return await call_next(request)

    if settings.dev:
        # Adicionado depois: fica por fora e responde o preflight antes da checagem de token.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(ORIGENS_VITE),
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "If-Match"],
            expose_headers=["ETag"],
        )

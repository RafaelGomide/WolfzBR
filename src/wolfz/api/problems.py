"""Erros no formato Problem Details (RFC 9457, §5.4 do design).

Toda resposta de erro da API tem o mesmo corpo: ``type``, ``title``,
``status``, ``detail`` e ``instance``, mais ``step_id`` e
``available_columns`` quando o erro é de um passo da receita. É o mesmo
texto que a CLI mostra, porque vem das mesmas exceções do núcleo.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from wolfz.core.engine import StepError
from wolfz.core.ingest import IngestError
from wolfz.core.recipe import RecipeError, RecipeTooNewError
from wolfz.core.registro import resumo_da_falha

PROBLEM_JSON = "application/problem+json"
log = logging.getLogger("wolfz.api")

_TITULOS = {
    400: "Requisição inválida",
    401: "Token de sessão ausente ou inválido",
    403: "Acesso negado",
    404: "Não encontrado",
    405: "Método não permitido",
    409: "Conflito",
    413: "Arquivo grande demais",
    415: "Formato não suportado",
    422: "Dados inválidos",
    423: "Projeto aberto em outra instância",
    428: "Cabeçalho If-Match obrigatório",
    500: "Erro interno",
}


class Problem(Exception):
    """Erro da API com status e texto para o usuário."""

    def __init__(self, status: int, detail: str, title: str | None = None, **extra: Any):
        self.status = status
        self.detail = detail
        self.title = title or _TITULOS.get(status, "Erro")
        self.extra = extra
        super().__init__(detail)


def problem_response(request: Request, status: int, title: str, detail: str, **extra: Any) -> JSONResponse:
    corpo = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        **extra,
    }
    return JSONResponse(corpo, status_code=status, media_type=PROBLEM_JSON)


def install(app: FastAPI) -> None:
    """Registra os tradutores de exceção da aplicação."""

    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc.status, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(StepError)
    async def _step(request: Request, exc: StepError) -> JSONResponse:
        corpo = exc.to_problem(status=422, instance=request.url.path)
        return JSONResponse(corpo, status_code=422, media_type=PROBLEM_JSON)

    @app.exception_handler(IngestError)
    async def _ingest(request: Request, exc: IngestError) -> JSONResponse:
        corpo = exc.to_problem(instance=request.url.path)
        return JSONResponse(corpo, status_code=exc.status, media_type=PROBLEM_JSON)

    @app.exception_handler(RecipeError)
    async def _recipe(request: Request, exc: RecipeError) -> JSONResponse:
        detalhe = "; ".join(exc.errors) if exc.errors else str(exc)
        if isinstance(exc, RecipeTooNewError):
            return problem_response(
                request,
                422,
                "Receita de uma versão mais nova do WolfzBR",
                detalhe,
                errors=exc.errors,
                recipe_version=exc.version,
                supported_version=exc.supported,
            )
        return problem_response(request, 422, "Receita inválida", detalhe, errors=exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        erros = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return problem_response(request, 422, _TITULOS[422], "; ".join(erros), errors=erros)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        titulo = _TITULOS.get(exc.status_code, "Erro")
        return problem_response(request, exc.status_code, titulo, str(exc.detail))

    # Middleware, e não exception_handler(Exception): este responde o 500 e
    # depois relança a exceção para o servidor, e o uvicorn grava o traceback
    # com a mensagem, que pode conter valor de célula (§12.1). Aqui ela para.
    @app.middleware("http")
    async def _inesperado(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            log.error("erro não tratado em %s: %s", request.url.path, resumo_da_falha(exc))
            return problem_response(request, 500, _TITULOS[500], "Erro inesperado. Veja o log do WolfzBR.")

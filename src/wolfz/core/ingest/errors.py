"""Erros de importação com mensagem para gente, não para programador.

Toda falha conhecida de leitura vira ``IngestError``, com um ``code``
estável (para a API e os testes) e um texto que diz o que aconteceu e o
que fazer. Segue o mesmo formato Problem Details de ``StepError`` (§5.4
do design), para que a interface e o terminal mostrem o mesmo texto.
"""

from __future__ import annotations

from typing import Any


class IngestError(Exception):
    """Falha ao importar um arquivo. Nenhum projeto é criado quando ela
    acontece (§10.1 do design)."""

    def __init__(self, code: str, title: str, message: str, status: int = 422):
        self.code = code
        self.title = title
        self.message = message
        self.status = status
        super().__init__(message)

    def to_problem(self, instance: str | None = None) -> dict[str, Any]:
        """Corpo de resposta no formato Problem Details (§5.4)."""
        problem: dict[str, Any] = {
            "type": "about:blank",
            "title": self.title,
            "status": self.status,
            "detail": self.message,
            "code": self.code,
        }
        if instance is not None:
            problem["instance"] = instance
        return problem


def not_found(name: str) -> IngestError:
    return IngestError("file_not_found", "Arquivo não encontrado", f"O arquivo {name} não existe.", 404)


def empty_file(name: str) -> IngestError:
    return IngestError("empty_file", "Arquivo vazio", f"O arquivo {name} está vazio (0 bytes).")


def locked(name: str) -> IngestError:
    return IngestError(
        "file_locked",
        "Arquivo em uso",
        f"Não foi possível abrir {name}: ele está em uso por outro programa, provavelmente o Excel "
        "ou a sincronização do OneDrive. Feche o arquivo e tente de novo.",
        409,
    )


def excel_lock_file(name: str) -> IngestError:
    original = name[2:]
    return IngestError(
        "excel_lock_file",
        "Arquivo temporário do Excel",
        f"{name} é o arquivo temporário que o Excel cria enquanto {original} está aberto, "
        f"não a planilha. Importe {original}.",
    )


def password_protected(name: str) -> IngestError:
    return IngestError(
        "password_protected",
        "Arquivo protegido por senha",
        f"{name} está protegido por senha. Abra no Excel, remova a senha "
        "(Arquivo > Informações > Proteger pasta de trabalho) e salve uma cópia sem senha.",
    )


def corrupted(name: str, reason: str | None = None) -> IngestError:
    detail = f" Detalhe: {reason}" if reason else ""
    return IngestError(
        "corrupted",
        "Arquivo corrompido",
        f"Não foi possível ler {name}: o arquivo parece corrompido ou incompleto. "
        f"Tente abrir no Excel e salvar de novo.{detail}",
    )


def sheet_not_found(name: str, sheet: str | int, available: list[str]) -> IngestError:
    options = ", ".join(repr(s) for s in available) or "(nenhuma)"
    return IngestError(
        "sheet_not_found",
        "Aba não encontrada",
        f"{name} não tem a aba {sheet!r}. Abas disponíveis: {options}.",
        404,
    )

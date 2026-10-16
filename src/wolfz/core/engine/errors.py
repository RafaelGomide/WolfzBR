"""Erro de execução de um passo da receita.

É a base do formato de erro padronizado (RFC 9457, Problem Details,
estendido com o passo que falhou — §5.4 do design). A API e a CLI usam
``to_problem()``, para que a interface e o ``wolfz run`` falhem com o mesmo
texto.
"""

from __future__ import annotations

import re
from typing import Any

_MISSING_COLUMN = re.compile(r'unable to find column "(.+?)"|^"(.+?)" not found')


class StepError(Exception):
    """Falha ao aplicar um passo. ``available_columns`` são as colunas que
    existiam antes do passo, para a interface sugerir a certa."""

    def __init__(
        self,
        step_id: str,
        op: str,
        message: str,
        available_columns: list[str],
        title: str = "Erro ao executar o passo",
    ):
        self.step_id = step_id
        self.op = op
        self.message = message
        self.available_columns = available_columns
        self.title = title
        super().__init__(message)

    def to_problem(self, status: int = 422, instance: str | None = None) -> dict[str, Any]:
        """Corpo de resposta no formato Problem Details (§5.4)."""
        problem: dict[str, Any] = {
            "type": "about:blank",
            "title": self.title,
            "status": status,
            "detail": self.message,
            "step_id": self.step_id,
            "op": self.op,
            "available_columns": self.available_columns,
        }
        if instance is not None:
            problem["instance"] = instance
        return problem


def missing_column(exc: Exception) -> str | None:
    """Nome da coluna em um ``ColumnNotFoundError`` do Polars, se der para
    extrair da mensagem."""
    first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if m := _MISSING_COLUMN.search(first_line):
        return m[1] or m[2]
    return None

"""Booleanos escritos em português ('Sim', 'N', 'X')."""

from __future__ import annotations

from wolfz.core.text import normalize_key

_TRUE = {"sim", "s", "x", "v", "verdadeiro", "true", "t", "1", "yes", "y", "ok"}
_FALSE = {"nao", "n", "falso", "f", "false", "0", "no"}


def parse_bool_br(value: object, empty_is_false: bool = False) -> bool | None:
    """'Sim'/'S'/'X'/'1' -> True; 'Não'/'N'/'0' -> False.

    ``empty_is_false=True`` para colunas de "marque com X", em que célula
    vazia significa não."""
    if isinstance(value, bool):
        return value
    k = normalize_key(value)
    if not k:
        return False if empty_is_false else None
    if k in _TRUE:
        return True
    if k in _FALSE:
        return False
    return None

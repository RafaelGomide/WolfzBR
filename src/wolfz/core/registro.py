"""O que pode ir para o log quando algo falha (§12.1 do design).

Mensagem de exceção de parse costuma trazer o valor que falhou ("could not
convert 'João da Silva'"), e o traceback repete a mensagem. Para o log vai
só o tipo da exceção e onde ela aconteceu: dá para achar o bug sem levar
dado do usuário junto.
"""

from __future__ import annotations

import traceback
from pathlib import Path


def resumo_da_falha(exc: BaseException) -> str:
    """'ValueError em numeros.py:142' — sem a mensagem da exceção."""
    quadros = traceback.extract_tb(exc.__traceback__)
    if not quadros:
        return type(exc).__name__
    ultimo = quadros[-1]
    return f"{type(exc).__name__} em {Path(ultimo.filename).name}:{ultimo.lineno}"

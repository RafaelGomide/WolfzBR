"""Aba que muda de nome todo mês (F2.F4).

O relatório de dezembro vem na aba ``DEZEMBRO_2025``; o de janeiro, em
``JANEIRO_2026``. A receita guarda o nome exato e, em
``source.match.sheet_name_regex``, um padrão que aceita os próximos:
``padrao_de_aba`` troca o ano e o número por ``\\d``, o mês por qualquer mês,
e mantém o resto.

O M não tem expressão regular; lá vale o ``molde_de_aba``, que compara o
nome com dígitos virando ``0`` e mês virando ``#`` (a mesma ideia do padrão
proposto). Um padrão escrito à mão pode aceitar mais do que o molde.
"""

from __future__ import annotations

import re

from wolfz.br.constants import MESES
from wolfz.core.text import normalize_key

# Do mais longo para o mais curto, para 'marco' não virar '#co' no molde.
_NOMES_DE_MES = sorted({*MESES, "março"}, key=lambda m: (-len(m), m))
# Os meses como aparecem no molde (normalizados), para o M.
MESES_DO_MOLDE = sorted({normalize_key(m) for m in _NOMES_DE_MES})
_TOKEN = re.compile(r"\d+|[^\W\d_]+|.", re.UNICODE)


# Nome que o Excel e o LibreOffice dão sozinhos: 'Plan2' não é o mês seguinte de 'Plan1'.
_NOME_PADRAO = re.compile(r"(?i)(plan|planilha|sheet|folha|tabela)\s*\d+")


def _e_mes(palavra: str) -> bool:
    return normalize_key(palavra).rstrip(".") in MESES


def padrao_de_aba(nome: str | None) -> str | None:
    """Expressão regular que aceita o nome da aba nos meses seguintes, ou
    ``None`` se o nome não tem número nem mês (não muda de um mês para o
    outro). 'Vendas 2024' -> '(?i)Vendas\\ \\d{4}'."""
    if not nome or _NOME_PADRAO.fullmatch(nome.strip()):
        return None
    partes, variavel = [], False
    for token in _TOKEN.findall(nome):
        if token.isdigit():
            partes.append(rf"\d{{{len(token)}}}" if len(token) in (2, 4) else r"\d+")
            variavel = True
        elif token.isalpha() and _e_mes(token):
            partes.append("(?:" + "|".join(re.escape(m) for m in _NOMES_DE_MES) + r")\.?")
            variavel = True
        else:
            partes.append(re.escape(token))
    return "(?i)" + "".join(partes) if variavel else None


def molde_de_aba(nome: str) -> str:
    """O nome sem o que muda todo mês: minúsculo, sem acento, mês vira '#' e
    cada dígito vira '0'. 'DEZEMBRO_2025' e 'Janeiro_2026' dão '#_0000'."""
    k = normalize_key(nome)
    for mes in _NOMES_DE_MES:
        k = re.sub(rf"(?<![a-z]){re.escape(normalize_key(mes))}(?![a-z])", "#", k)
    return re.sub(r"\d", "0", k)

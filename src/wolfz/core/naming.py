"""Nomes de coluna: snake_case e desduplicação."""

from __future__ import annotations

import re
from collections import Counter

from wolfz.core.text import normalize_spaces, remove_accents


def to_snake_case(name: str) -> str:
    """'Valor de Venda (R$)' -> 'valor_de_venda_r'; 'Nº Pedido' -> 'n_pedido'.

    Remove BOM e acentos, troca qualquer separador por '_'. Nome que começa
    com dígito ganha prefixo 'c_' para ser identificador válido em Python,
    M e SQL. Nome vazio vira 'coluna'."""
    name = normalize_spaces(str(name))
    name = name.replace("º", "").replace("ª", "").replace("%", " pct ")
    name = remove_accents(name).lower()
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    if not name:
        return "coluna"
    return f"c_{name}" if name[0].isdigit() else name


def dedupe_names(names: list[str]) -> list[str]:
    """['valor', 'valor', 'data'] -> ['valor', 'valor_2', 'data'].

    Relatórios com cabeçalho multinível costumam repetir o mesmo rótulo
    em várias colunas ("Valor" sob cada mês)."""
    seen: Counter[str] = Counter()
    result = []
    taken = set(names)
    for name in names:
        seen[name] += 1
        if seen[name] == 1:
            result.append(name)
            continue
        n = seen[name]
        while f"{name}_{n}" in taken:
            n += 1
        new = f"{name}_{n}"
        taken.add(new)
        result.append(new)
    return result

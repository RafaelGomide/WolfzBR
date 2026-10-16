"""Exportação da receita como Power Query M.

Versão mínima da Fase 0: a receita vira uma função ``(Fonte as table) as
table => ...``, que recebe a tabela já lida. Ler o arquivo de origem
(``Excel.Workbook``, ``Csv.Document``) e montar o ``.pq`` final entra em F2.

Nomes de coluna e textos nunca são concatenados direto no código: passam
por ``m_text``, que escapa aspas e caracteres de controle (§11.5).
"""

from __future__ import annotations

from collections.abc import Iterable

from wolfz.core.recipe import Recipe

_ESCAPES = {"\r": "#(cr)", "\n": "#(lf)", "\t": "#(tab)"}


def m_text(value: str) -> str:
    """Literal de texto M: '"Valor"' com aspas dobradas e controles
    escapados. '#(' também é escapado, porque abre uma sequência de escape."""
    out = []
    for i, ch in enumerate(value):
        if ch == '"':
            out.append('""')
        elif ch == "#" and value[i + 1 : i + 2] == "(":
            out.append("#(#)")
        elif ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"#({ord(ch):04X})")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def m_list(items: Iterable[str]) -> str:
    """Lista M de textos: {"a", "b"}."""
    return "{" + ", ".join(m_text(i) for i in items) + "}"


def m_field(column: str, row: str = "_") -> str:
    """Valor da coluna na linha. ``Record.Field`` aceita qualquer nome de
    coluna sem precisar escapar identificador."""
    return f"Record.Field({row}, {m_text(column)})"


def recipe_to_m(recipe: Recipe) -> str:
    """Função M que aplica todos os passos da receita a uma tabela."""
    if not recipe.steps:
        return "(Fonte as table) as table => Fonte\n"
    helpers: dict[str, str] = {}
    for step in recipe.steps:
        for name, definition in step.m_helpers.items():
            if helpers.setdefault(name, definition) != definition:
                raise ValueError(f"duas definições diferentes para a função M {name!r}")

    lines = [f"{name} = {definition.strip()}" for name, definition in helpers.items()]
    prev = "Fonte"
    for step in recipe.steps:
        lines.append(f"// {step.id}: {step.op}\n" + step.to_m(prev, step.id))
        prev = step.id

    body = ",\n".join(lines)
    indented = "\n".join(f"        {line}" if line else "" for line in body.splitlines())
    return f"(Fonte as table) as table =>\n    let\n{indented}\n    in\n        {prev}\n"

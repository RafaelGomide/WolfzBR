"""Exportação da receita como script Python autônomo.

O script só depende de Polars: as funções de ``wolfz.br`` que as operações
usam são copiadas para dentro dele, junto com as constantes e funções de
que dependem. Assim ele roda numa máquina sem o WolfzBR, e o teste de
equivalência garante que dá o mesmo resultado que o motor (§13.5).

Versão mínima da Fase 0: só a função ``transform`` e uma leitura simples de
CSV. A exportação completa (leitura de Excel, encoding, saída) entra em F2.
"""

from __future__ import annotations

import inspect
import re
import textwrap
import types
from collections.abc import Callable, Iterable
from typing import Any

from wolfz import __version__
from wolfz.core.recipe import Recipe

_HEADER = '''\
"""Script gerado pelo WolfzBR {version} a partir da receita {name!r}.

Não depende do WolfzBR, só de Polars. Uso:
    python <este_script.py> entrada.csv saida.csv
"""

from __future__ import annotations

{imports}
'''

_MAIN = """

if __name__ == "__main__":
    import sys

    entrada, saida = sys.argv[1:3]
    df = pl.read_csv(entrada, infer_schema=False)
    transform(df.lazy()).collect().write_csv(saida)
"""


def _code_names(code: types.CodeType) -> set[str]:
    """Nomes globais usados pela função, incluindo os de lambdas e
    compreensões internas."""
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _code_names(const)
    return names


def _literal(name: str, value: Any) -> str:
    """Constante como código Python, com saída determinística (conjuntos
    ordenados, para o script não mudar de uma execução para outra)."""
    if isinstance(value, re.Pattern):
        flags = value.flags & ~re.UNICODE
        return f"{name} = re.compile({value.pattern!r}{f', {flags}' if flags else ''})"
    if isinstance(value, frozenset | set):
        items = "{" + ", ".join(repr(v) for v in sorted(value)) + "}"
        if isinstance(value, frozenset):
            return f"{name} = frozenset({items})"
        return f"{name} = {items}" if value else f"{name} = set()"
    if isinstance(value, dict | list | tuple | str | int | float | bool) or value is None:
        return f"{name} = {value!r}"
    raise TypeError(f"não sei copiar a constante {name} ({type(value).__name__}) para o script")


def bundle(functions: Iterable[Callable[..., Any]]) -> tuple[list[str], str]:
    """Código-fonte das funções e de tudo de que dependem dentro do
    WolfzBR. Devolve (linhas de import, código)."""
    imports: set[str] = set()
    constants: dict[str, str] = {}
    sources: dict[str, str] = {}
    seen: dict[str, Any] = {}

    def visit(fn: Callable[..., Any]) -> None:
        name = fn.__name__
        if name in sources:
            if seen[name] is not fn:
                raise ValueError(f"duas funções diferentes chamadas {name!r} no script")
            return
        seen[name] = fn
        sources[name] = textwrap.dedent(inspect.getsource(fn))
        for ref in sorted(_code_names(fn.__code__)):
            if ref not in fn.__globals__:
                continue  # builtin ou atributo
            value = fn.__globals__[ref]
            if isinstance(value, types.ModuleType):
                imports.add(f"import {value.__name__}")
            elif isinstance(value, types.FunctionType) and value.__module__.startswith("wolfz."):
                visit(value)
            elif callable(value):
                # classe ou função de outra biblioteca (ex.: datetime.date)
                imports.add(f"from {value.__module__} import {value.__name__}")
            else:
                code = _literal(ref, value)
                if constants.setdefault(ref, code) != code:
                    raise ValueError(f"duas constantes diferentes chamadas {ref!r} no script")

    for fn in functions:
        visit(fn)
    if any("re.compile(" in c for c in constants.values()):
        imports.add("import re")
    parts = [*constants.values(), *sources.values()]
    return sorted(imports), "\n\n".join(p.rstrip() for p in parts)


def recipe_to_python(recipe: Recipe) -> str:
    """Script Python autônomo com a função ``transform(lf)`` que aplica
    todos os passos da receita."""
    helpers: list[Callable[..., Any]] = []
    for step in recipe.steps:
        helpers.extend(h for h in step.python_helpers if h not in helpers)
    stdlib, helper_code = bundle(helpers)
    # stdlib primeiro (import, depois from), Polars por último
    stdlib = sorted(stdlib, key=lambda line: (line.startswith("from "), line))
    imports = [*stdlib, "", "import polars as pl"] if stdlib else ["import polars as pl"]

    body = []
    for step in recipe.steps:
        body.append(f"# {step.id}: {step.op}")
        body.extend(step.to_python().splitlines())
    body.append("return lf")

    parts = [_HEADER.format(version=__version__, name=recipe.name, imports="\n".join(imports))]
    if helper_code:
        parts.append("\n# Funções copiadas de wolfz.br\n\n" + helper_code + "\n")
    parts.append(
        "\ndef transform(lf: pl.LazyFrame) -> pl.LazyFrame:\n"
        + "\n".join(f"    {line}" if line else "" for line in body)
        + "\n"
    )
    return "\n".join(parts) + _MAIN

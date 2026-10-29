"""Exportação da receita como script Python autônomo.

O script só depende de Polars: as funções de ``wolfz.br`` que as operações
usam são copiadas para dentro dele, junto com as constantes e funções de
que dependem. Assim ele roda numa máquina sem o WolfzBR, e o teste de
equivalência garante que dá o mesmo resultado que o motor (§13.5).

A leitura da entrada (``wolfz.export.leitura``) também vai copiada: o
script lê planilha e CSV do mesmo jeito que ``wolfz.run``.
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
import textwrap
import types
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from wolfz import __version__
from wolfz.core.recipe import Recipe
from wolfz.export.leitura import empilhar_abas, ler_abas, ler_entrada

_HEADER = '''"""Receita "{name}", exportada pelo WolfzBR {version} em {date}.

Script autônomo: não depende do WolfzBR, só de Polars (e, para ler
planilha, de fastexcel e python-calamine). Uso:

    python <este_script.py> entrada.xlsx saida.csv

Lê a entrada como o WolfzBR lê (planilha como grade de texto, CSV com
encoding e separador detectados), aplica os passos da receita e grava a
saída em .csv ou .parquet. A função ``transform`` também pode ser
importada e aplicada a um ``LazyFrame`` já lido.
"""

from __future__ import annotations

{imports}
'''

_MAIN = """

def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"uso: python {sys.argv[0]} entrada saida.csv")
    entrada, saida = sys.argv[1:3]
    if JUNTAR_ABAS:
        partes = [(nome, transform(grade.lazy()).collect()) for nome, grade in ler_abas(entrada, ABAS_REGEX)]
        df = empilhar_abas(partes, COLUNA_ABA)
    else:
        df = transform(ler_entrada(entrada, ABA, ABA_REGEX, GRADE).lazy()).collect()
    if saida.lower().endswith(".parquet"):
        df.write_parquet(saida)
    else:
        df.write_csv(saida, datetime_format="%Y-%m-%d %H:%M:%S%.f")  # como o CSV da WolfzBR


if __name__ == "__main__":
    main()
"""

# Passos que trabalham sobre a grade crua: se a receita começa por um deles,
# o CSV é lido sem cabeçalho (a mesma regra de ``wolfz.run``).
_PASSOS_DE_GRADE = {"select_range", "header_rows"}


def _docstring(text: str) -> str:
    """Texto seguro dentro do docstring do script: sem quebra de linha,
    barra invertida nem aspas que fechem a string."""
    limpo = " ".join("".join(" " if not c.isprintable() else c for c in text).split())
    return limpo.replace("\\", "\\\\").replace('"', '\\"')


def _code_names(code: types.CodeType) -> set[str]:
    """Nomes globais usados pela função, incluindo os de lambdas e
    compreensões internas."""
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _code_names(const)
    return names


def _annotation_names(fn: Callable[..., Any]) -> set[str]:
    """Nomes usados nas anotações: com ``from __future__ import annotations``
    elas são texto e não aparecem no bytecode."""
    names: set[str] = set()
    for annotation in fn.__annotations__.values():
        if isinstance(annotation, str):
            tree = ast.parse(annotation, mode="eval")
            names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names


def _public_module(value: Any) -> str:
    """Módulo público de onde importar ``value`` (``pathlib`` e não
    ``pathlib._local``)."""
    parts = value.__module__.split(".")
    for i in range(1, len(parts) + 1):
        module = ".".join(parts[:i])
        if getattr(sys.modules.get(module), value.__name__, None) is value:
            return module
    return value.__module__


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
    if type(value) is date:
        return f"{name} = date({value.year}, {value.month}, {value.day})"
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
        for ref in sorted(_code_names(fn.__code__) | _annotation_names(fn)):
            if ref not in fn.__globals__:
                continue  # builtin ou atributo
            value = fn.__globals__[ref]
            if isinstance(value, types.ModuleType):
                if value.__name__ != "polars":  # o script sempre importa polars as pl
                    imports.add(f"import {value.__name__}")
            elif isinstance(value, types.FunctionType) and value.__module__.startswith("wolfz."):
                visit(value)
            elif callable(value):
                # classe ou função de outra biblioteca (ex.: datetime.date)
                imports.add(f"from {_public_module(value)} import {value.__name__}")
            else:
                code = _literal(ref, value)
                if constants.setdefault(ref, code) != code:
                    raise ValueError(f"duas constantes diferentes chamadas {ref!r} no script")

    for fn in functions:
        visit(fn)
    if any("re.compile(" in c for c in constants.values()):
        imports.add("import re")
    if any(" = date(" in c for c in constants.values()):
        imports.add("from datetime import date")
    code = "\n".join(c.rstrip() for c in constants.values())
    if sources:
        code += "\n\n\n" + "\n\n\n".join(src.rstrip() for src in sources.values())
    return sorted(imports), code


def recipe_to_python(recipe: Recipe, today: date | None = None) -> str:
    """Script Python autônomo: ``transform(lf)`` aplica todos os passos
    ativos da receita, e ``main`` lê a entrada e grava a saída."""
    steps = recipe.active_steps
    helpers: list[Callable[..., Any]] = [ler_entrada, ler_abas, empilhar_abas]
    for step in steps:
        helpers.extend(h for h in step.python_helpers if h not in helpers)
    stdlib, helper_code = bundle(helpers)
    imports = [*stdlib, "import sys", "", "import polars as pl"]

    match = recipe.source.match
    grade = bool(steps) and steps[0].op in _PASSOS_DE_GRADE
    constants = [
        "# Como ler a entrada (da receita)",
        f"ABA = {recipe.source.sheet!r}",
        f"ABA_REGEX = {match.sheet_name_regex if match else None!r}",
        f"GRADE = {grade!r}  # CSV lido como grade (A, B, ...) e não com cabeçalho",
    ]
    combine = recipe.source.combine_sheets
    # Os nomes das abas são lidos do arquivo na hora de rodar; no script só
    # entram a regex e o nome da coluna, pelo repr (R8).
    constants += [
        "",
        "# Juntar abas (source.combine_sheets): a receita roda em cada aba e as tabelas são empilhadas",
        f"JUNTAR_ABAS = {combine is not None!r}",
        f"ABAS_REGEX = {combine.sheets_regex if combine else None!r}",
        f"COLUNA_ABA = {combine.origin_col if combine else None!r}",
    ]
    extras = {k: v for step in steps for k, v in step.python_constants.items()}
    if extras:
        constants += [
            "",
            "# Arquivos exportados junto com o script",
            *(f"{k} = {v}" for k, v in extras.items()),
        ]

    body = []
    for step in steps:
        body.append(f"# {step.id}: {step.op}")
        body.extend(step.to_python().splitlines())
    body.append("return lf")

    header = _HEADER.format(
        version=__version__,
        name=_docstring(recipe.name),
        date=(today or date.today()).isoformat(),
        imports="\n".join(imports),
    )
    parts = [header, "\n".join(constants) + "\n"]
    parts.append("\n# Funções copiadas do WolfzBR\n\n" + helper_code + "\n")
    parts.append(
        "\ndef transform(lf: pl.LazyFrame) -> pl.LazyFrame:\n"
        + '    """Aplica os passos da receita, em ordem."""\n'
        + "\n".join(f"    {line}" if line else "" for line in body)
        + "\n"
    )
    return ruff_format("\n".join(parts) + _MAIN)


def ruff_format(code: str) -> str:
    """Passa o script pelo ruff, com a configuração padrão: ordena os
    imports e formata. O script é código que o usuário vai ler (F2.B3)."""
    from ruff.__main__ import find_ruff_bin

    ruff = find_ruff_bin()
    for args in (["check", "--select", "I", "--fix"], ["format"]):
        result = subprocess.run(
            [ruff, *args, "--isolated", "--quiet", "--stdin-filename", "script.py", "-"],
            input=code.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            erro = result.stderr.decode("utf-8", "replace") or result.stdout.decode("utf-8", "replace")
            raise RuntimeError(f"ruff recusou o script exportado: {erro.strip()}")
        code = result.stdout.decode("utf-8")
    return code

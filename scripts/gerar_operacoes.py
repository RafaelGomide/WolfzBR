"""Gera ``docs/operacoes.md`` a partir do catálogo de operações (FH.D3).

Para cada operação registrada: o nome que a interface mostra
(``frontend/src/textos.ts``), a descrição (docstring da classe), os
parâmetros (JSON Schema do passo), cada exemplo de ``examples`` como tabela
antes e depois, calculada pelo motor e não copiada do esperado, e a
tradução em Power Query M do primeiro exemplo. O arquivo nunca é editado à
mão: mudou uma operação, rode de novo. O teste ``tests/test_docs.py``
falha se ele estiver desatualizado::

    uv run python scripts/gerar_operacoes.py            # grava
    uv run python scripts/gerar_operacoes.py --check    # só confere (CI)
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.recipe import CURRENT_VERSION, Op, registered_ops

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "docs" / "operacoes.md"
TEXTOS = RAIZ / "frontend" / "src" / "textos.ts"

# Módulo de wolfz.ops -> seção do documento, na ordem do fluxo de limpeza.
GRUPOS = {
    "estrutura": "Estrutura da tabela",
    "colunas": "Colunas",
    "linhas": "Linhas",
    "texto": "Texto",
    "br": "Padrões brasileiros",
    "municipio": "Padrões brasileiros",
    "verificacao": "Verificações",
}
MAX_LINHAS = 8
CAMPOS_FIXOS = {"id", "op", "enabled"}
LISTAS_DE_COLUNAS = {"cols", "by", "index", "into", "names"}


def rotulos(bloco: str) -> dict[str, str]:
    """Rótulos de ``textos.ts`` (``ops`` ou ``params``): o nome que a interface mostra."""
    texto = TEXTOS.read_text(encoding="utf-8")
    m = re.search(rf"^  {bloco}: \{{\n(.*?)^  \}}", texto, flags=re.MULTILINE | re.DOTALL)
    if m is None:
        raise SystemExit(f"bloco {bloco!r} não encontrado em {TEXTOS}")
    return dict(re.findall(r'^\s+(\w+): "((?:[^"\\]|\\.)*)",?$', m[1], flags=re.MULTILINE))


def _tipo(nome: str, schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return "um de: " + ", ".join(f"`{json.dumps(v, ensure_ascii=False)}`" for v in schema["enum"])
    if "const" in schema:
        return f"`{json.dumps(schema['const'], ensure_ascii=False)}`"
    if "anyOf" in schema:
        partes = [_tipo(nome, s) for s in schema["anyOf"] if s.get("type") != "null"]
        return " ou ".join(dict.fromkeys(partes))
    tipo = schema.get("type")
    if tipo == "array":
        if nome in LISTAS_DE_COLUNAS:
            return "lista de colunas"
        return f"lista de ({_tipo(nome, schema.get('items', {}))})"
    if tipo == "object":
        valores = schema.get("additionalProperties")
        if isinstance(valores, dict) and valores:
            return f"mapa de texto para ({_tipo(nome, valores)})"
        return "mapa"
    nomes = {"string": "texto", "integer": "inteiro", "number": "número", "boolean": "sim/não"}
    if tipo == "string" and nome.endswith("col"):
        return "coluna"
    base = nomes.get(tipo, "valor")
    limites = [f"mín. {schema['minimum']}"] if "minimum" in schema else []
    limites += [f"máx. {schema['maximum']}"] if "maximum" in schema else []
    return base + (f" ({', '.join(limites)})" if limites else "")


def _parametros(cls: type[Op], params: dict[str, str]) -> list[str]:
    schema = cls.model_json_schema()
    obrigatorios = set(schema.get("required", []))
    linhas = []
    for nome, prop in schema["properties"].items():
        if nome in CAMPOS_FIXOS:
            continue
        if nome in obrigatorios:
            padrao = "obrigatório"
        else:
            # Do modelo, e não do schema: default_factory ({}) não vai para o schema.
            valor = cls.model_fields[nome].get_default(call_default_factory=True)
            padrao = f"`{json.dumps(valor, ensure_ascii=False)}`"
        descricao = prop.get("description") or params.get(nome, "")
        linhas.append(f"| `{nome}` | {_tipo(nome, prop)} | {padrao} | {_celula_texto(descricao)} |")
    if not linhas:
        return ["Sem parâmetros."]
    return ["| Parâmetro | Tipo | Padrão | Descrição |", "|---|---|---|---|", *linhas]


def _celula_texto(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def _valor(v: object) -> str:
    if v is None:
        return "*nulo*"
    if isinstance(v, bool):
        return "verdadeiro" if v else "falso"
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        if not v:
            return '`""`'
        visivel = v if v.isprintable() else json.dumps(v, ensure_ascii=True)[1:-1]
        # Espaço no começo ou no fim fica visível: é justamente o que trim tira.
        inicio = len(visivel) - len(visivel.lstrip(" "))
        fim = len(visivel) - len(visivel.rstrip(" "))
        visivel = "␠" * inicio + visivel.strip(" ") + "␠" * fim
        return "`" + visivel.replace("|", "\\|").replace("`", "'") + "`"
    return f"`{v}`"


def _tabela(df: pl.DataFrame) -> list[str]:
    if df.width == 0:
        return ["*(tabela sem colunas)*"]
    linhas = [
        "| " + " | ".join(_celula_texto(c) or "*(sem nome)*" for c in df.columns) + " |",
        "|" + "---|" * df.width,
    ]
    for linha in df.head(MAX_LINHAS).iter_rows():
        linhas.append("| " + " | ".join(_valor(v) for v in linha) + " |")
    if df.height > MAX_LINHAS:
        linhas.append(f"\n*… mais {df.height - MAX_LINHAS} linhas.*")
    if df.height == 0:
        linhas.append("\n*(nenhuma linha)*")
    return linhas


def _passo(cls: type[Op], nome: str, exemplo: dict[str, Any]) -> Op:
    return cls.model_validate({"id": "s1", "op": nome, **exemplo["step"]})


def _exemplo(cls: type[Op], nome: str, i: int, exemplo: dict[str, Any]) -> list[str]:
    passo = _passo(cls, nome, exemplo)
    entrada = pl.DataFrame(exemplo["input"])
    saida = passo.to_polars(entrada.lazy()).collect()
    corpo = passo.model_dump(mode="json", exclude={"id"}, exclude_defaults=True)
    corpo = {"op": nome, **{k: v for k, v in corpo.items() if k != "op"}}
    return [
        f"**Exemplo {i}**",
        "",
        "```json",
        json.dumps(corpo, ensure_ascii=False),
        "```",
        "",
        "Antes:",
        "",
        *_tabela(entrada),
        "",
        "Depois:",
        "",
        *_tabela(saida),
        "",
    ]


def _m(cls: type[Op], nome: str) -> list[str]:
    passo = _passo(cls, nome, cls.examples[0])
    m = passo.to_m("Origem", "Passo")
    linhas = ["Em Power Query M (passo do primeiro exemplo):", "", "```m", m, "```"]
    if cls.m_helpers:
        funcoes = ", ".join(f"`{f}`" for f in sorted(cls.m_helpers))
        linhas += ["", f"Usa as funções auxiliares {funcoes}, declaradas no início da consulta exportada."]
    return linhas


def _ordem(cls: type[Op]) -> tuple[int, int]:
    modulo = cls.__module__.rsplit(".", 1)[-1]
    grupos = list(dict.fromkeys(GRUPOS))
    return grupos.index(modulo), inspect.getsourcelines(cls)[1]


def gerar() -> str:
    nomes_ops, params = rotulos("ops"), rotulos("params")
    catalogo = {n: c for n, c in registered_ops().items() if c.__module__.startswith("wolfz.ops.")}
    sem_rotulo = sorted(set(catalogo) - set(nomes_ops))
    if sem_rotulo:
        raise SystemExit(f"operações sem nome em textos.ts: {', '.join(sem_rotulo)}")
    ordenadas = sorted(catalogo.items(), key=lambda item: _ordem(item[1]))

    saida = [
        "# Operações",
        "",
        "<!-- Gerado por scripts/gerar_operacoes.py a partir do catálogo. Não edite à mão. -->",
        "",
        f"As {len(catalogo)} operações que um passo de receita pode usar, no formato "
        f'`wolfz_version: "{CURRENT_VERSION}"`. O formato da receita está em '
        "[`receita.md`](receita.md). Cada operação tem a mesma regra no motor (Polars), na "
        "consulta Power Query M e no script Python exportados, com teste de equivalência.",
        "",
        "Todo passo tem também `id` (`s1`, `s2`, …), `op` (o nome da operação) e, opcional, "
        "`enabled` (`false` deixa o passo na receita sem rodar). Os exemplos abaixo são "
        "calculados pelo motor a cada geração deste arquivo.",
        "",
    ]
    grupo_atual = None
    for nome, cls in ordenadas:
        grupo = GRUPOS[cls.__module__.rsplit(".", 1)[-1]]
        if grupo != grupo_atual:
            saida += [f"- **{grupo}**"]
            grupo_atual = grupo
        saida += [f"  - [`{nome}`](#{nome}): {nomes_ops[nome]}"]
    saida.append("")

    grupo_atual = None
    for nome, cls in ordenadas:
        grupo = GRUPOS[cls.__module__.rsplit(".", 1)[-1]]
        if grupo != grupo_atual:
            saida += [f"## {grupo}", ""]
            grupo_atual = grupo
        saida += [
            f'<a id="{nome}"></a>',
            "",
            f"### `{nome}`: {nomes_ops[nome]}",
            "",
            inspect.cleandoc(cls.__doc__ or ""),
            "",
            *_parametros(cls, params),
            "",
        ]
        for i, exemplo in enumerate(cls.examples, 1):
            saida += _exemplo(cls, nome, i, exemplo)
        saida += [*_m(cls, nome), ""]
    return "\n".join(saida).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="falha se o arquivo estiver desatualizado")
    args = parser.parse_args(argv)
    texto = gerar()
    if args.check:
        atual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
        if atual != texto:
            print(f"{DESTINO.relative_to(RAIZ)} desatualizado: rode python scripts/gerar_operacoes.py")
            return 1
        return 0
    DESTINO.write_text(texto, encoding="utf-8", newline="\n")
    print(f"gravado: {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

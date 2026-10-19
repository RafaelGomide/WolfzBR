"""Leitura do corpus de testes (``tests/corpus/``, F1.B).

Uma pasta por arquivo, com ``original.*``, ``receita_esperada.wolfz.json``,
``saida_esperada.parquet`` e ``FONTE.md``. Ver ``tests/corpus/README.md``.
Usado pelos testes e, depois, por ``scripts/medir_deteccao.py`` (F1.C8).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from types import ModuleType
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
CORPUS = RAIZ / "tests" / "corpus"
VALIDACAO = CORPUS / "validacao"

MAX_BYTES = 1024 * 1024  # F1.B2
MINIMO_ARQUIVOS = 30  # F1.B3
MINIMO_POR_CATEGORIA = 2
ARQUIVOS_VALIDACAO = 10  # F1.B5
FORMATOS = {".xlsx", ".xls", ".ods", ".csv"}
# Arquivos soltos na raiz do corpus, anteriores a esta estrutura.
SOLTOS = {"README.md", "minimo.csv"}

CATEGORIAS = {
    "relatorio_rodape": "relatório com título, cabeçalho e rodapé",
    "cabecalho_multinivel": "cabeçalho multinível com mesclagem",
    "subtotais": "subtotais no meio",
    "mesclagem_vertical": "mesclagem vertical de categoria",
    "csv_cp1252": "CSV cp1252 com ';'",
    "csv_utf8_bom": "CSV UTF-8 com BOM",
    "sinais_ibge": "sinais do IBGE",
    "datas_8_digitos": "datas em 8 dígitos",
    "zeros_perdidos": "zeros à esquerda perdidos",
    "meses_lado_a_lado": "meses lado a lado",
    "exportacao_erp": "exportação de ERP",
    "xls_antigo": ".xls antigo",
    "ods": ".ods",
    "duas_tabelas": "duas tabelas na mesma aba",
    "mojibake": "mojibake",
}

# Operações que as receitas do corpus podem citar antes de existirem: o
# catálogo de F1.E e as previstas para depois. Serve para pegar erro de
# digitação numa receita que ainda não roda.
OPERACOES_PLANEJADAS = {
    # F1.E
    "select_range",
    "header_rows",
    "drop_empty_rows",
    "drop_empty_cols",
    "fill_down",
    "drop_cols",
    "reorder",
    "cast",
    "split_col",
    "merge_cols",
    "trim",
    "case",
    "remove_accents",
    "replace",
    "parse_decimal_br",
    "parse_percent",
    "parse_date_br",
    "parse_month_year",
    "parse_bool_br",
    "clean_cpf",
    "clean_cnpj",
    "clean_cep",
    "normalize_uf",
    "dedupe",
    "filter",
    "fill_null",
    "sort",
    "unpivot",
    # F2.C
    "parse_ibge_value",
    "clean_cpf_cnpj",
    "fix_mojibake",
    "strip_footnotes",
    "clean_phone",
    "split_municipio_uf",
    "scale_by_unit",
    "normalize_municipio",
}

CAMPOS_FONTE = {
    "sintetico": {"origem", "gerador", "licenca", "categorias"},
    "publico": {"origem", "url", "baixado_em", "licenca", "categorias"},
}
ARQUIVOS_PERMITIDOS = {"FONTE.md", "estrutura_esperada.json", "externo.json", ".gitignore"}


def ler_fonte(path: Path) -> dict[str, Any]:
    """Cabeçalho ``---`` do ``FONTE.md`` (chave: valor, uma por linha)."""
    linhas = path.read_text(encoding="utf-8").splitlines()
    if not linhas or linhas[0].strip() != "---":
        raise ValueError(f"{path}: FONTE.md precisa começar com um cabeçalho '---'")
    dados: dict[str, Any] = {}
    for linha in linhas[1:]:
        if linha.strip() == "---":
            break
        chave, sep, valor = linha.partition(":")
        if not sep:
            raise ValueError(f"{path}: linha sem 'chave: valor': {linha!r}")
        dados[chave.strip()] = valor.strip()
    else:
        raise ValueError(f"{path}: cabeçalho '---' sem fechamento")
    if "categorias" in dados:
        dados["categorias"] = [c.strip() for c in dados["categorias"].split(",") if c.strip()]
    return dados


@dataclass(frozen=True)
class Par:
    """Uma receita e a saída que ela deve produzir."""

    entrada: Entrada
    receita: Path
    saida: Path

    @property
    def id(self) -> str:
        sufixo = self.receita.name.removeprefix("receita_esperada").removesuffix(".wolfz.json")
        return f"{self.entrada.nome}{sufixo}"

    def json(self) -> dict[str, Any]:
        return json.loads(self.receita.read_text(encoding="utf-8"))

    def operacoes(self) -> list[str]:
        return [p.get("op", "") for p in self.json().get("steps", [])]


@dataclass(frozen=True)
class Entrada:
    pasta: Path
    conjunto: str  # "desenvolvimento" ou "validacao"

    @property
    def nome(self) -> str:
        return self.pasta.name

    @cached_property
    def fonte(self) -> dict[str, Any]:
        return ler_fonte(self.pasta / "FONTE.md")

    @property
    def estrutura(self) -> dict[str, Any]:
        """``estrutura_esperada.json``: gabarito da detecção (F1.C8)."""
        return json.loads((self.pasta / "estrutura_esperada.json").read_text(encoding="utf-8"))

    @property
    def externo(self) -> dict[str, Any] | None:
        path = self.pasta / "externo.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @property
    def originais(self) -> list[Path]:
        return sorted(self.pasta.glob("original.*"))

    @property
    def original(self) -> Path | None:
        return self.originais[0] if len(self.originais) == 1 else None

    @property
    def pares(self) -> list[Par]:
        pares = []
        for receita in sorted(self.pasta.glob("receita_esperada*.wolfz.json")):
            sufixo = receita.name.removeprefix("receita_esperada").removesuffix(".wolfz.json")
            pares.append(Par(self, receita, self.pasta / f"saida_esperada{sufixo}.parquet"))
        return pares


def _pastas(raiz: Path) -> list[Path]:
    if not raiz.is_dir():
        return []
    return sorted(
        p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")) and p != VALIDACAO
    )


def entradas(validacao: bool = True) -> list[Entrada]:
    lista = [Entrada(p, "desenvolvimento") for p in _pastas(CORPUS)]
    if validacao:
        lista += [Entrada(p, "validacao") for p in _pastas(VALIDACAO)]
    return lista


def pares(validacao: bool = True) -> list[Par]:
    return [p for e in entradas(validacao) for p in e.pares]


def _script(nome: str) -> ModuleType:
    """Um script de ``scripts/`` importado como módulo."""
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "scripts" / f"{nome}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo  # dataclasses precisam do módulo registrado
    spec.loader.exec_module(modulo)
    return modulo


def gerador() -> ModuleType:
    """``scripts/gerar_sinteticos.py``."""
    return _script("gerar_sinteticos")


def publicos() -> ModuleType:
    """``scripts/corpus_publico.py``."""
    return _script("corpus_publico")

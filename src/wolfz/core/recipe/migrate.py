"""Migração de receitas de ``wolfz_version`` antiga para a atual.

Roda ao carregar, em memória; o arquivo só é regravado quando o usuário
salva (§13.3 do design). Política (§5.7): receitas ``0.x`` são migradas até
a 1.0; depois disso toda receita ``1.x`` abre em qualquer versão ``1.y``.
Receita de versão mais nova que o WolfzBR instalado é recusada, nunca
interpretada pela metade.

Para mudar o formato: suba ``CURRENT_VERSION`` e registre em ``MIGRATIONS``
uma função que leva o dicionário da versão anterior para a seguinte.

Na memória toda receita fica no formato atual, mas ela é **gravada com o
menor formato que usa** (ADR-9, ``formato_minimo``): uma receita sem nada da
1.1 continua ``"1.0"``, byte a byte, e abre no WolfzBR 1.0.x. Toda op nova
declara ``desde`` (``Op.desde``) e todo campo novo, ``json_schema_extra={"desde": …}``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

CURRENT_VERSION = "1.1"

RecipeDict = dict[str, Any]

# Parâmetros renomeados no congelamento da 1.0 (FH.A2): operação -> {antigo: novo}.
# Todo texto que se intercala ao juntar ou dividir é ``separator``, e opção
# booleana que acrescenta coluna começa com ``add_`` (``*_col`` é sempre o
# nome de uma coluna).
RENOMEADOS_1_0: dict[str, dict[str, str]] = {
    "split_col": {"delimiter": "separator"},
    "header_rows": {"joiner": "separator"},
    "clean_cpf": {"flag": "add_valid_col"},
    "clean_cnpj": {"flag": "add_valid_col"},
    "parse_ibge_value": {"status": "add_status_col"},
}


def _de_0_1_para_1_0(data: RecipeDict) -> RecipeDict:
    steps = data.get("steps")
    if not isinstance(steps, list):
        return dict(data)
    novos = []
    for step in steps:
        nomes = RENOMEADOS_1_0.get(step.get("op")) if isinstance(step, dict) else None
        novos.append({nomes.get(k, k): v for k, v in step.items()} if nomes else step)
    return {**data, "steps": novos}


# versão de origem -> (versão de destino, função).
MIGRATIONS: dict[str, tuple[str, Callable[[RecipeDict], RecipeDict]]] = {
    "0.1": ("1.0", _de_0_1_para_1_0),
    # A 1.1 só acrescenta: toda receita 1.0 é uma receita 1.1 válida.
    "1.0": ("1.1", dict),
}


class RecipeVersionError(ValueError):
    """Versão da receita ausente, inválida ou sem caminho de migração."""


class NewerRecipeVersion(RecipeVersionError):
    """Receita gravada por um WolfzBR mais novo que o instalado (F2.G2)."""

    def __init__(self, version: str, supported: str):
        self.version = version
        self.supported = supported
        super().__init__(
            f"esta receita foi feita numa versão mais nova do WolfzBR (formato {version}); "
            f"o WolfzBR {_instalado()} instalado lê até o formato {supported}. "
            f"Atualize o WolfzBR: {COMANDO_ATUALIZAR}"
        )


COMANDO_ATUALIZAR = "pipx upgrade wolfzbr (ou pip install --upgrade wolfzbr)"


def _instalado() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("wolfzbr")
    except PackageNotFoundError:  # pragma: no cover - rodando sem instalar
        return "0.0.0+desconhecida"


def parse_version(version: object) -> tuple[int, int]:
    """'1.0' -> (1, 0). Só major.minor: a receita não tem versão de patch."""
    if not isinstance(version, str) or not (m := re.fullmatch(r"(\d+)\.(\d+)", version)):
        raise RecipeVersionError(f"wolfz_version inválida: {version!r} (esperado algo como '1.0')")
    return int(m[1]), int(m[2])


def migrate(data: RecipeDict, target: str = CURRENT_VERSION) -> RecipeDict:
    """Leva a receita até ``target`` aplicando as migrações em sequência.

    Devolve um dicionário novo; o original não é alterado."""
    if "wolfz_version" not in data:
        raise RecipeVersionError("receita sem o campo 'wolfz_version'")
    version = data["wolfz_version"]
    if parse_version(version) > parse_version(target):
        raise NewerRecipeVersion(version, target)
    data = dict(data)
    while data["wolfz_version"] != target:
        step = MIGRATIONS.get(data["wolfz_version"])
        if step is None:
            raise RecipeVersionError(
                f"não há migração do formato {data['wolfz_version']} para {target}; "
                "a receita é antiga demais para esta versão do WolfzBR"
            )
        next_version, fn = step
        data = fn(data)
        data["wolfz_version"] = next_version
    return data

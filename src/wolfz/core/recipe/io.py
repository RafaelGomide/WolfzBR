"""Leitura, gravação e validação de receitas ``.wolfz.json``.

Serialização estável (ADR do formato da receita, §15 do design): chaves ordenadas, indentação de
2, UTF-8 sem BOM e ``\\n`` no fim. Carregar e salvar uma receita já
canônica produz exatamente os mesmos bytes, então o diff no Git mostra só o
que mudou de fato.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from wolfz.core.recipe.migrate import RecipeVersionError, migrate
from wolfz.core.recipe.models import Recipe, recipe_validator
from wolfz.core.workspace import replace_atomic


class RecipeError(ValueError):
    """Receita inválida. ``errors`` traz uma mensagem por problema, no
    formato ``"s5.cols[0]: não pode ser vazio"``."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _load_catalog() -> None:
    # Importar o pacote de operações executa os @register_op. Fica aqui, e
    # não no topo do módulo, porque wolfz.ops importa wolfz.core.recipe.
    importlib.import_module("wolfz.ops")


# ---------------------------------------------------------------------------
# Mensagens de erro
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, str] = {
    "missing": "campo obrigatório",
    "extra_forbidden": "campo não permitido",
    "string_type": "deve ser texto",
    "int_type": "deve ser um número inteiro",
    "int_parsing": "deve ser um número inteiro",
    "float_type": "deve ser um número",
    "float_parsing": "deve ser um número",
    "bool_type": "deve ser verdadeiro ou falso",
    "bool_parsing": "deve ser verdadeiro ou falso",
    "list_type": "deve ser uma lista",
    "dict_type": "deve ser um objeto",
    "model_type": "deve ser um objeto",
    "model_attributes_type": "deve ser um objeto",
    "datetime_type": "deve ser data e hora (ex.: 2026-10-16T14:00:00Z)",
    "datetime_parsing": "deve ser data e hora (ex.: 2026-10-16T14:00:00Z)",
    "datetime_from_date_parsing": "deve ser data e hora (ex.: 2026-10-16T14:00:00Z)",
    "union_tag_not_found": "passo sem o campo 'op'",
}


def _message(error: dict[str, Any]) -> str:
    kind, ctx = error["type"], error.get("ctx") or {}
    if kind == "union_tag_invalid":
        return f"operação desconhecida: {ctx.get('tag')!r}"
    if kind == "literal_error":
        expected = str(ctx.get("expected", "")).replace(" or ", " ou ")
        return f"valor inválido; esperado {expected}"
    if kind == "string_too_short":
        return (
            "não pode ser vazio"
            if ctx.get("min_length") == 1
            else f"mínimo de {ctx['min_length']} caracteres"
        )
    if kind == "too_short":
        return f"precisa de pelo menos {ctx.get('min_length')} item(ns)"
    if kind == "string_pattern_mismatch":
        return (
            "id de passo deve seguir o formato s1, s2, …" if error["loc"][-1] == "id" else "formato inválido"
        )
    if kind == "value_error":
        return str(ctx.get("error", error["msg"]))
    return _MESSAGES.get(kind, error["msg"])


def _path(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _format_errors(exc: ValidationError, data: Any) -> list[str]:
    raw_steps = data.get("steps") if isinstance(data, dict) else None
    lines = []
    for error in exc.errors():
        loc = error["loc"]
        if len(loc) >= 2 and loc[0] == "steps" and isinstance(loc[1], int):
            i, rest = loc[1], loc[2:]
            raw = raw_steps[i] if isinstance(raw_steps, list) and i < len(raw_steps) else None
            step_id = raw.get("id") if isinstance(raw, dict) else None
            # Com a união discriminada, o pydantic põe o nome da operação no
            # caminho ('steps', 4, 'rename', 'cols', 0); para o usuário ele
            # não acrescenta nada.
            if rest and isinstance(raw, dict) and rest[0] == raw.get("op"):
                rest = rest[1:]
            prefix = step_id if isinstance(step_id, str) and step_id else f"steps[{i}]"
            where = prefix + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in rest)
        else:
            where = _path(loc) or "receita"
        lines.append(f"{where}: {_message(error)}")
    return lines


# ---------------------------------------------------------------------------
# Leitura e gravação
# ---------------------------------------------------------------------------


def recipe_from_dict(data: Any) -> Recipe:
    """Valida um dicionário (já decodificado do JSON) como receita, migrando
    versões antigas antes."""
    if not isinstance(data, dict):
        raise RecipeError(["receita: o JSON deve ser um objeto"])
    _load_catalog()
    try:
        data = migrate(data)
    except RecipeVersionError as exc:
        raise RecipeError([f"wolfz_version: {exc}"]) from None
    try:
        return recipe_validator().model_validate(data)
    except ValidationError as exc:
        raise RecipeError(_format_errors(exc, data)) from None


def loads_recipe(text: str) -> Recipe:
    """Lê uma receita a partir do texto JSON."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecipeError([f"JSON inválido na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}"]) from None
    return recipe_from_dict(data)


def load_recipe(path: str | Path) -> Recipe:
    """Carrega e valida uma receita ``.wolfz.json``. Aceita arquivo com BOM
    (editores do Windows), mas sempre grava sem."""
    return loads_recipe(Path(path).read_text(encoding="utf-8-sig"))


def dumps_recipe(recipe: Recipe) -> str:
    """Texto canônico da receita: chaves ordenadas, indentação de 2, ``\\n``
    no fim. Campos com valor ``None`` são omitidos."""
    data = recipe.model_dump(mode="json", exclude_none=True)
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def save_recipe(recipe: Recipe, path: str | Path) -> None:
    """Grava a receita em UTF-8 sem BOM, com quebra de linha ``\\n`` em
    qualquer sistema. Escreve em arquivo temporário e renomeia por cima,
    para que um crash no meio nunca deixe um JSON truncado (§9)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(dumps_recipe(recipe).encode("utf-8"))
    replace_atomic(tmp, path)  # aguenta leitor concorrente no Windows


def recipe_json_schema() -> dict[str, Any]:
    """JSON Schema da receita com o catálogo de operações atual. O frontend
    monta os formulários dos passos a partir dele."""
    _load_catalog()
    return recipe_validator().model_json_schema()

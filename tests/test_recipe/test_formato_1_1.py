"""Formato 1.1 gravado só quando a receita usa algo da 1.1 (ADR-9)."""

import json
from pathlib import Path

import pytest

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.recipe import (
    CURRENT_VERSION,
    RecipeTooNewError,
    Source,
    dumps_recipe,
    formato_minimo,
    loads_recipe,
    recipe_from_dict,
    registered_ops,
)

ANTIGAS = Path(__file__).resolve().parents[1] / "receitas_antigas"
BASE = {"wolfz_version": "1.0", "name": "t", "created_at": "2026-01-01T00:00:00Z"}


def _dumps(source, *passos):
    data = {**BASE, "source": source, "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)]}
    return json.loads(dumps_recipe(recipe_from_dict(data)))


def test_na_memoria_toda_receita_e_do_formato_atual():
    assert recipe_from_dict({**BASE, "source": {"type": "csv"}}).wolfz_version == CURRENT_VERSION == "1.1"


def test_sem_nada_novo_continua_1_0():
    assert _dumps({"type": "excel", "sheet": "JAN"}, {"op": "trim", "cols": ["a"]})["wolfz_version"] == "1.0"


@pytest.mark.parametrize(
    ("source", "passo"),
    [
        ({"type": "excel", "combine_sheets": {}}, {"op": "trim", "cols": ["a"]}),
        ({"type": "excel", "combine_sheets": {"origin_col": None}}, {"op": "trim", "cols": ["a"]}),
        ({"type": "csv"}, {"op": "parse_datetime_br", "cols": ["a"]}),
    ],
)
def test_com_recurso_novo_vira_1_1(source, passo):
    assert _dumps(source, passo)["wolfz_version"] == "1.1"


def test_1_1_recusada_pela_1_0_com_a_mensagem_de_versao_nova(monkeypatch):
    """Critério 13 da F3: o WolfzBR 1.0.x (CURRENT_VERSION "1.0") recusa a
    receita 1.1 pedindo para atualizar, não com "campo não permitido"."""
    import importlib

    io = importlib.import_module("wolfz.core.recipe.io")
    texto = dumps_recipe(recipe_from_dict({**BASE, "source": {"type": "excel", "combine_sheets": {}}}))
    original = io.migrate
    monkeypatch.setattr(io, "migrate", lambda d: original(d, target="1.0"))
    with pytest.raises(RecipeTooNewError) as exc:
        loads_recipe(texto)
    assert "versão mais nova" in str(exc.value) and "Atualize" in str(exc.value)


def _catalogo_1_0_1():
    data = json.loads((ANTIGAS / "v1.0.1" / "catalogo.wolfz.json").read_text(encoding="utf-8"))
    return {p["op"]: set(p) for p in data["steps"]}


def test_toda_op_nova_declara_desde():
    """Item 5 do ADR-9: quem cria uma op nova não pode esquecer o desde."""
    antigas = _catalogo_1_0_1()
    for nome, cls in registered_ops().items():
        if nome.startswith("teste_"):
            continue
        assert (cls.desde == "1.0") == (nome in antigas), nome


def test_todo_campo_novo_de_source_declara_desde():
    antigos = {"type", "sheet", "match"}
    for nome, campo in Source.model_fields.items():
        marcado = isinstance(campo.json_schema_extra, dict) and "desde" in campo.json_schema_extra
        assert marcado == (nome not in antigos), nome


def test_formato_minimo_de_dicionario():
    assert formato_minimo({"source": {"type": "csv"}, "steps": [{"op": "trim"}]}) == "1.0"
    assert formato_minimo({"source": {"type": "excel", "combine_sheets": {}}, "steps": []}) == "1.1"

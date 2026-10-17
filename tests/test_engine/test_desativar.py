"""Passo desativado (``enabled: false``): fica na receita, mas não roda em
lugar nenhum (motor, preview, exportação M e Python)."""

import json

import polars as pl

import wolfz.ops  # noqa: F401
from wolfz.core.engine import collect
from wolfz.core.engine.cache import chaves
from wolfz.core.engine.preview import preview
from wolfz.core.recipe import dumps_recipe, loads_recipe, recipe_from_dict
from wolfz.export.m import recipe_to_m
from wolfz.export.python import recipe_to_python

TABELA = pl.DataFrame({"Região": ["Sul", "Total"], "Vlr": ["1,50", "1,50"]})


def _receita(enabled_s2=True):
    s2 = {"id": "s2", "op": "drop_rows_where", "col": "regiao", "match": "equals", "value": "Total"}
    if not enabled_s2:
        s2["enabled"] = False
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "desativar",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [
                {"id": "s1", "op": "rename", "mapping": {"Região": "regiao"}},
                s2,
                {"id": "s3", "op": "parse_brl", "cols": ["Vlr"]},
            ],
        }
    )


def test_passo_ativo_nao_grava_o_campo():
    texto = dumps_recipe(_receita())
    assert "enabled" not in texto  # receitas antigas continuam com os mesmos bytes


def test_passo_desativado_grava_e_volta():
    receita = _receita(enabled_s2=False)
    texto = dumps_recipe(receita)
    passos = json.loads(texto)["steps"]
    assert passos[1]["enabled"] is False and "enabled" not in passos[0]
    assert dumps_recipe(loads_recipe(texto)) == texto
    assert [s.id for s in receita.active_steps] == ["s1", "s3"]


def test_motor_pula_o_passo_desativado():
    ativo = collect(_receita(), TABELA.lazy())
    desativado = collect(_receita(enabled_s2=False), TABELA.lazy())
    assert ativo.height == 1 and desativado.height == 2
    assert desativado["Vlr"].to_list() == [1.5, 1.5]


def test_preview_pula_e_reaproveita_o_cache(tmp_path):
    raw = tmp_path / "raw.parquet"
    TABELA.write_parquet(raw)
    receita = _receita(enabled_s2=False)
    pagina = preview(raw, "k", receita)
    assert pagina.total_rows == 2
    # No passo desativado, o preview mostra a tabela de antes dele.
    assert preview(raw, "k", receita, step="s2").frame.columns == ["regiao", "Vlr"]
    sem_s2 = receita.model_copy(update={"steps": [receita.steps[0], receita.steps[2]]})
    assert chaves("k", receita.active_steps) == chaves("k", sem_s2.steps)


def test_exportadores_pulam_o_passo_desativado():
    receita = _receita(enabled_s2=False)
    assert "s2" not in recipe_to_m(receita)
    assert "# s2" not in recipe_to_python(receita)
    assert "s2" in recipe_to_m(_receita())

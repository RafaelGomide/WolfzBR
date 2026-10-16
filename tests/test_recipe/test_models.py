from datetime import UTC, datetime
from typing import Literal

import polars as pl
import pytest
from conftest import RemoverDeTeste, RenomearDeTeste

from wolfz.core.recipe import (
    Op,
    Recipe,
    RecipeError,
    Source,
    models,
    recipe_from_dict,
    register_op,
    registered_ops,
)


def test_carrega_passos_com_a_classe_certa(recipe_dict):
    recipe = recipe_from_dict(recipe_dict)
    assert isinstance(recipe, Recipe)
    assert [type(s) for s in recipe.steps] == [RenomearDeTeste, RemoverDeTeste]
    assert recipe.steps[1].strict is True
    assert recipe.source.match.sheet_name_regex == r"Vendas \d{4}"
    assert recipe.created_at == datetime(2026, 10, 16, 14, tzinfo=UTC)


def test_passos_executam_em_sequencia(recipe_dict):
    recipe = recipe_from_dict(recipe_dict)
    lf = pl.LazyFrame({"Vlr": [1], "obs": ["x"]})
    for step in recipe.steps:
        lf = step.to_polars(lf)
    assert lf.collect().columns == ["valor"]


def test_receita_construida_em_codigo():
    recipe = Recipe(
        wolfz_version="0.1",
        name="Teste",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source=Source(type="csv"),
        steps=[RemoverDeTeste(id="s1", op="teste_remover", cols=["a"])],
    )
    assert recipe.model_dump()["steps"][0]["cols"] == ["a"]  # serializa a subclasse inteira


def test_receita_sem_passos(recipe_dict):
    recipe_dict["steps"] = []
    assert recipe_from_dict(recipe_dict).steps == []


def test_op_e_abstrata():
    with pytest.raises(TypeError):
        Op(id="s1", op="x")


def test_catalogo_registrado():
    ops = registered_ops()
    assert ops["teste_renomear"] is RenomearDeTeste
    assert ops["teste_remover"] is RemoverDeTeste


def test_registrar_de_novo_a_mesma_classe_e_inofensivo():
    assert register_op(RemoverDeTeste) is RemoverDeTeste


def test_registro_recusa_nome_repetido():
    class Outra(Op):
        op: Literal["teste_remover"]

        def to_polars(self, lf):
            return lf

        def to_m(self, prev, name):
            return ""

        def to_python(self):
            return ""

    with pytest.raises(ValueError, match="já registrada"):
        register_op(Outra)


def test_registro_recusa_op_sem_literal():
    class SemLiteral(Op):
        def to_polars(self, lf):
            return lf

        def to_m(self, prev, name):
            return ""

        def to_python(self):
            return ""

    with pytest.raises(TypeError, match="Literal"):
        register_op(SemLiteral)


def test_registro_recusa_op_incompleta():
    class Incompleta(Op):
        op: Literal["teste_incompleta"]

    with pytest.raises(TypeError, match="não implementa"):
        register_op(Incompleta)


@pytest.mark.parametrize("cls", [Op, int, "rename"])
def test_registro_recusa_o_que_nao_e_op(cls):
    with pytest.raises(TypeError):
        register_op(cls)


def test_catalogo_vazio_recusa_qualquer_passo(recipe_dict, monkeypatch):
    monkeypatch.setattr(models, "_REGISTRY", {})
    models.recipe_validator.cache_clear()
    try:
        with pytest.raises(RecipeError) as exc:
            recipe_from_dict(recipe_dict)
        assert exc.value.errors == [
            "s1: operação desconhecida: 'teste_renomear'",
            "s2: operação desconhecida: 'teste_remover'",
        ]
    finally:
        models.recipe_validator.cache_clear()

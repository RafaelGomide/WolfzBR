"""Estrutura da migração. ``MIGRATIONS`` está vazio na 0.1; os testes usam
migrações falsas para garantir que a cadeia funciona antes de existir a
primeira de verdade."""

import importlib

import pytest

import wolfz
from wolfz.core.recipe import RecipeError, RecipeTooNewError, recipe_from_dict
from wolfz.core.recipe.migrate import (
    CURRENT_VERSION,
    NewerRecipeVersion,
    RecipeVersionError,
    migrate,
    parse_version,
)

# O pacote exporta a função migrate, que esconde o submódulo de mesmo nome.
migrate_module = importlib.import_module("wolfz.core.recipe.migrate")


def test_versao_atual():
    assert CURRENT_VERSION == "0.1"
    assert migrate_module.MIGRATIONS == {}


def test_versao_atual_passa_sem_mudar():
    data = {"wolfz_version": CURRENT_VERSION, "name": "x"}
    assert migrate(data) == data


@pytest.mark.parametrize(("version", "expected"), [("0.1", (0, 1)), ("1.10", (1, 10))])
def test_parse_version(version, expected):
    assert parse_version(version) == expected


@pytest.mark.parametrize("version", ["1", "1.0.0", "v1.0", "", None, 1.0])
def test_parse_version_invalida(version):
    with pytest.raises(RecipeVersionError, match="inválida"):
        parse_version(version)


def test_sem_versao():
    with pytest.raises(RecipeVersionError, match="sem o campo"):
        migrate({"name": "x"})


@pytest.mark.parametrize("version", ["0.2", "1.0", "10.1"])
def test_versao_mais_nova_e_recusada(version):
    with pytest.raises(NewerRecipeVersion) as exc:
        migrate({"wolfz_version": version})
    assert (exc.value.version, exc.value.supported) == (version, CURRENT_VERSION)
    mensagem = str(exc.value)
    assert f"formato {version}" in mensagem
    assert f"o WolfzBR {wolfz.__version__} instalado lê até o formato {CURRENT_VERSION}" in mensagem
    assert "pipx upgrade wolfzbr" in mensagem


def test_versao_mais_nova_vira_erro_de_receita():
    """Quem carrega a receita (CLI, API, ``wolfz.run``) recebe um RecipeError
    próprio, com uma linha só: a de pedir atualização."""
    with pytest.raises(RecipeTooNewError) as exc:
        recipe_from_dict({"wolfz_version": "0.2", "name": "x", "steps": []})
    assert isinstance(exc.value, RecipeError)
    assert len(exc.value.errors) == 1
    assert exc.value.errors[0].startswith("Esta receita foi feita numa versão mais nova do WolfzBR")


def test_cadeia_de_migracoes(monkeypatch):
    def v0_1_para_0_2(d):
        d = dict(d)
        d["nome"] = d.pop("name")
        return d

    def v0_2_para_1_0(d):
        return {**d, "steps": d.get("steps", [])}

    monkeypatch.setattr(
        migrate_module,
        "MIGRATIONS",
        {"0.1": ("0.2", v0_1_para_0_2), "0.2": ("1.0", v0_2_para_1_0)},
    )
    original = {"wolfz_version": "0.1", "name": "x"}
    assert migrate(original, target="1.0") == {"wolfz_version": "1.0", "nome": "x", "steps": []}
    assert original == {"wolfz_version": "0.1", "name": "x"}  # não altera a entrada


def test_sem_caminho_de_migracao():
    with pytest.raises(RecipeVersionError, match="antiga demais"):
        migrate({"wolfz_version": "0.0"})

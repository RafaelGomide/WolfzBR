"""Mensagens de erro de validação: sempre com o id do passo e o campo."""

import copy

import pytest

from wolfz.core.recipe import RecipeError, loads_recipe, recipe_from_dict


def _errors(recipe_dict, change):
    data = copy.deepcopy(recipe_dict)
    change(data)
    with pytest.raises(RecipeError) as exc:
        recipe_from_dict(data)
    return exc.value.errors


def test_erro_aponta_id_do_passo_e_indice(recipe_dict):
    errors = _errors(recipe_dict, lambda d: d["steps"][1].update(id="s5", cols=[3]))
    assert errors == ["s5.cols[0]: deve ser texto"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d["steps"][1].pop("cols"), "s2.cols: campo obrigatório"),
        (lambda d: d["steps"][1].update(cols=[]), "s2.cols: precisa de pelo menos 1 item(ns)"),
        (lambda d: d["steps"][1].update(strict="talvez"), "s2.strict: deve ser verdadeiro ou falso"),
        (lambda d: d["steps"][1].update(colunas=["a"]), "s2.colunas: campo não permitido"),
        (lambda d: d["steps"][0].update(op="nao_existe"), "s1: operação desconhecida: 'nao_existe'"),
        (lambda d: d["steps"][0].pop("op"), "s1: passo sem o campo 'op'"),
        (
            lambda d: d["steps"][0].update(id="passo1"),
            "passo1.id: id de passo deve seguir o formato s1, s2, …",
        ),
        (lambda d: d["steps"][0].pop("id"), "steps[0].id: campo obrigatório"),
        (lambda d: d["steps"].append("x"), "steps[2]: deve ser um objeto"),
        (lambda d: d["steps"][1].update(id="s1"), "receita: id de passo repetido: 's1'"),
        (lambda d: d.pop("name"), "name: campo obrigatório"),
        (lambda d: d.update(name=""), "name: não pode ser vazio"),
        (
            lambda d: d.update(created_at="ontem"),
            "created_at: deve ser data e hora (ex.: 2026-10-16T14:00:00Z)",
        ),
        (
            lambda d: d["source"].update(type="pdf"),
            "source.type: valor inválido; esperado 'excel', 'csv' ou 'ods'",
        ),
        (
            lambda d: d["source"]["match"].update(sheet_name_regex="("),
            "source.match.sheet_name_regex: regex inválida",
        ),
        (lambda d: d.update(steps={}), "steps: deve ser uma lista"),
        (lambda d: d.update(extra=1), "extra: campo não permitido"),
    ],
)
def test_mensagens(recipe_dict, change, expected):
    errors = _errors(recipe_dict, change)
    assert len(errors) == 1
    assert errors[0].startswith(expected)


def test_varios_erros_de_uma_vez(recipe_dict):
    def change(d):
        d.pop("name")
        d["steps"][1]["cols"] = [1, 2]

    assert _errors(recipe_dict, change) == [
        "name: campo obrigatório",
        "s2.cols[0]: deve ser texto",
        "s2.cols[1]: deve ser texto",
    ]


def test_mensagem_da_excecao_junta_as_linhas(recipe_dict):
    recipe_dict.pop("name")
    recipe_dict.pop("source")
    with pytest.raises(RecipeError, match="name: campo obrigatório\nsource: campo obrigatório"):
        recipe_from_dict(recipe_dict)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"name": ', "JSON inválido na linha 1, coluna 10"),
        ("[]", "receita: o JSON deve ser um objeto"),
        ('{"name": "x"}', "wolfz_version: receita sem o campo 'wolfz_version'"),
        ('{"wolfz_version": "9.0"}', "Esta receita foi feita numa versão mais nova do WolfzBR"),
    ],
)
def test_erros_de_leitura(text, expected):
    with pytest.raises(RecipeError) as exc:
        loads_recipe(text)
    assert exc.value.errors[0].startswith(expected)

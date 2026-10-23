import json

import pytest
from typer.testing import CliRunner

from wolfz.cli import app
from wolfz.core.recipe import (
    dumps_recipe,
    load_recipe,
    loads_recipe,
    recipe_from_dict,
    recipe_json_schema,
    save_recipe,
)

CANONICA = """{
  "created_at": "2026-10-16T14:00:00Z",
  "name": "Vendas de São Paulo",
  "source": {
    "match": {
      "sheet_name_regex": "Vendas \\\\d{4}"
    },
    "sheet": "Vendas",
    "type": "excel"
  },
  "steps": [
    {
      "id": "s1",
      "mapping": {
        "Vlr": "valor"
      },
      "op": "teste_renomear"
    },
    {
      "cols": [
        "obs"
      ],
      "id": "s2",
      "op": "teste_remover",
      "strict": true
    }
  ],
  "wolfz_version": "1.0"
}
"""


def test_carregar_e_salvar_preserva_os_bytes(tmp_path):
    path = tmp_path / "vendas.wolfz.json"
    path.write_bytes(CANONICA.encode("utf-8"))
    save_recipe(load_recipe(path), path)
    assert path.read_bytes() == CANONICA.encode("utf-8")


def test_formato_canonico(recipe_dict):
    recipe_dict["name"] = "Vendas de São Paulo"
    text = dumps_recipe(recipe_from_dict(recipe_dict))
    assert text == CANONICA  # chaves ordenadas, indentação 2, acento literal, \n no fim


def test_gravacao_sem_bom_e_com_lf(tmp_path, recipe_dict):
    path = tmp_path / "r.wolfz.json"
    save_recipe(recipe_from_dict(recipe_dict), path)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert [p.name for p in tmp_path.iterdir()] == ["r.wolfz.json"]  # sem temporário sobrando


def test_none_e_omitido(recipe_dict):
    del recipe_dict["source"]["sheet"], recipe_dict["source"]["match"]
    data = json.loads(dumps_recipe(recipe_from_dict(recipe_dict)))
    assert data["source"] == {"type": "excel"}


def test_le_arquivo_com_bom(tmp_path):
    path = tmp_path / "bom.wolfz.json"
    path.write_bytes(b"\xef\xbb\xbf" + CANONICA.encode("utf-8"))
    assert load_recipe(path).name == "Vendas de São Paulo"


def test_ida_e_volta_pelo_texto():
    assert dumps_recipe(loads_recipe(CANONICA)) == CANONICA


def test_json_schema_tem_a_uniao_de_passos():
    schema = recipe_json_schema()
    steps = schema["properties"]["steps"]["items"]
    assert steps["discriminator"]["propertyName"] == "op"
    assert {"teste_renomear", "teste_remover"} <= set(steps["discriminator"]["mapping"])
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["RemoverDeTeste"]["properties"]["id"]["pattern"] == r"^s[1-9]\d*$"


def test_cli_schema():
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.output) == recipe_json_schema()


def _exemplos():
    import wolfz.ops  # noqa: F401  (registra o catálogo)
    from wolfz.core.recipe import registered_ops

    for nome, cls in sorted(registered_ops().items()):
        if cls.__module__.startswith("wolfz."):
            for i, exemplo in enumerate(cls.examples):
                yield pytest.param(nome, exemplo["step"], id=f"{nome}-{i}")


@pytest.mark.parametrize(("op", "passo"), list(_exemplos()))
def test_todo_passo_salvo_abre_de_novo(op, passo):
    """O que o WolfzBR grava ele mesmo lê: a gravação omite os nulos, então
    campo que aceita nulo precisa ter padrão (o ``new`` do ``replace`` não
    tinha, e a receita salva não abria)."""
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "ida e volta",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": "s1", "op": op, **passo}],
        }
    )
    assert loads_recipe(dumps_recipe(receita)) == receita

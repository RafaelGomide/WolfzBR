"""Fixtures dos testes da receita."""

import pytest
from ops_de_teste import RemoverDeTeste, RenomearDeTeste  # noqa: F401  (registra as operações)


@pytest.fixture
def recipe_dict():
    return {
        "wolfz_version": "0.1",
        "name": "Vendas mensais",
        "created_at": "2026-10-16T14:00:00Z",
        "source": {"type": "excel", "sheet": "Vendas", "match": {"sheet_name_regex": r"Vendas \d{4}"}},
        "steps": [
            {"id": "s1", "op": "teste_renomear", "mapping": {"Vlr": "valor"}},
            {"id": "s2", "op": "teste_remover", "cols": ["obs"]},
        ],
    }

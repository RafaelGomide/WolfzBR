import pytest

from wolfz.core.naming import dedupe_names, to_snake_case


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Valor de Venda (R$)", "valor_de_venda_r"),
        ("Nº Pedido", "n_pedido"),
        ("﻿Regiao - Sigla", "regiao_sigla"),
        ("% Margem", "pct_margem"),
        ("2024", "c_2024"),
        ("***", "coluna"),
    ],
)
def test_to_snake_case(name, expected):
    assert to_snake_case(name) == expected


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["valor", "valor", "data"], ["valor", "valor_2", "data"]),
        (["a", "a", "a_2"], ["a", "a_3", "a_2"]),  # não colide com nome existente
        ([], []),
    ],
)
def test_dedupe_names(names, expected):
    assert dedupe_names(names) == expected

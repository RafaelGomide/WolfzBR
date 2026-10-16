import pytest

from wolfz.br.booleanos import parse_bool_br


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Sim", True),
        ("S", True),
        ("X", True),
        ("1", True),
        ("Verdadeiro", True),
        ("Não", False),
        ("NAO", False),
        ("N", False),
        ("0", False),
        (True, True),
        (False, False),
        ("", None),
        (None, None),
        ("talvez", None),
    ],
)
def test_parse_bool_br(value, expected):
    assert parse_bool_br(value) is expected


def test_parse_bool_br_vazio_e_falso():
    assert parse_bool_br("", empty_is_false=True) is False
    assert parse_bool_br(None, empty_is_false=True) is False

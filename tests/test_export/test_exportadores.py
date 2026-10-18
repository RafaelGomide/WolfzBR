from datetime import UTC, datetime

import pytest
from m_parser import parse_m
from m_sintaxe import check_m

from wolfz.core.recipe import Recipe, Source
from wolfz.export.m import m_list, m_text, recipe_to_m
from wolfz.export.python import bundle, recipe_to_python


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Valor", '"Valor"'),
        ('Nº "Pedido"', '"Nº ""Pedido"""'),
        ("a\r\nb\tc", '"a#(cr)#(lf)b#(tab)c"'),
        ("#(lf)", '"#(#)(lf)"'),
        ("# solto", '"# solto"'),
        ("\x01", '"#(0001)"'),
    ],
)
def test_m_text(value, expected):
    assert m_text(value) == expected
    check_m(expected)


def test_m_list():
    assert m_list(["a", 'b"']) == '{"a", "b"""}'


def _vazia() -> Recipe:
    return Recipe(
        wolfz_version="0.1",
        name="vazia",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source=Source(type="csv"),
    )


def test_receita_sem_passos():
    assert recipe_to_m(_vazia()).endswith("in\n    Fonte\n")
    script = recipe_to_python(_vazia())
    namespace: dict = {}
    exec(script, namespace)
    assert "def transform" in script


@pytest.mark.parametrize(
    "code",
    [
        'let a = "x in a',
        "let a = (1 in a",
        "let a = 1) in a",
        "let a = 1",
        "let a = True in a",
        "let a = 'x' in a",
        "/* sem fim",
    ],
)
def test_check_m_reprova(code):
    with pytest.raises(AssertionError):
        check_m(code)


# ---------------------------------------------------------------------------
# bundle: cópia de funções para o script
# ---------------------------------------------------------------------------

_TABELA = frozenset({"b", "a"})


def _helper_com_constante(v):
    return v in _TABELA


def test_bundle_copia_constantes_ordenadas():
    imports, code = bundle([_helper_com_constante])
    assert imports == []
    assert "_TABELA = frozenset({'a', 'b'})" in code


def test_bundle_recusa_constante_desconhecida():
    global _OBJETO
    _OBJETO = object()

    def usa_objeto():
        return _OBJETO

    with pytest.raises(TypeError, match="não sei copiar"):
        bundle([usa_objeto])


def test_parser_da_microsoft_reprova_m_quebrado():
    """O parser de verdade pega o que a checagem estrutural pega."""
    results = parse_m(['let a = "x in a', "let a = (1 in a", "let a = 1, in a", "let a = 1 in a"])
    assert [r["ok"] for r in results] == [False, False, False, True]

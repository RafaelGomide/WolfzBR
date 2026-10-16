import pytest

from wolfz.core.text import (
    clean_text,
    fix_mojibake,
    is_null_token,
    normalize_key,
    normalize_spaces,
    only_digits,
    remove_accents,
    strip_footnote_marks,
)


def test_remove_accents():
    assert remove_accents("Espírito Santo, São Paulo") == "Espirito Santo, Sao Paulo"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  a\xa0\xa0b  ", "a b"),
        ("a\tb\r\nc", "a b c"),
        ("a​b﻿", "ab"),  # zero-width e BOM
        ("São", "São"),  # acento decomposto (macOS) vira NFC
    ],
)
def test_normalize_spaces(text, expected):
    assert normalize_spaces(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("SÃO PAULO", "sao paulo"), ("são  paulo", "sao paulo"), (None, "")],
)
def test_normalize_key(text, expected):
    assert normalize_key(text) == expected


@pytest.mark.parametrize(("text", "expected"), [("123.456.789-09", "12345678909"), (None, "")])
def test_only_digits(text, expected):
    assert only_digits(text) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        (float("nan"), True),
        ("", True),
        ("#N/D", True),
        ("#VALOR!", True),
        ("Sem Informação", True),
        ("NULL", True),
        ("00/00/0000", True),
        ("-", False),  # traço é zero em formato contábil, não ausência
        ("0", False),
        ("Vitória", False),
    ],
)
def test_is_null_token(value, expected):
    assert is_null_token(value) is expected


def test_is_null_token_extra():
    assert is_null_token("Não se aplica", extra={"nao se aplica"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" 06.321.359/0001-47", "06.321.359/0001-47"),
        ("  Sem Informação ", None),
        ("a\xa0 b", "a b"),
        (None, None),
    ],
)
def test_clean_text(value, expected):
    assert clean_text(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SÃ£o Paulo", "São Paulo"),
        ("InformaÃ§Ã£o", "Informação"),
        ("SÃO PAULO", "SÃO PAULO"),  # legítimo, não reversível
        ("Vitória", "Vitória"),
        (None, None),
    ],
)
def test_fix_mojibake(text, expected):
    assert fix_mojibake(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Abacaxi*", "Abacaxi"),
        ("Receita líquida (1)", "Receita líquida"),
        ("Total²", "Total"),
        ("Ano 2024", "Ano 2024"),
        (None, None),
    ],
)
def test_strip_footnote_marks(text, expected):
    assert strip_footnote_marks(text) == expected

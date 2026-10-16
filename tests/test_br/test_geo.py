import pytest

from wolfz.br.geo import ibge_code_6, normalize_uf, split_municipio_uf


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ES", "ES"),
        ("es", "ES"),
        ("Espírito Santo", "ES"),
        ("ESPIRITO SANTO", "ES"),
        ("  são  paulo ", "SP"),
        ("Distrito Federal", "DF"),
        ("XX", None),
        (None, None),
    ],
)
def test_normalize_uf(value, expected):
    assert normalize_uf(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Alta Floresta D'Oeste (RO)", ("Alta Floresta D'Oeste", "RO")),  # SIDRA
        ("Vitória - ES", ("Vitória", "ES")),
        ("Vitória/ES", ("Vitória", "ES")),
        ("Vitória \u2013 es", ("Vitória", "ES")),  # meia-risca
        ("Vitória", ("Vitória", None)),
        ("Embu-Guaçu", ("Embu-Guaçu", None)),  # sufixo que não é UF não corta
        ("#N/D", (None, None)),
        (None, (None, None)),
    ],
)
def test_split_municipio_uf(text, expected):
    assert split_municipio_uf(text) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("3550308", "355030"),
        ("355030", "355030"),
        (3550308, "355030"),
        ("3550308.0", "355030"),
        ("35503", None),
        (None, None),
    ],
)
def test_ibge_code_6(code, expected):
    assert ibge_code_6(code) == expected

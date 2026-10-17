import pytest

from wolfz.core.ingest.cells import CellType, column_index, column_letter, from_a1, infer_type, to_a1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, CellType.EMPTY),
        ("", CellType.EMPTY),
        ("   ", CellType.EMPTY),
        ("12", CellType.NUMBER),
        ("-0.5", CellType.NUMBER),
        ("1e+22", CellType.NUMBER),
        ("2024-01-31 00:00:00", CellType.DATE),
        ("2024-01-31", CellType.DATE),
        ("true", CellType.BOOL),
        ("#N/A", CellType.ERROR),
        ("#N/D", CellType.ERROR),
        ("#DIV/0!", CellType.ERROR),
        ("1.234,56", CellType.TEXT),  # número brasileiro é trabalho da detecção
        ("01/02/2024", CellType.TEXT),
        ("São Paulo", CellType.TEXT),
    ],
)
def test_infer_type(value, expected):
    assert infer_type(value) is expected


@pytest.mark.parametrize(("col", "letter"), [(0, "A"), (25, "Z"), (26, "AA"), (701, "ZZ"), (702, "AAA")])
def test_letras_de_coluna(col, letter):
    assert column_letter(col) == letter
    assert column_index(letter) == col


def test_a1():
    assert to_a1(0, 0) == "A1"
    assert to_a1(9, 27) == "AB10"
    assert from_a1("AB10") == (9, 27)

from datetime import date, datetime

import pytest

from wolfz.br.datas import excel_serial_to_date, parse_date_br, parse_month_year


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("31/12/2024", date(2024, 12, 31)),
        ("31-12-2024", date(2024, 12, 31)),
        ("31.12.2024", date(2024, 12, 31)),
        ("31/12/24", date(2024, 12, 31)),
        ("1/2/2024", date(2024, 2, 1)),  # dia primeiro
        ("2024-12-31", date(2024, 12, 31)),
        ("2024-12-31T10:00:00", date(2024, 12, 31)),
        ("2024-12-31T10:00:00Z", date(2024, 12, 31)),
        ("31/12/2024 14:30:00", date(2024, 12, 31)),
        ("31-dez-2024", date(2024, 12, 31)),
        ("31 de dezembro de 2024", date(2024, 12, 31)),
        ("15-Mar-24", date(2024, 3, 15)),
        ("20241231", date(2024, 12, 31)),  # Receita Federal
        ("31122024", date(2024, 12, 31)),  # DATASUS
        ("45657", date(2024, 12, 31)),  # serial do Excel
        ("01/01/29", date(2029, 1, 1)),  # pivô de século do Excel
        ("01/01/30", date(1930, 1, 1)),
        ("31/02/2024", None),  # data impossível
        ("00/00/0000", None),
        ("00000000", None),
        ("31.12.9999", None),  # "sem data fim" de ERP
        ("01/01/1700", None),
        ("2024", None),  # ano solto não vira serial
        ("abc", None),
        (None, None),
        (datetime(2024, 5, 1, 10, 0), date(2024, 5, 1)),
        (date(2024, 5, 1), date(2024, 5, 1)),
    ],
)
def test_parse_date_br(value, expected):
    assert parse_date_br(value) == expected


@pytest.mark.parametrize(
    ("value", "eight_digits", "expected"),
    [
        ("01022024", "dmy", date(2024, 2, 1)),
        ("01022024", "ymd", None),
        ("20240102", "ymd", date(2024, 1, 2)),
        ("20240102", "dmy", None),
    ],
)
def test_parse_date_br_eight_digits(value, eight_digits, expected):
    assert parse_date_br(value, eight_digits=eight_digits) == expected


def test_parse_date_br_sem_serial():
    assert parse_date_br("45657", accept_excel_serial=False) is None


@pytest.mark.parametrize(
    "value",
    ["jan/24", "Janeiro de 2024", "JAN-2024", "01/2024", "1/24", "2024-01", "202401", "Competência 01/2024"],
)
def test_parse_month_year(value):
    assert parse_month_year(value) == date(2024, 1, 1)


@pytest.mark.parametrize("value", ["13/2024", "xyz/2024", None])
def test_parse_month_year_invalido(value):
    assert parse_month_year(value) is None


def test_parse_month_year_date():
    assert parse_month_year(date(2024, 3, 15)) == date(2024, 3, 1)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        (45292, date(2024, 1, 1)),
        ("45292,5", date(2024, 1, 1)),
        (1, date(1899, 12, 31)),
        (0, None),
        ("abc", None),
    ],
)
def test_excel_serial_to_date(serial, expected):
    assert excel_serial_to_date(serial) == expected

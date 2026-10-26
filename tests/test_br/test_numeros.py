import pytest

from wolfz.br.numeros import (
    decimal_provavel,
    format_brl,
    parse_brl,
    parse_ibge_value,
    parse_number_br,
    parse_percent_br,
    scale_from_unit,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.234,56", 1234.56),
        ("1234,56", 1234.56),
        ("-1.234,56", -1234.56),
        ("(1.234,56)", -1234.56),  # negativo contábil
        ("1.234,56-", -1234.56),  # menos no fim (SAP)
        ("R$ 1.234,56", 1234.56),
        ("US$ 10", 10.0),
        ("1,234.56", 1234.56),  # padrão americano
        ("1 234,56", 1234.56),  # espaço como milhar
        ("1\xa0234,56", 1234.56),  # espaço não separável
        ("1,5E+3", 1500.0),
        ("1.234", 1234.0),  # separador + 3 dígitos com decimal=',' é milhar
        ("1.234.567", 1234567.0),
        ("+12", 12.0),
        ("0,5", 0.5),
        (",5", 0.5),
        ("1.23.4", None),
        ("12%", None),  # percentual vai para parse_percent_br
        ("-", None),
        ("#N/D", None),
        ("abc", None),
        (None, None),
        (True, None),
        (7, 7.0),
        (2.5, 2.5),
        (float("nan"), None),
    ],
)
def test_parse_number_br(value, expected):
    assert parse_number_br(value) == expected


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ("1.234", {"decimal": "."}, 1.234),
        ("1,234", {"decimal": "."}, 1234.0),
        ("-", {"dash_is_zero": True}, 0.0),
        ("1.234,56 D", {"debit_negative": True}, -1234.56),
        ("1.234,56 C", {"debit_negative": True}, 1234.56),
        ("1.234,56 D", {}, 1234.56),
    ],
)
def test_parse_number_br_options(value, kwargs, expected):
    assert parse_number_br(value, **kwargs) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("R$ 1.234,56", 1234.56),
        ("(1.234,56)", -1234.56),
        ("R$ -", 0.0),
        ("-", 0.0),
        ("R$ 0,00", 0.0),
        ("", None),
    ],
)
def test_parse_brl(value, expected):
    assert parse_brl(value) == expected


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        (1234.56, {}, "R$ 1.234,56"),
        (-5, {}, "-R$ 5,00"),
        (0.004, {}, "R$ 0,00"),
        (-0.004, {}, "R$ 0,00"),
        (1234567.891, {"symbol": False}, "1.234.567,89"),
        (None, {}, None),
    ],
)
def test_format_brl(value, kwargs, expected):
    assert format_brl(value, **kwargs) == expected


@pytest.mark.parametrize(
    ("value", "bare", "expected"),
    [
        ("12,5%", "fraction", 0.125),
        ("12,5 %", "fraction", 0.125),
        ("0,125", "fraction", 0.125),
        ("12,5", "points", 0.125),
        ("abc", "fraction", None),
        (None, "fraction", None),
    ],
)
def test_parse_percent_br(value, bare, expected):
    result = parse_percent_br(value, bare=bare)
    assert result == (None if expected is None else pytest.approx(expected))


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("Mil Reais", 1_000),
        ("R$ milhões", 1_000_000),
        ("Bilhões de reais", 1_000_000_000),
        ("Toneladas", 1),
        ("Milímetros", 1),
        (None, 1),
    ],
)
def test_scale_from_unit(unit, expected):
    assert scale_from_unit(unit) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("-", (0.0, "zero_absoluto")),
        ("..", (None, "nao_se_aplica")),
        ("...", (None, "nao_disponivel")),
        ("X", (None, "omitido_sigilo")),
        ("0", (0.0, "zero_arredondado")),
        ("0.00", (0.0, "zero_arredondado")),
        ("5556", (5556.0, "valor")),
        ("12.5", (12.5, "valor")),
        ("abc", (None, "invalido")),
        (None, (None, "nao_disponivel")),
    ],
)
def test_parse_ibge_value(value, expected):
    assert parse_ibge_value(value) == expected


@pytest.mark.parametrize(
    ("valores", "esperado"),
    [
        (["8725.3480", "0.125", "1"], "."),  # número do Excel lido como texto
        (["0.5", "12"], "."),
        (["-29.06944444"], "."),
        (["R$ 1.5"], "."),
        (["1.234", "2,5"], ","),  # tem vírgula: padrão brasileiro
        (["1.234", "1.234.567"], ","),  # todo ponto com 3 dígitos: milhar
        (["104.000", "55.180"], ","),  # ambíguo: fica o padrão (use decimal=".")
        (["1.5E+3"], ","),
        (["abc.de", "v1.2x"], ","),
        ([None, "", "  ", 1.5, True], ","),
        ([], ","),
    ],
)
def test_decimal_provavel(valores, esperado):
    assert decimal_provavel(valores) == esperado


@pytest.mark.parametrize(("value", "expected"), [("4,22%", 0.0422), ("2,05%", 0.0205), ("0,7%", 0.007)])
def test_parse_percent_br_sem_resto_do_ponto_flutuante(value, expected):
    """4,22 / 100 em ponto flutuante é 0.042199999999999994, que ia assim para
    o CSV exportado."""
    assert parse_percent_br(value) == expected
    assert repr(parse_percent_br(value)) == repr(expected)

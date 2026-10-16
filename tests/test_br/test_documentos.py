import pytest

from wolfz.br.documentos import (
    clean_cep,
    clean_cnpj,
    clean_cpf,
    clean_cpf_cnpj,
    clean_phone,
    cnpj_is_valid,
    cpf_is_valid,
    format_cnpj,
    format_cpf,
)

CPF_VALIDO = "12345678909"
CNPJ_VALIDO = "11222333000181"
CNPJ_BB = "00000000000191"  # Banco do Brasil


@pytest.mark.parametrize(
    ("cpf", "expected"),
    [
        ("123.456.789-09", True),
        (CPF_VALIDO, True),
        ("123.456.789-00", False),
        ("111.111.111-11", False),  # todos iguais
        ("1234567890", False),
        (None, False),
    ],
)
def test_cpf_is_valid(cpf, expected):
    assert cpf_is_valid(cpf) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123.456.789-09", CPF_VALIDO),
        ("2345678909", "02345678909"),  # zero à esquerda perdido no Excel
        ("12345678909.0", CPF_VALIDO),
        (12345678909, CPF_VALIDO),
        ("***.456.789-**", "***456789**"),  # mascarado (LGPD)
        ("1,23457E+10", None),  # notação científica é irrecuperável
        ("1.2E+10", None),
        ("123456789012", None),
        ("#N/D", None),
        (None, None),
    ],
)
def test_clean_cpf(value, expected):
    assert clean_cpf(value) == expected


def test_clean_cpf_sem_completar_zeros():
    assert clean_cpf("2345678909", pad_zeros=False) is None


@pytest.mark.parametrize(
    ("cpf", "expected"),
    [(CPF_VALIDO, "123.456.789-09"), ("123", None), (None, None)],
)
def test_format_cpf(cpf, expected):
    assert format_cpf(cpf) == expected


@pytest.mark.parametrize(
    ("cnpj", "expected"),
    [
        ("11.222.333/0001-81", True),
        (CNPJ_VALIDO, True),
        (CNPJ_BB, True),
        ("11.222.333/0001-80", False),
        ("12ABC34501DE35", True),  # alfanumérico (IN RFB 2.229/2024)
        ("12.abc.345/01de-35", True),
        ("12ABC34501DE36", False),
        ("00000000000000", False),
        ("123", False),
        (None, False),
    ],
)
def test_cnpj_is_valid(cnpj, expected):
    assert cnpj_is_valid(cnpj) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("11.222.333/0001-81", CNPJ_VALIDO),
        ("191", CNPJ_BB),
        ("12.abc.345/01de-35", "12ABC34501DE35"),
        ("00.000.000/000E-20", "00000000000E20"),  # alfanumérico, não notação científica
        ("1,23457E+13", None),
        ("11222333000181.0", CNPJ_VALIDO),
        ("123456789012345", None),
        ("12.abc", None),
        (None, None),
    ],
)
def test_clean_cnpj(value, expected):
    assert clean_cnpj(value) == expected


def test_clean_cnpj_sem_completar_zeros():
    assert clean_cnpj("191", pad_zeros=False) is None


@pytest.mark.parametrize(
    ("cnpj", "expected"),
    [(CNPJ_VALIDO, "11.222.333/0001-81"), ("123", None), (None, None)],
)
def test_format_cnpj(cnpj, expected):
    assert format_cnpj(cnpj) == expected


@pytest.mark.parametrize(
    ("value", "person_type", "expected"),
    [
        ("2345678909", "F", "02345678909"),
        ("191", "PJ", CNPJ_BB),
        ("191", "Jurídica", CNPJ_BB),
        ("123.456.789-09", None, CPF_VALIDO),
        ("11.222.333/0001-81", None, CNPJ_VALIDO),
        ("12.abc.345/01de-35", None, "12ABC34501DE35"),
        ("191", None, None),  # 00000000191 e 00000000000191 são ambos válidos: ambíguo
        ("52998224725", None, "52998224725"),  # 11 dígitos sem ambiguidade é CPF
        (None, None, None),
    ],
)
def test_clean_cpf_cnpj(value, person_type, expected):
    assert clean_cpf_cnpj(value, person_type) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("29100-000", "29100000"),
        ("1310100", "01310100"),  # zero perdido (São Paulo capital)
        ("01310-100", "01310100"),
        ("29100", None),  # CEP de 5 dígitos é ambíguo
        ("00000-000", None),
        (None, None),
    ],
)
def test_clean_cep(value, expected):
    assert clean_cep(value) == expected


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ("(27) 99999-9999", {}, "+5527999999999"),
        ("+55 27 99999-9999", {}, "+5527999999999"),
        ("027 99999-9999", {}, "+5527999999999"),  # zero de longa distância
        ("0 21 27 99999-9999", {}, "+5527999999999"),  # código de operadora
        ("(27) 3333-4444", {}, "+552733334444"),  # fixo
        ("(27) 9999-8888", {}, "+5527999998888"),  # celular antigo ganha o 9
        ("(27) 9999-8888", {"add_ninth_digit": False}, "+552799998888"),
        ("99999-9999", {"default_ddd": 27}, "+5527999999999"),
        ("99999-9999", {}, None),  # sem DDD e sem padrão
        ("(20) 99999-9999", {}, None),  # DDD inexistente
        ("0800 123 4567", {}, None),  # não geográfico
        ("(27) 89999-9999", {}, None),  # 9 dígitos sem começar com 9
        (None, {}, None),
    ],
)
def test_clean_phone(value, kwargs, expected):
    assert clean_phone(value, **kwargs) == expected

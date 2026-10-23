"""API pública em Python (FH.A3): ``wolfz.__all__`` e ``wolfz.br.__all__``.

Depois da 1.0, tirar ou renomear um destes nomes quebra o script de quem
usa o WolfzBR como biblioteca: é versão major. Acrescentar é minor, e a
lista aqui é atualizada junto."""

import inspect

import wolfz
import wolfz.br

PUBLICA = {"RecipeError", "StepError", "__version__", "br", "load_recipe", "run"}

PUBLICA_BR = {
    "MESES",
    "UFS",
    "clean_cep",
    "clean_cnpj",
    "clean_cpf",
    "clean_cpf_cnpj",
    "clean_phone",
    "cnpj_is_valid",
    "cpf_is_valid",
    "excel_serial_to_date",
    "format_brl",
    "format_cnpj",
    "format_cpf",
    "ibge_code_6",
    "normalize_uf",
    "parse_bool_br",
    "parse_brl",
    "parse_date_br",
    "parse_ibge_value",
    "parse_month_year",
    "parse_number_br",
    "parse_percent_br",
    "scale_from_unit",
    "split_municipio_uf",
}


def test_nomes_publicos():
    assert set(wolfz.__all__) == PUBLICA
    assert set(wolfz.br.__all__) == PUBLICA_BR
    for nome in PUBLICA:
        assert hasattr(wolfz, nome)
    for nome in PUBLICA_BR:
        assert hasattr(wolfz.br, nome)


def test_funcoes_publicas_documentadas():
    funcoes = [getattr(wolfz, n) for n in ("run", "load_recipe")]
    funcoes += [v for n in PUBLICA_BR if callable(v := getattr(wolfz.br, n))]
    for f in funcoes:
        assert inspect.getdoc(f), f"{f.__name__} sem docstring"


def test_br_pelo_pacote_raiz():
    assert wolfz.br.clean_cpf("529.982.247-25") == "52998224725"
    assert wolfz.br.cpf_is_valid("52998224725")
    assert wolfz.br.parse_brl("R$ 1.234,56") == 1234.56

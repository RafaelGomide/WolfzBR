"""Testes property-based (hypothesis) dos parsers BR: ida e volta e
validação de documentos gerados."""

import string

from hypothesis import given
from hypothesis import strategies as st

from wolfz.br.documentos import (
    clean_cnpj,
    clean_cpf,
    cnpj_is_valid,
    cpf_is_valid,
    format_cnpj,
    format_cpf,
)
from wolfz.br.numeros import format_brl, parse_brl

valores = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)


@given(valores)
def test_parse_brl_inverte_format_brl(x):
    assert parse_brl(format_brl(x)) == round(x, 2)


@given(valores)
def test_parse_brl_inverte_format_brl_sem_simbolo(x):
    assert parse_brl(format_brl(x, symbol=False)) == round(x, 2)


@given(st.text(alphabet=string.digits, min_size=11, max_size=11))
def test_clean_cpf_inverte_format_cpf(cpf):
    assert clean_cpf(format_cpf(cpf)) == cpf


# Implementação independente da regra oficial, para não testar o código
# contra ele mesmo: cada caractere vale ord(c) - 48 (IN RFB 2.229/2024).
def _dv_cpf(base: str) -> str:
    for size in (9, 10):
        total = sum(int(d) * (size + 1 - i) for i, d in enumerate(base[:size]))
        base += str(total * 10 % 11 % 10)
    return base


def _dv_cnpj(base: str) -> str:
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for p in (pesos, [6, *pesos]):
        resto = sum((ord(c) - 48) * w for c, w in zip(base, p, strict=True)) % 11
        base += "0" if resto < 2 else str(11 - resto)
    return base


cpf_gerado = (
    st.text(alphabet=string.digits, min_size=9, max_size=9).map(_dv_cpf).filter(lambda c: len(set(c)) > 1)
)
cnpj_gerado = (
    st.text(alphabet=string.ascii_uppercase + string.digits, min_size=12, max_size=12)
    .map(_dv_cnpj)
    .filter(lambda c: len(set(c)) > 1)
)


@given(cpf_gerado)
def test_cpf_gerado_e_valido(cpf):
    assert cpf_is_valid(cpf)
    assert cpf_is_valid(format_cpf(cpf))


@given(cnpj_gerado)
def test_cnpj_alfanumerico_gerado_e_valido(cnpj):
    assert cnpj_is_valid(cnpj)
    assert cnpj_is_valid(format_cnpj(cnpj))
    assert clean_cnpj(format_cnpj(cnpj)) == cnpj


# Só os dígitos verificadores: trocar um caractere da base nem sempre é
# detectado pelo módulo 11 (restos 0 e 1 geram o mesmo DV).
@given(cnpj_gerado, st.sampled_from([12, 13]), st.sampled_from(string.digits))
def test_cnpj_com_dv_trocado_e_invalido(cnpj, pos, novo):
    alterado = cnpj[:pos] + novo + cnpj[pos + 1 :]
    if alterado != cnpj:
        assert not cnpj_is_valid(alterado)

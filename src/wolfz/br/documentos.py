"""CPF, CNPJ (inclusive alfanumérico), CEP e telefone."""

from __future__ import annotations

import re

from wolfz.core.text import is_null_token, normalize_key, normalize_spaces, only_digits


def _strip_float_suffix(s: str) -> str | None:
    """'12345678909.0' -> '12345678909'. Ferramentas que leem a coluna como
    número devolvem o documento com '.0'. Notação científica ('1,23457E+13')
    é irrecuperável: o Excel já descartou os dígitos finais."""
    if re.fullmatch(r"\d+\.0+", s):
        return s.split(".")[0]
    if re.search(r"\d[eE][+-]?\d", s):
        return None
    return s


def _prepare_id(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    s = normalize_spaces(str(value))
    if is_null_token(s):
        return None
    return _strip_float_suffix(s)


def cpf_is_valid(cpf: str | None) -> bool:
    """Valida os dígitos verificadores do CPF (aceita com ou sem máscara)."""
    d = only_digits(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d[i]) * (size + 1 - i) for i in range(size))
        dv = (total * 10) % 11 % 10
        if dv != int(d[size]):
            return False
    return True


_MASKED_CPF = re.compile(r"[*xX]{3}\.?(\d{3})\.?(\d{3})-?[*xX]{2}")


def clean_cpf(value: object, pad_zeros: bool = True) -> str | None:
    """CPF como texto de 11 dígitos, sem máscara.

    '123.456.789-09' -> '12345678909'
    '2345678909'     -> '02345678909'   zero à esquerda perdido no Excel
    '12345678909.0'  -> '12345678909'
    '***.456.789-**' -> '***456789**'   CPF mascarado (Portal da Transparência,
                                         LGPD): preserva os 6 dígitos centrais
    Não valida dígito verificador; use ``cpf_is_valid`` para a flag."""
    s = _prepare_id(value)
    if s is None:
        return None
    if m := _MASKED_CPF.fullmatch(s.replace(" ", "")):
        return f"***{m[1]}{m[2]}**"
    d = only_digits(s)
    if not d or len(d) > 11 or (len(d) < 11 and not pad_zeros):
        return None
    return d.zfill(11)


def format_cpf(cpf: str | None) -> str | None:
    d = only_digits(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else None


def _cnpj_check_digits(base12: str) -> str:
    # Regra do CNPJ alfanumérico (IN RFB 2.229/2024): cada caractere vale
    # ord(c) - 48, então dígitos valem eles mesmos e 'A' vale 17. Para CNPJ
    # só numérico o resultado é idêntico à regra antiga.
    weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    digits = base12
    for w in (weights, [6, *weights]):
        total = sum((ord(c) - 48) * p for c, p in zip(digits, w))
        rest = total % 11
        digits += "0" if rest < 2 else str(11 - rest)
    return digits[12:]


_CNPJ_FORMAT = re.compile(r"[A-Z0-9]{12}\d{2}")


def cnpj_is_valid(cnpj: str | None) -> bool:
    """Valida CNPJ numérico ou alfanumérico (em vigor desde julho de 2026)."""
    if cnpj is None:
        return False
    c = re.sub(r"[.\-/\s]", "", str(cnpj)).upper()
    if not _CNPJ_FORMAT.fullmatch(c) or c == c[0] * 14:
        return False
    return _cnpj_check_digits(c[:12]) == c[12:]


def clean_cnpj(value: object, pad_zeros: bool = True) -> str | None:
    """CNPJ como texto de 14 caracteres, sem máscara, letras em maiúscula.

    '12.345.678/0001-95' -> '12345678000195'
    '191'                -> '00000000000191'   Banco do Brasil depois do Excel
    '12.abc.345/01de-35' -> '12ABC34501DE35'   alfanumérico
    Não valida dígito verificador; use ``cnpj_is_valid`` para a flag."""
    s = _prepare_id(value)
    if s is None:
        return None
    c = re.sub(r"[.\-/\s]", "", s).upper()
    if c.isdigit():
        if len(c) > 14 or (len(c) < 14 and not pad_zeros):
            return None
        return c.zfill(14)
    return c if _CNPJ_FORMAT.fullmatch(c) else None


def format_cnpj(cnpj: str | None) -> str | None:
    if cnpj is None or len(cnpj) != 14:
        return None
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


_PF = {"f", "pf", "fisica", "pessoa fisica", "cpf"}
_PJ = {"j", "pj", "juridica", "pessoa juridica", "cnpj"}


def clean_cpf_cnpj(value: object, person_type: object = None) -> str | None:
    """Coluna única com CPF ou CNPJ ("CPF OU CNPJ DO SANCIONADO" no CEIS,
    "CPF/CNPJ do fornecedor" em ERPs).

    Com ``person_type`` ('F'/'J', 'PF'/'PJ', 'Física'/'Jurídica'), completa
    os zeros no tamanho certo. Sem ele, decide pelo tamanho e, quando os
    zeros foram perdidos, pelo dígito verificador: só completa se exatamente
    uma das leituras (CPF ou CNPJ) for válida. Ambíguo -> ``None``."""
    kind = normalize_key(person_type)
    if kind in _PF:
        return clean_cpf(value)
    if kind in _PJ:
        return clean_cnpj(value)
    s = _prepare_id(value)
    if s is None:
        return None
    c = re.sub(r"[.\-/\s]", "", s).upper()
    if not c.isdigit():
        return clean_cnpj(c)
    if len(c) > 11:
        return clean_cnpj(c)
    as_cpf, as_cnpj = c.zfill(11), c.zfill(14)
    cpf_ok, cnpj_ok = cpf_is_valid(as_cpf), cnpj_is_valid(as_cnpj)
    if cpf_ok and not cnpj_ok:
        return as_cpf
    if cnpj_ok and not cpf_ok:
        return as_cnpj
    return as_cpf if len(c) == 11 else None


def clean_cep(value: object) -> str | None:
    """CEP como 8 dígitos: '29100-000' -> '29100000'; '1310100' -> '01310100'.

    CEPs de São Paulo capital começam com 0 e perdem esse zero quando a
    coluna passa por Excel. CEP de 5 dígitos (anterior a 1992) é ambíguo e
    devolve ``None``."""
    s = _prepare_id(value)
    if s is None:
        return None
    d = only_digits(s)
    if len(d) == 7:
        d = "0" + d
    return d if len(d) == 8 and d != "00000000" else None


_DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34,
    35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62,
    63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85,
    86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}


def clean_phone(value: object, default_ddd: str | int | None = None, add_ninth_digit: bool = True) -> str | None:
    """Telefone para E.164: '(27) 99999-9999' -> '+5527999999999'.

    Trata '+55', zero de longa distância ('027...'), código de operadora
    ('0 21 27 ...'), número sem DDD (usa ``default_ddd``) e celular antigo de
    8 dígitos (acrescenta o 9). 0800/0300/4004 não são geográficos e
    devolvem ``None``, assim como DDD inexistente."""
    s = _prepare_id(value)
    if s is None:
        return None
    d = only_digits(s)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    elif d.startswith("0"):
        d = d[1:]
        if len(d) in (12, 13):  # código de operadora
            d = d[2:]
    if len(d) in (8, 9):
        if default_ddd is None:
            return None
        d = f"{int(default_ddd):02d}{d}"
    if len(d) not in (10, 11) or int(d[:2]) not in _DDDS:
        return None
    ddd, number = d[:2], d[2:]
    if len(number) == 8 and number[0] in "6789" and add_ninth_digit:
        number = "9" + number
    if len(number) == 9 and number[0] != "9":
        return None
    return f"+55{ddd}{number}"

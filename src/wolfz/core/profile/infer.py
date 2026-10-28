"""Inferência do tipo brasileiro de uma coluna de texto."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from wolfz.br.booleanos import parse_bool_br
from wolfz.br.datas import parse_date_br, parse_datetime_br, parse_month_year
from wolfz.br.documentos import cnpj_is_valid, cpf_is_valid
from wolfz.br.numeros import parse_brl, parse_number_br, parse_percent_br
from wolfz.core.text import clean_text, only_digits


def _looks_brl(v: str) -> bool:
    return "R$" in v or bool(re.fullmatch(r"\(?-?\d{1,3}(\.\d{3})*,\d{2}\)?-?", v))


_DETECTORS: list[tuple[str, Callable[[str], bool]]] = [
    ("cnpj", lambda v: cnpj_is_valid(v) and len(re.sub(r"\W", "", v)) == 14),
    ("cpf", lambda v: cpf_is_valid(v) and len(only_digits(v)) == 11),
    ("cep", lambda v: bool(re.fullmatch(r"\d{5}-\d{3}", v))),
    ("data", lambda v: parse_date_br(v, accept_excel_serial=False) is not None),
    ("mes_ano", lambda v: parse_month_year(v) is not None),
    ("percentual", lambda v: "%" in v and parse_percent_br(v) is not None),
    ("codigo", lambda v: v.isdigit() and v.startswith("0") and len(v) > 1),
    ("moeda", lambda v: _looks_brl(v) and parse_brl(v) is not None),
    ("numero", lambda v: parse_number_br(v) is not None),
    ("booleano", lambda v: parse_bool_br(v) is not None),
]


def _com_hora(vals: list[str]) -> float:
    """Fração dos valores com hora diferente de 00:00. Refina uma coluna que
    já é ``data``: não entra em ``_DETECTORS``, para não mudar o tipo de
    nenhuma outra coluna (F4, critério 3)."""
    lidos = [parse_datetime_br(v, accept_excel_serial=False) for v in vals]
    return sum(
        d is not None and (d.hour, d.minute, d.second, d.microsecond) != (0, 0, 0, 0) for d in lidos
    ) / len(vals)


def infer_br_type(values: Iterable[object], sample: int = 2000, min_rate: float = 0.9) -> tuple[str, float]:
    """Sugere o tipo de uma coluna de texto e a taxa de acerto.

    Devolve, por exemplo, ('moeda', 0.97) ou ('texto', 1.0). 'data_hora' é
    uma coluna 'data' em que mais da metade dos valores tem hora. 'codigo'
    sinaliza coluna numérica com zero à esquerda (código IBGE, matrícula,
    conta contábil) que deve continuar texto. Os detectores são testados do
    mais específico para o mais genérico; vence o primeiro com taxa
    >= ``min_rate`` entre os valores não nulos da amostra."""
    vals = [s for v in values if (s := clean_text(v)) is not None][:sample]
    if not vals:
        return "vazio", 1.0
    for name, test in _DETECTORS:
        rate = sum(test(v) for v in vals) / len(vals)
        if rate >= min_rate:
            leading_zero = any(v.startswith("0") and v[1:2].isdigit() for v in vals)
            if name == "codigo" or (name == "numero" and leading_zero):
                return "codigo", rate
            if name == "data" and _com_hora(vals) > 0.5:
                return "data_hora", rate
            return name, rate
    return "texto", 1.0

"""Datas em formato brasileiro, mês/ano e serial do Excel."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from wolfz.br.constants import MESES
from wolfz.core.text import is_null_token, normalize_spaces, remove_accents

_EXCEL_EPOCH = date(1899, 12, 30)


def excel_serial_to_date(serial: float | int | str) -> date | None:
    """45292 -> 2024-01-01.

    Datas que o Excel exporta como número (célula formatada como "Geral" ou
    coluna lida pelo pandas/Polars sem formatação). A base 1899-12-30 já
    compensa o bug do ano bissexto de 1900 do Lotus/Excel."""
    try:
        n = float(str(serial).replace(",", "."))
    except ValueError:
        return None
    if not 1 <= n < 2_958_466:  # 9999-12-31
        return None
    return _EXCEL_EPOCH + timedelta(days=int(n))


_DATE_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DATE_DMY = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})")
_DATE_TEXT = re.compile(
    r"(\d{1,2})(?:\s+de\s+|[\s/\-.])([a-z]{3,9})\.?(?:\s+de\s+|[\s/\-.])(\d{4}|\d{2})"
)
_TIME_SUFFIX = re.compile(r"[ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def _make_date(y: int, m: int, d: int) -> date | None:
    # Ano 9999 é o "sem data fim" de ERPs (SAP grava 31.12.9999); ano < 1800
    # é lixo de digitação ou data zerada.
    if not 1800 <= y < 9999:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _full_year(y: str, century_pivot: int) -> int:
    if len(y) == 4:
        return int(y)
    yy = int(y)
    return 2000 + yy if yy < century_pivot else 1900 + yy


def parse_date_br(
    value: object,
    eight_digits: str = "auto",
    century_pivot: int = 30,
    accept_excel_serial: bool = True,
) -> date | None:
    """Converte data em qualquer formato comum no Brasil para ``date``.

    Aceita:
      '31/12/2024'  '31-12-2024'  '31.12.2024'  '31/12/24'   dia primeiro
      '2024-12-31'  '2024-12-31T10:00:00'                     ISO
      '31/12/2024 14:30:00'                                   hora é descartada
      '31-dez-2024'  '31 de dezembro de 2024'  '15-Mar-24'    mês por extenso
      '20241231' (Receita Federal) / '31122024' (DATASUS)     8 dígitos
      '45657'                                                 serial do Excel

    Datas impossíveis (31/02), zeradas ('00/00/0000', '00000000') e o
    'sem data fim' de ERP (ano 9999) viram ``None``.

    ``eight_digits``: 'ymd', 'dmy' ou 'auto' (usa a única leitura válida; se
    as duas forem válidas, prefere ymd). ``century_pivot``: ano de 2 dígitos
    abaixo dele é 20xx, senão 19xx; o padrão 30 é a mesma regra do Excel e
    do Windows ('29' -> 2029, '30' -> 1930), então o resultado bate com o
    que o analista vê na planilha. Serial do Excel só é aceito entre 20000 e
    80000 (1954–2119) para que um ano solto como '2024' não vire data."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = normalize_spaces(str(value))
    if is_null_token(s):
        return None
    s = _TIME_SUFFIX.sub("", s)
    k = remove_accents(s).lower()

    if m := _DATE_ISO.fullmatch(k):
        return _make_date(int(m[1]), int(m[2]), int(m[3]))
    if m := _DATE_DMY.fullmatch(k):
        return _make_date(_full_year(m[3], century_pivot), int(m[2]), int(m[1]))
    if m := _DATE_TEXT.fullmatch(k):
        month = MESES.get(m[2])
        return _make_date(_full_year(m[3], century_pivot), month, int(m[1])) if month else None
    if re.fullmatch(r"\d{8}", k):
        ymd = _make_date(int(k[:4]), int(k[4:6]), int(k[6:]))
        dmy = _make_date(int(k[4:]), int(k[2:4]), int(k[:2]))
        if eight_digits == "ymd":
            return ymd
        if eight_digits == "dmy":
            return dmy
        return ymd or dmy
    if accept_excel_serial and re.fullmatch(r"\d{5}([.,]\d+)?", k):
        if 20_000 <= float(k.replace(",", ".")) <= 80_000:
            return excel_serial_to_date(k)
    return None


def parse_month_year(value: object, century_pivot: int = 30) -> date | None:
    """Mês/ano para o 1º dia do mês.

    'jan/24' 'Janeiro de 2024' 'JAN-2024' '01/2024' '1/24' '2024-01' '202401'
    -> date(2024, 1, 1). Cabeçalhos de relatório mensal e colunas de
    competência ("Competência 03/2025") quase sempre vêm assim."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.replace(day=1)
    k = remove_accents(normalize_spaces(str(value))).lower()
    k = re.sub(r"^(competencia|comp\.?|ref\.?|mes)\s*:?\s*", "", k)
    month = year = None
    if m := re.fullmatch(r"([a-z]{3,9})\.?\s*(?:de\s+|[/\-.\s])?\s*(\d{4}|\d{2})", k):
        month, year = MESES.get(m[1]), _full_year(m[2], century_pivot)
    elif m := re.fullmatch(r"(\d{1,2})[/\-.](\d{4}|\d{2})", k):
        month, year = int(m[1]), _full_year(m[2], century_pivot)
    elif m := re.fullmatch(r"(\d{4})[/\-.]?(\d{2})", k):
        month, year = int(m[2]), int(m[1])
    if not month or not 1 <= month <= 12:
        return None
    return _make_date(year, month, 1)

"""Funções de limpeza e normalização para dados brasileiros.

Organizado em duas camadas:

1. Funções de valor (``parse_*``, ``clean_*``): recebem UM valor bruto e
   devolvem o valor limpo ou ``None``. Não dependem de Polars, são fáceis de
   testar e de traduzir para Power Query M.
2. Funções de tabela (``DataFrame`` Polars): aplicam as de valor em colunas
   inteiras e cuidam de estrutura (cabeçalho, totais, linhas vazias).

Regra geral: nenhuma função "chuta" em silêncio. Quando o valor é ambíguo ou
irrecuperável, o retorno é ``None`` — melhor um nulo visível do que um número
errado no relatório.

Casos tratados aqui foram observados em bases reais: ANP (preços de
combustíveis), IBGE/SIDRA, Portal da Transparência (CEIS), Receita Federal,
TSE e DATASUS, além de exportações típicas de Excel e ERPs (SAP, TOTVS).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, datetime

import polars as pl

from .utils import (
    MESES,
    UFS,
    dedupe_names,
    excel_serial_to_date,
    is_null_token,
    normalize_key,
    normalize_spaces,
    only_digits,
    remove_accents,
    to_snake_case,
)

# ===========================================================================
# Texto
# ===========================================================================

def clean_text(value: object, extra_nulls: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Limpeza básica de qualquer célula de texto.

    Remove espaços nas pontas e repetidos, espaço não separável (\\xa0, muito
    comum em cópia de sistema web e PDF), caracteres invisíveis e BOM, e
    converte marcadores de ausência ("#N/D", "Sem Informação", "NULL"...) em
    ``None``. Ex.: ' 06.321.359/0001-47' (CNPJ com espaço à esquerda, como
    vem no CSV da ANP) -> '06.321.359/0001-47'."""
    if value is None:
        return None
    s = normalize_spaces(str(value))
    return None if is_null_token(s, extra_nulls) else s


_MOJIBAKE_MARKERS = ("Ã", "Â", "â€")


def fix_mojibake(text: str | None) -> str | None:
    """Conserta texto UTF-8 que foi lido como Latin-1/cp1252.

    'SÃ£o Paulo' -> 'São Paulo'; 'InformaÃ§Ã£o' -> 'Informação'.
    Acontece quando um arquivo passa por dois sistemas com encodings
    diferentes. Tenta desfazer até duas camadas; se o texto não for
    reversível (ex.: 'SÃO PAULO' legítimo), devolve o original."""
    if text is None or not any(m in text for m in _MOJIBAKE_MARKERS):
        return text
    for _ in range(2):
        fixed = None
        for enc in ("cp1252", "latin-1"):
            try:
                fixed = text.encode(enc).decode("utf-8")
                break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        if fixed is None or fixed == text:
            break
        text = fixed
        if not any(m in text for m in _MOJIBAKE_MARKERS):
            break
    return text


_FOOTNOTE = re.compile(r"\s*(\*+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\(\d{1,2}\))\s*$")


def strip_footnote_marks(text: str | None) -> str | None:
    """Remove marca de nota de rodapé no fim do rótulo.

    'Abacaxi*' -> 'Abacaxi' (SIDRA); 'Receita líquida (1)' -> 'Receita
    líquida'; 'Total²' -> 'Total'. Sem isso, a mesma categoria aparece com e
    sem asterisco em anos diferentes e não agrupa."""
    if text is None:
        return None
    return _FOOTNOTE.sub("", text)


# ===========================================================================
# Números
# ===========================================================================

_CURRENCY = re.compile(r"R\$|US\$|U\$|€|\$|\bBRL\b|\bUSD\b|\bEUR\b", re.I)
_DASHES = {"-", "–", "—"}


def _normalize_separators(s: str, decimal: str) -> str | None:
    """Converte '1.234,56' / '1,234.56' / '1234,56' para '1234.56'."""
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        integer, _, frac = s.rpartition(dec)
        if not re.fullmatch(rf"\d{{1,3}}(\{thou}\d{{3}})*|\d+", integer):
            return None
        s = integer.replace(thou, "") + "." + frac
    elif has_comma:
        if s.count(",") > 1:
            if not re.fullmatch(r"\d{1,3}(,\d{3})+", s):
                return None
            s = s.replace(",", "")
        elif decimal == "." and re.fullmatch(r"\d{1,3},\d{3}", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        if s.count(".") > 1:
            if not re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
                return None
            s = s.replace(".", "")
        elif decimal == "," and re.fullmatch(r"\d{1,3}\.\d{3}", s):
            # '1.234' no padrão BR é mil duzentos e trinta e quatro.
            s = s.replace(".", "")
    return s if re.fullmatch(r"\d+(\.\d+)?|\.\d+", s) else None


def parse_number_br(
    value: object,
    decimal: str = ",",
    dash_is_zero: bool = False,
    debit_negative: bool = False,
) -> float | None:
    """Converte número em formato brasileiro (ou misto) para float.

    Aceita:
      '1.234,56'  '1234,56'  '-1.234,56'  '(1.234,56)'   negativo contábil
      '1.234,56-'                                        menos no fim (SAP)
      '1.234,56 D' / 'C'      débito/crédito (``debit_negative=True`` -> D < 0)
      'R$ 1.234,56'  'US$ 10'                            símbolo de moeda
      '1,234.56'                                         padrão americano
      '1 234,56'                                         espaço como milhar
      '1,5E+3'                                           notação científica

    ``decimal`` resolve o único caso realmente ambíguo, um separador seguido
    de exatamente 3 dígitos: '1.234' vale 1234 com decimal=',' (padrão BR) e
    1.234 com decimal='.'. Use decimal='.' para bases que publicam ponto
    decimal (SIDRA via API, alguns anos do TSE).

    '-' sozinho vira 0 se ``dash_is_zero`` (formato contábil do Excel), senão
    ``None``. Valor com '%' devolve ``None``: use ``parse_percent_br``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    s = normalize_spaces(str(value))
    if "%" in s:
        return None
    s = _CURRENCY.sub("", s).strip()
    if s in _DASHES:
        return 0.0 if dash_is_zero else None
    if is_null_token(s):
        return None

    negative = False
    m = re.fullmatch(r"(.*\d)\s*([DdCc])", s)
    if m:
        s = m.group(1).strip()
        negative = debit_negative and m.group(2).upper() == "D"
    if s.startswith("(") and s.endswith(")"):
        negative, s = not negative, s[1:-1].strip()
    if s.endswith("-"):
        negative, s = not negative, s[:-1].strip()
    if s[:1] in _DASHES:
        negative, s = not negative, s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()
    s = _CURRENCY.sub("", s).replace(" ", "")

    if re.fullmatch(r"\d+([.,]\d+)?[eE][+-]?\d+", s):
        number = float(s.replace(",", "."))
    else:
        normalized = _normalize_separators(s, decimal)
        if normalized is None:
            return None
        number = float(normalized)
    return -number if negative else number


def parse_brl(value: object, debit_negative: bool = False) -> float | None:
    """Moeda brasileira: 'R$ 1.234,56', '(1.234,56)', 'R$ -' (= 0).

    Igual a ``parse_number_br`` com decimal=',' e '-' valendo zero, que é
    como o formato contábil do Excel exibe zero."""
    return parse_number_br(value, decimal=",", dash_is_zero=True, debit_negative=debit_negative)


def parse_percent_br(value: object, bare: str = "fraction") -> float | None:
    """Percentual para fração: '12,5%' -> 0.125.

    Sem o símbolo '%', o significado depende da base, então é explícito:
    ``bare='fraction'`` trata '0,125' como 0.125; ``bare='points'`` trata
    '12,5' como 12,5% -> 0.125. Nunca decide valor a valor, porque uma
    coluna com 0,5 e 50 ficaria com escalas misturadas."""
    if value is None:
        return None
    s = normalize_spaces(str(value))
    if "%" in s:
        n = parse_number_br(s.replace("%", ""))
        return None if n is None else n / 100
    n = parse_number_br(s)
    if n is None:
        return None
    return n / 100 if bare == "points" else n


def scale_from_unit(unit: str | None) -> int:
    """Multiplicador embutido na unidade de medida.

    'Mil Reais' -> 1000 (SIDRA); 'R$ milhões' -> 1_000_000; 'Toneladas' -> 1.
    Tabelas do IBGE e demonstrativos financeiros publicam valores já
    divididos; somar colunas com escalas diferentes é um erro clássico."""
    k = normalize_key(unit)
    if re.search(r"\b(bilhoes|bilhao|bi)\b", k):
        return 1_000_000_000
    if re.search(r"\b(milhoes|milhao|mi)\b", k):
        return 1_000_000
    if re.search(r"\b(mil|milhares)\b", k):
        return 1_000
    return 1


_IBGE_SIGNS: dict[str, tuple[float | None, str]] = {
    "-": (0.0, "zero_absoluto"),
    "..": (None, "nao_se_aplica"),
    "...": (None, "nao_disponivel"),
    "x": (None, "omitido_sigilo"),
}


def parse_ibge_value(value: object, decimal: str = ".") -> tuple[float | None, str]:
    """Valor de tabela do IBGE com os sinais convencionais.

    Devolve (valor, situação):
      '-'    -> (0.0,  'zero_absoluto')     zero não resultante de arredondamento
      '..'   -> (None, 'nao_se_aplica')
      '...'  -> (None, 'nao_disponivel')
      'X'    -> (None, 'omitido_sigilo')    omitido para não identificar o informante
      '0'    -> (0.0,  'zero_arredondado')  valor pequeno arredondado para zero
      '5556' -> (5556.0, 'valor')

    A distinção importa: '-' entra numa soma como zero; '...' e 'X' não podem
    virar zero, senão o total fica subestimado sem ninguém perceber."""
    if value is None:
        return None, "nao_disponivel"
    s = normalize_spaces(str(value))
    sign = _IBGE_SIGNS.get(s.lower())
    if sign:
        return sign
    if re.fullmatch(r"-?0([.,]0+)?", s):
        return 0.0, "zero_arredondado"
    n = parse_number_br(s, decimal=decimal)
    return (n, "valor") if n is not None else (None, "invalido")


# ===========================================================================
# Datas
# ===========================================================================

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


# ===========================================================================
# Booleanos
# ===========================================================================

_TRUE = {"sim", "s", "x", "v", "verdadeiro", "true", "t", "1", "yes", "y", "ok"}
_FALSE = {"nao", "n", "falso", "f", "false", "0", "no"}


def parse_bool_br(value: object, empty_is_false: bool = False) -> bool | None:
    """'Sim'/'S'/'X'/'1' -> True; 'Não'/'N'/'0' -> False.

    ``empty_is_false=True`` para colunas de "marque com X", em que célula
    vazia significa não."""
    if isinstance(value, bool):
        return value
    k = normalize_key(value)
    if not k:
        return False if empty_is_false else None
    if k in _TRUE:
        return True
    if k in _FALSE:
        return False
    return None


# ===========================================================================
# Documentos e identificadores
# ===========================================================================

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


_UF_BY_KEY = {normalize_key(name): uf for uf, name in UFS.items()} | {uf.lower(): uf for uf in UFS}


def normalize_uf(value: object) -> str | None:
    """'ES', 'es', 'Espírito Santo', 'ESPIRITO SANTO' -> 'ES'."""
    return _UF_BY_KEY.get(normalize_key(value))


_MUN_UF = (
    re.compile(r"(.+?)\s*\(([A-Za-z]{2})\)"),      # Alta Floresta D'Oeste (RO)  [SIDRA]
    re.compile(r"(.+?)\s*[-–/]\s*([A-Za-z]{2})"),  # Vitória - ES / Vitória/ES
)


def split_municipio_uf(text: object) -> tuple[str | None, str | None]:
    """Separa município e UF quando vêm no mesmo campo.

    'Alta Floresta D'Oeste (RO)' -> ("Alta Floresta D'Oeste", 'RO')
    'Vitória - ES' -> ('Vitória', 'ES');  'Vitória' -> ('Vitória', None).
    Só separa se o sufixo for uma UF real, para não cortar nomes como
    'Embu-Guaçu'."""
    s = clean_text(text)
    if s is None:
        return None, None
    for pattern in _MUN_UF:
        if (m := pattern.fullmatch(s)) and m[2].upper() in UFS:
            return m[1].strip(), m[2].upper()
    return s, None


def ibge_code_6(code: object) -> str | None:
    """Código de município IBGE de 7 dígitos -> 6 dígitos.

    DATASUS (SIM, SINASC, SIH, CNES) usa 6 dígitos, sem o dígito
    verificador: '3550308' -> '355030'. Para cruzar DATASUS com IBGE, faça o
    join pelos 6 primeiros dígitos em vez de tentar reconstruir o sétimo."""
    d = only_digits(_prepare_id(code))
    return d[:6] if len(d) in (6, 7) else None


# ===========================================================================
# Inferência de tipo
# ===========================================================================

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


def infer_br_type(values: Iterable[object], sample: int = 2000, min_rate: float = 0.9) -> tuple[str, float]:
    """Sugere o tipo de uma coluna de texto e a taxa de acerto.

    Devolve, por exemplo, ('moeda', 0.97) ou ('texto', 1.0). 'codigo'
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
            if name == "codigo" or (name == "numero" and any(v.startswith("0") and v[1:2].isdigit() for v in vals)):
                return "codigo", rate
            return name, rate
    return "texto", 1.0


# ===========================================================================
# Tabela (Polars)
# ===========================================================================

_DTYPES: dict[Callable, pl.DataType] = {
    parse_number_br: pl.Float64, parse_brl: pl.Float64, parse_percent_br: pl.Float64,
    parse_date_br: pl.Date, parse_month_year: pl.Date, parse_bool_br: pl.Boolean,
}


def apply_parser(
    df: pl.DataFrame,
    columns: str | list[str],
    parser: Callable[[object], object],
    dtype: pl.DataType | None = None,
    suffix: str | None = None,
) -> pl.DataFrame:
    """Aplica uma função de valor a colunas inteiras.

    O parser roda uma vez por valor DISTINTO e o resultado é mapeado de
    volta, o que é ordens de grandeza mais rápido que linha a linha em
    colunas repetitivas (datas, categorias, UFs). Com ``suffix`` a coluna
    original é mantida e a convertida ganha um nome novo
    ('valor' -> 'valor_num'), para auditar o antes/depois.

    Ex.: apply_parser(df, ["valor_venda"], parse_brl)
         apply_parser(df, "data", lambda v: parse_date_br(v, eight_digits="dmy"), pl.Date)"""
    columns = [columns] if isinstance(columns, str) else columns
    dtype = dtype or _DTYPES.get(parser, pl.String)
    exprs = []
    for col in columns:
        uniques = df.get_column(col).drop_nulls().unique().to_list()
        mapping = {u: parser(u) for u in uniques}
        exprs.append(
            pl.col(col)
            .replace_strict(list(mapping), list(mapping.values()), default=None, return_dtype=dtype)
            .alias(f"{col}{suffix}" if suffix else col)
        )
    return df.with_columns(exprs)


def clean_column_names(df: pl.DataFrame) -> pl.DataFrame:
    """Nomes de coluna em snake_case, sem acento, sem BOM, sem repetição.

    'Valor de Venda' -> 'valor_de_venda'; '\\ufeffRegiao - Sigla' ->
    'regiao_sigla'; duas colunas 'Valor' -> 'valor', 'valor_2'."""
    names = dedupe_names([to_snake_case(c) for c in df.columns])
    return df.rename(dict(zip(df.columns, names)))


def normalize_text_columns(
    df: pl.DataFrame,
    columns: list[str] | None = None,
    extra_nulls: frozenset[str] | set[str] = frozenset(),
) -> pl.DataFrame:
    """``clean_text`` vetorizado em todas as colunas de texto.

    Espaços, caracteres invisíveis e acentos decompostos são tratados
    no Polars; marcadores de nulo são identificados entre os valores
    distintos de cada coluna e trocados por null."""
    columns = columns or [c for c, t in df.schema.items() if t == pl.String]
    df = df.with_columns(
        pl.col(c)
        .str.normalize("NFC")
        .str.replace_all("[​‌‍⁠﻿­]", "")
        .str.replace_all(r"[\s    　]+", " ")
        .str.strip_chars()
        for c in columns
    )
    exprs = []
    for c in columns:
        tokens = [v for v in df.get_column(c).drop_nulls().unique().to_list() if is_null_token(v, extra_nulls)]
        if tokens:
            exprs.append(pl.when(pl.col(c).is_in(tokens)).then(None).otherwise(pl.col(c)).alias(c))
    return df.with_columns(exprs) if exprs else df


def _is_blank(col: str) -> pl.Expr:
    return pl.col(col).is_null() | (pl.col(col).cast(pl.String).str.strip_chars() == "")


def drop_empty_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Remove linhas em que todas as células estão vazias."""
    return df.filter(~pl.all_horizontal(_is_blank(c) for c in df.columns))


def drop_empty_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Remove colunas 100% vazias (colunas de espaçamento de relatório,
    'Valor de Compra' que nunca é preenchido)."""
    keep = [c for c in df.columns if not df.select(_is_blank(c).all()).item()]
    return df.select(keep)


def drop_repeated_headers(df: pl.DataFrame, min_match: float = 0.8) -> pl.DataFrame:
    """Remove linhas que repetem o cabeçalho no meio dos dados.

    Aparece quando vários relatórios paginados ou vários arquivos mensais
    são colados um embaixo do outro. Use antes de ``clean_column_names``:
    a comparação é com o nome original da coluna."""
    hits = pl.sum_horizontal(
        (pl.col(c).cast(pl.String).str.strip_chars().str.to_lowercase() == c.strip().lower()).fill_null(False)
        for c in df.columns
    )
    return df.filter(hits < max(1, round(min_match * len(df.columns))))


_TOTAL_LABEL = r"(?i)^\s*((sub\s*-?\s*)?total|soma|consolidado)\b"


def drop_total_rows(
    df: pl.DataFrame,
    label_columns: list[str] | None = None,
    pattern: str = _TOTAL_LABEL,
    return_removed: bool = False,
) -> pl.DataFrame | tuple[pl.DataFrame, pl.DataFrame]:
    """Remove linhas de total/subtotal ('Total', 'TOTAL GERAL', 'Subtotal
    Região Sul', 'Soma').

    Procura o rótulo nas duas primeiras colunas de texto (ou em
    ``label_columns``): com células mescladas, o 'Total' costuma cair na
    segunda coluna. 'Totalmente' não casa, mas uma empresa chamada 'Total
    Distribuidora' casaria — por isso ``return_removed=True`` devolve também
    as linhas descartadas, para conferência."""
    if label_columns is None:
        label_columns = [c for c, t in df.schema.items() if t == pl.String][:2]
    is_total = pl.any_horizontal(pl.col(c).str.contains(pattern).fill_null(False) for c in label_columns)
    kept = df.filter(~is_total)
    return (kept, df.filter(is_total)) if return_removed else kept


def fill_down(df: pl.DataFrame, columns: str | list[str]) -> pl.DataFrame:
    """Preenche para baixo células vazias de colunas de categoria.

    Desfaz célula mesclada na vertical ('Região' mesclada sobre 5 linhas) e
    relatório agrupado que só escreve o grupo na primeira linha."""
    columns = [columns] if isinstance(columns, str) else columns
    return df.with_columns(
        pl.when(_is_blank(c)).then(None).otherwise(pl.col(c)).forward_fill().alias(c) for c in columns
    )


def promote_header(df: pl.DataFrame, n_rows: int = 1, sep: str = "_") -> pl.DataFrame:
    """Usa as ``n_rows`` primeiras linhas como cabeçalho.

    Para tabela lida com ``has_header=False`` ou que tem título acima do
    cabeçalho real (corte as linhas de título antes com ``df.slice``). Com
    2+ linhas, as superiores são preenchidas para a direita (célula mesclada
    na horizontal) e as partes são unidas:
        | 2024 |      | 2025 |      |        ->  2024_Jan | 2024_Fev | ...
        | Jan  | Fev  | Jan  | Fev  |"""
    header = [list(r) for r in df.head(n_rows).iter_rows()]
    for row in header[:-1]:
        last = None
        for j, v in enumerate(row):
            if v is None or str(v).strip() == "":
                row[j] = last
            else:
                last = v
    names = []
    for j in range(df.width):
        parts: list[str] = []
        for row in header:
            v = row[j]
            if v is not None and (p := normalize_spaces(str(v))) and (not parts or parts[-1] != p):
                parts.append(p)
        names.append(sep.join(parts) or f"coluna_{j + 1}")
    names = dedupe_names(names)
    return df.slice(n_rows).rename(dict(zip(df.columns, names)))

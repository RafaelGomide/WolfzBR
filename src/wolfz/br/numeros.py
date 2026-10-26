"""Números em formato brasileiro: moeda, percentual, escala e sinais do IBGE.

Regra geral: nenhuma função "chuta" em silêncio. Quando o valor é ambíguo ou
irrecuperável, o retorno é ``None`` — melhor um nulo visível do que um número
errado no relatório.
"""

from __future__ import annotations

import re

from wolfz.br.constants import NULL_TOKENS
from wolfz.core.text import is_null_token, normalize_key, normalize_spaces

_CURRENCY = re.compile(r"R\$|US\$|U\$|€|\$|\bBRL\b|\bUSD\b|\bEUR\b", re.I)
_DASHES = {"-", "\u2013", "\u2014"}  # hífen, meia-risca, travessão


# Número simples, que o caminho completo leria do mesmo jeito: 'R$' opcional,
# sinal, parte inteira (com milhar só onde não é ambíguo) e decimais. Uma
# coluna de 1 milhão de valores passa por aqui sem as normalizações e as
# regex do caminho completo (FH.B2).
_SIMPLES = {
    ",": re.compile(r"(?:R\$ ?)?(?P<n>(-?)([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)(?:,([0-9]+))?)"),
    ".": re.compile(r"(?:R\$ ?)?(?P<n>(-?)([0-9]+)(?:\.([0-9]+))?)"),
}
# Texto que não pode ser número: um caractere que nenhum número aceita (só
# dígito, espaço, separador, sinal, parênteses, moeda, as letras de R$,
# US$, BRL/USD/EUR, D/C e do E da notação científica, e os invisíveis que a
# normalização tira) ou um traço entre dígitos (CEP, CPF, '1-2'). Data,
# descrição e CEP param aqui.
_NAO_E_NUMERO = re.compile(
    r"[^\d\s.,+()\-\u2013\u2014$€BCDELRSUbcdelrsu\u200b-\u200d\u2060\ufeff\u00ad]"
    r"|[0-9]\s*[\-\u2013\u2014]\s*[0-9]"
)


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
    if isinstance(value, str):
        padrao = _SIMPLES.get(decimal)
        if padrao is not None and (m := padrao.fullmatch(value)) and m["n"] not in NULL_TOKENS:
            _, sinal, inteiro, frac = m.groups()
            return float(f"{sinal}{inteiro.replace('.', '')}.{frac or '0'}")
        if _NAO_E_NUMERO.search(value):
            return None
    return _parse_completo(value, decimal, dash_is_zero, debit_negative)


def _parse_completo(value: object, decimal: str, dash_is_zero: bool, debit_negative: bool) -> float | None:
    """``parse_number_br`` sem os atalhos: todas as normalizações."""
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


_DIGITOS = frozenset("0123456789")


def decimal_provavel(valores: list) -> str:
    """Separador decimal de uma coluna de números em texto, decidido pela
    coluna inteira (``parse_decimal_br`` com ``decimal="auto"``).

    ``"."`` quando nenhum valor tem vírgula e algum tem um único ponto
    seguido de 1, 2 ou 4 ou mais dígitos ('8725.3480', '0.5'): esse ponto
    não pode ser separador de milhar. É o caso de número do Excel lido como
    texto. Senão, ``","`` (padrão brasileiro).

    Coluna em que todo ponto tem exatamente 3 dígitos depois ('104.000') é
    ambígua e fica com ``","``: escolha ``decimal="."`` se a fonte publica
    ponto decimal."""
    ponto = False
    for v in valores:
        if v is None or isinstance(v, (bool, int, float)):
            continue
        t = str(v).strip()
        if "," in t:
            return ","
        if not ponto and t.count(".") == 1:
            antes, depois = t.split(".")
            ponto = (
                bool(antes)
                and antes[-1] in _DIGITOS
                and bool(depois)
                and set(depois) <= _DIGITOS
                and len(depois) != 3
            )
    return "." if ponto else ","


def parse_brl(value: object, debit_negative: bool = False) -> float | None:
    """Moeda brasileira: 'R$ 1.234,56', '(1.234,56)', 'R$ -' (= 0).

    Igual a ``parse_number_br`` com decimal=',' e '-' valendo zero, que é
    como o formato contábil do Excel exibe zero."""
    return parse_number_br(value, decimal=",", dash_is_zero=True, debit_negative=debit_negative)


def format_brl(value: float | None, symbol: bool = True) -> str | None:
    """Inverso de ``parse_brl``: 1234.56 -> 'R$ 1.234,56'; -5 -> '-R$ 5,00'.

    Arredonda para centavos. Valor que arredonda para zero sai sem sinal,
    para não exibir '-R$ 0,00'."""
    if value is None:
        return None
    text = f"{abs(value):,.2f}".translate(str.maketrans(",.", ".,"))
    sign = "-" if value < 0 and text != "0,00" else ""
    return f"{sign}R$ {text}" if symbol else f"{sign}{text}"


def parse_percent_br(value: object, bare: str = "fraction") -> float | None:
    """Percentual para fração: '12,5%' -> 0.125.

    Sem o símbolo '%', o significado depende da base, então é explícito:
    ``bare='fraction'`` trata '0,125' como 0.125; ``bare='points'`` trata
    '12,5' como 12,5% -> 0.125. Nunca decide valor a valor, porque uma
    coluna com 0,5 e 50 ficaria com escalas misturadas."""
    if value is None:
        return None
    s = normalize_spaces(str(value))
    # n / 100 arredondado: 4,22% é 0.0422, não 0.042199999999999994 (que
    # apareceria assim no CSV exportado).
    if "%" in s:
        n = parse_number_br(s.replace("%", ""))
        return None if n is None else round(n / 100, 15)
    n = parse_number_br(s)
    if n is None:
        return None
    return round(n / 100, 15) if bare == "points" else n


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

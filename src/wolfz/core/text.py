"""Normalização de texto: espaços, acentos, chaves de comparação e
marcadores de ausência.

Nada aqui altera o significado de um valor; as regras de conversão ficam em
``wolfz.br``.
"""

from __future__ import annotations

import re
import unicodedata

from wolfz.br.constants import NULL_TOKENS

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_ESPACOS_ESPECIAIS = re.compile(r"[    　\t\r\n]+")


def remove_accents(text: str) -> str:
    """'Espírito Santo' -> 'Espirito Santo'. Mantém caixa e pontuação."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_spaces(text: str) -> str:
    """Troca espaço não separável, tab e quebra de linha por espaço simples,
    remove caracteres invisíveis (zero-width, BOM, hífen suave) e colapsa
    espaços repetidos. Também converte para a forma NFC, porque arquivos
    vindos de macOS trazem acentos decompostos ('a' + '~') que parecem iguais
    na tela mas não são iguais numa comparação ou num join."""
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = _ESPACOS_ESPECIAIS.sub(" ", text)
    return re.sub(r" {2,}", " ", text).strip()


def normalize_key(text: str | None) -> str:
    """Chave de comparação: sem acento, minúscula, espaços normalizados.
    Use para casar categorias ('SÃO PAULO', 'Sao Paulo', 'são  paulo')."""
    if text is None:
        return ""
    return remove_accents(normalize_spaces(str(text))).lower()


def only_digits(text: str | None) -> str:
    """'123.456.789-09' -> '12345678909'."""
    return re.sub(r"\D", "", str(text)) if text is not None else ""


def is_null_token(value: object, extra: frozenset[str] | set[str] = frozenset()) -> bool:
    """True se o valor representa ausência de dado (ver ``NULL_TOKENS``).

    ``extra`` aceita marcadores próprios da base, já normalizados com
    ``normalize_key`` (ex.: {"nao se aplica", "999"})."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    key = normalize_key(str(value))
    return key in NULL_TOKENS or key in extra


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

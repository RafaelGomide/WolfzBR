"""Funções utilitárias do WolfzBR: leitura robusta de arquivos, normalização
de texto e nomes, e inspeção rápida de dados durante o desenvolvimento.

Nada aqui altera o significado de um valor; as regras de limpeza ficam em
``cleaning.py``.
"""

from __future__ import annotations

import codecs
import csv
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Constantes compartilhadas
# ---------------------------------------------------------------------------

UFS: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

# Abreviações em português e em inglês (Excel em inglês exporta "15-Mar-2024").
MESES: dict[str, int] = {
    "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "feb": 2,
    "mar": 3, "marco": 3, "abr": 4, "abril": 4, "apr": 4,
    "mai": 5, "maio": 5, "may": 5, "jun": 6, "junho": 6,
    "jul": 7, "julho": 7, "ago": 8, "agosto": 8, "aug": 8,
    "set": 9, "setembro": 9, "sep": 9, "sept": 9,
    "out": 10, "outubro": 10, "oct": 10, "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12, "dec": 12,
}

# Marcadores de "sem valor" vistos em bases públicas e em exportações
# corporativas, já normalizados por ``normalize_key``. Casos de origem:
#   Excel PT-BR/EN: #N/D, #VALOR!, #DIV/0!, #REF!, #NOME?, #NÚM!, #NULO!
#   TSE: #NULO#, #NE#
#   Portal da Transparência: "Sem Informação", "Não Identificado"
#   Datas vazias de sistemas legados: 00/00/0000, 0000-00-00, 00000000
# "-" fica de fora de propósito: em formato contábil e nas tabelas do IBGE
# ele significa ZERO, não ausência (ver cleaning.parse_brl e parse_ibge_value).
NULL_TOKENS: frozenset[str] = frozenset({
    "", "--", "---", "?", "na", "n/a", "n.a.", "n/d", "nd", "nan", "null",
    "none", "nil", "<null>", "(null)", "#n/d", "#n/a", "#valor!", "#value!",
    "#div/0!", "#ref!", "#nome?", "#name?", "#num!", "#nulo!", "#null!",
    "#nulo#", "#ne#", "s/i", "s.i.", "sem informacao", "nao informado",
    "nao identificado", "nao disponivel", "(vazio)", "(em branco)", "(blank)",
    "00/00/0000", "0000-00-00", "00000000",
})

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_ESPACOS_ESPECIAIS = re.compile(r"[    　\t\r\n]+")


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Nomes de coluna
# ---------------------------------------------------------------------------

def to_snake_case(name: str) -> str:
    """'Valor de Venda (R$)' -> 'valor_de_venda_r'; 'Nº Pedido' -> 'n_pedido'.

    Remove BOM e acentos, troca qualquer separador por '_'. Nome que começa
    com dígito ganha prefixo 'c_' para ser identificador válido em Python,
    M e SQL. Nome vazio vira 'coluna'."""
    name = normalize_spaces(str(name))
    name = name.replace("º", "").replace("ª", "").replace("%", " pct ")
    name = remove_accents(name).lower()
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    if not name:
        return "coluna"
    return f"c_{name}" if name[0].isdigit() else name


def dedupe_names(names: list[str]) -> list[str]:
    """['valor', 'valor', 'data'] -> ['valor', 'valor_2', 'data'].

    Relatórios com cabeçalho multinível costumam repetir o mesmo rótulo
    em várias colunas ("Valor" sob cada mês)."""
    seen: Counter[str] = Counter()
    result = []
    taken = set(names)
    for name in names:
        seen[name] += 1
        if seen[name] == 1:
            result.append(name)
            continue
        n = seen[name]
        while f"{name}_{n}" in taken:
            n += 1
        new = f"{name}_{n}"
        taken.add(new)
        result.append(new)
    return result


# ---------------------------------------------------------------------------
# Leitura de arquivos
# ---------------------------------------------------------------------------

def detect_encoding(path: str | Path, sample_size: int = 1 << 20) -> str:
    """Detecta o encoding de um arquivo de texto brasileiro.

    Ordem: BOM (UTF-8 ou UTF-16) -> UTF-8 válido -> cp1252 -> latin-1.
    Bases do governo vêm nos dois sabores: ANP publica UTF-8 com BOM; Portal
    da Transparência, TSE e Receita publicam Latin-1/cp1252. UTF-16 aparece
    quando alguém salva do Excel como "Texto Unicode".

    Não usa detecção estatística (charset-normalizer/chardet) de propósito:
    no CSV do CEIS ela escolhe cp1250, que decodifica 'Ã' como 'Ă' e corrompe
    todo texto acentuado em português. Para dado brasileiro, cp1252 é a
    resposta certa sempre que o arquivo não é UTF-8."""
    raw = Path(path).read_bytes()[:sample_size]
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        # A amostra pode cortar um caractere multibyte no fim; o decoder
        # incremental tolera isso quando o arquivo não foi lido inteiro.
        codecs.getincrementaldecoder("utf-8")().decode(raw, final=len(raw) < sample_size)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        # Bytes 0x81, 0x8D, 0x8F, 0x90 e 0x9D não existem em cp1252.
        return "latin-1"


def detect_separator(sample: str, candidates: str = ";,\t|") -> str:
    """Detecta o separador de um CSV a partir de um trecho do texto.

    Padrão brasileiro é ';' (porque ',' é separador decimal). Usa
    ``csv.Sniffer`` e, se falhar, escolhe o candidato com contagem mais
    estável entre as primeiras linhas."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=candidates).delimiter
    except csv.Error:
        pass
    lines = [ln for ln in sample.splitlines()[:50] if ln.strip()]
    best, best_score = ";", -1.0
    for sep in candidates:
        counts = [ln.count(sep) for ln in lines]
        if not counts or max(counts) == 0:
            continue
        mode, freq = Counter(counts).most_common(1)[0]
        score = freq / len(counts) * (1 if mode > 0 else 0)
        if score > best_score:
            best, best_score = sep, score
    return best


def read_csv_raw(
    path: str | Path,
    encoding: str | None = None,
    separator: str | None = None,
    has_header: bool = True,
) -> pl.DataFrame:
    """Lê um CSV com TODAS as colunas como texto, sem inferência de tipo.

    É o ponto de partida certo para limpeza: inferir tipo na leitura destrói
    zeros à esquerda (CPF, CEP, código IBGE), interpreta '1.234' como 1,234
    e transforma datas dd/mm em texto ou em datas trocadas. A conversão de
    tipos acontece depois, coluna a coluna, com as funções de cleaning.py.

    Encoding e separador são detectados quando não informados. Arquivos que
    não são UTF-8 são decodificados em memória antes de ir para o Polars."""
    path = Path(path)
    encoding = encoding or detect_encoding(path)
    text = path.read_bytes().decode(encoding, errors="replace")
    separator = separator or detect_separator(text[:64_000])
    return pl.read_csv(
        text.encode("utf-8"),
        separator=separator,
        has_header=has_header,
        infer_schema=False,
        quote_char='"',
        truncate_ragged_lines=True,
    )


# ---------------------------------------------------------------------------
# Datas do Excel
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Inspeção durante o desenvolvimento
# ---------------------------------------------------------------------------

def value_shape(value: str | None, max_len: int = 30) -> str:
    """Forma de um valor: dígito vira '9', letra vira 'a', resto fica.

    '123.456.789-09' -> '999.999.999-99'; 'R$ 1.234,56' -> 'a$ 9.999,99'.
    Agrupar uma coluna por forma revela em segundos os formatos misturados
    (CPF com e sem máscara, datas em dois padrões, zeros perdidos)."""
    if value is None:
        return "<null>"
    s = re.sub(r"\d", "9", str(value))
    s = re.sub(r"[^\W\d_]", "a", s)
    return s[:max_len]


def quick_profile(df: pl.DataFrame, top: int = 3) -> pl.DataFrame:
    """Perfil rápido de todas as colunas: nulos, vazios, distintos, formas
    mais comuns e exemplos. Pensado para uso interativo em notebook."""
    rows = []
    for name in df.columns:
        s = df[name].cast(pl.String)
        values = s.to_list()
        non_null = [v for v in values if v is not None]
        shapes = Counter(value_shape(v) for v in non_null)
        rows.append({
            "coluna": name,
            "nulos": s.null_count(),
            "vazios_ou_marcadores": sum(is_null_token(v) for v in non_null),
            "distintos": s.n_unique(),
            "formas": " | ".join(f"{k} ({c})" for k, c in shapes.most_common(top)),
            "exemplos": " | ".join(str(v)[:30] for v in list(dict.fromkeys(non_null))[:top]),
        })
    return pl.DataFrame(rows)

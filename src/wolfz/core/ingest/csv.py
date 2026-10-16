"""Leitura robusta de CSV brasileiro: encoding, separador e leitura crua."""

from __future__ import annotations

import codecs
import csv
from collections import Counter
from pathlib import Path

import polars as pl


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
    tipos acontece depois, coluna a coluna, com as funções de ``wolfz.br``.

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

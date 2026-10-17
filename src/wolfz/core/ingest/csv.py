"""Leitura robusta de CSV brasileiro: encoding, separador e leitura crua.

Arquivos até ``STREAMING_THRESHOLD_BYTES`` são decodificados em memória.
Acima disso, o texto é convertido para UTF-8 em blocos num arquivo
temporário e lido pelo Polars em streaming, sem nunca ter o arquivo inteiro
como ``str`` Python (que custa de 2 a 4 vezes o tamanho em bytes).
"""

from __future__ import annotations

import codecs
import csv
import io
import os
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import polars as pl

from wolfz.core.ingest.cells import column_letter

STREAMING_THRESHOLD_BYTES = 50 * 1024 * 1024
_SAMPLE_BYTES = 64_000
_CHUNK = 1 << 20


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
    não são UTF-8 são decodificados em memória antes de ir para o Polars;
    acima de ``STREAMING_THRESHOLD_BYTES``, em streaming (``open_csv_lazy``)."""
    path = Path(path)
    if path.stat().st_size > STREAMING_THRESHOLD_BYTES:
        with open_csv_lazy(path, encoding, separator, has_header) as lf:
            return lf.collect(engine="streaming")
    encoding = encoding or detect_encoding(path)
    text = path.read_bytes().decode(encoding, errors="replace")
    separator = separator or detect_separator(text[:_SAMPLE_BYTES])
    return pl.read_csv(
        text.encode("utf-8"),
        separator=separator,
        has_header=has_header,
        infer_schema=False,
        quote_char='"',
        truncate_ragged_lines=True,
    )


def read_sample(path: str | Path, encoding: str, size: int = _SAMPLE_BYTES) -> str:
    """Começo do arquivo decodificado, tolerando um caractere cortado no fim."""
    with Path(path).open("rb") as f:
        raw = f.read(size)
    return codecs.getincrementaldecoder(encoding)(errors="replace").decode(raw, final=len(raw) < size)


def sniff_csv(path: str | Path) -> tuple[str, str]:
    """``(encoding, separador)`` detectados de um CSV."""
    encoding = detect_encoding(path)
    return encoding, detect_separator(read_sample(path, encoding))


def grid_width(sample: str, separator: str) -> int:
    """Maior quantidade de campos numa linha da amostra. Linhas com título
    ou nota têm menos campos que a tabela; a largura da grade é a maior.
    A última linha é descartada: pode estar cortada pela amostra."""
    lines = sample.splitlines(keepends=True)
    if len(lines) > 1:
        lines = lines[:-1]
    reader = csv.reader(io.StringIO("".join(lines)), delimiter=separator)
    return max((len(row) for row in reader), default=1) or 1


def _copy_as_utf8(path: Path, encoding: str, dest: Path, header: str = "") -> None:
    """Converte o arquivo para UTF-8 em blocos; ``header`` vai na frente."""
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    with path.open("rb") as src, dest.open("w", encoding="utf-8", newline="") as out:
        out.write(header)
        while block := src.read(_CHUNK):
            out.write(decoder.decode(block))
        out.write(decoder.decode(b"", final=True))


@contextmanager
def open_csv_lazy(
    path: str | Path,
    encoding: str | None = None,
    separator: str | None = None,
    has_header: bool = True,
    tmp_dir: str | Path | None = None,
) -> Iterator[pl.LazyFrame]:
    """``LazyFrame`` de um CSV, tudo como texto, para ler em streaming
    (``collect(engine="streaming")`` ou ``sink_parquet``). Só vale dentro do
    ``with``: fora dele o arquivo temporário já foi apagado.

    Com ``has_header=False`` a tabela é a grade do arquivo, como numa aba
    de planilha: colunas ``A``, ``B``, … e linha ``i`` = linha ``i + 1`` do
    arquivo. A largura vem da amostra do começo do arquivo; linhas mais
    largas que isso, mais adiante, são truncadas."""
    path = Path(path)
    encoding = encoding or detect_encoding(path)
    sample = read_sample(path, encoding)
    separator = separator or detect_separator(sample)
    options = {
        "separator": separator,
        "infer_schema": False,
        "quote_char": '"',
        "truncate_ragged_lines": True,
    }

    if has_header and encoding in ("utf-8", "utf-8-sig"):
        yield pl.scan_csv(path, has_header=True, **options)
        return

    header = ""
    if not has_header:
        # Cabeçalho sintético: o Polars tira a largura da primeira linha,
        # que numa planilha de relatório costuma ser um título de um campo.
        width = grid_width(sample, separator)
        header = separator.join(column_letter(i) for i in range(width)) + "\n"
    fd, name = tempfile.mkstemp(suffix=".csv", prefix=".wolfz-", dir=tmp_dir)
    os.close(fd)
    tmp = Path(name)
    try:
        _copy_as_utf8(path, encoding, tmp, header)
        yield pl.scan_csv(tmp, has_header=True, **options)
    finally:
        tmp.unlink(missing_ok=True)

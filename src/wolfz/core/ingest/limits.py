"""Limites da importação (§2.2 e §11.4 do design).

Recusar cedo e com mensagem clara é melhor do que degradar até travar a
máquina (§8.8): os limites são verificados antes de qualquer leitura pesada.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from wolfz.core.ingest.errors import IngestError, corrupted

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """Tetos da importação.

    - ``max_file_bytes``: 100 MB, decidido em F0.A1 (§2.2).
    - ``max_uncompressed_bytes``: soma do tamanho descompactado de um
      ``.xlsx``/``.ods`` (que são zip). Um ``.xlsx`` de 100 MB costuma ter
      entre 0,5 e 1,5 GB de XML; 2 GB é o orçamento de memória (§3.5).
    - ``max_compression_ratio``: razão descompactado/compactado acima da
      qual o arquivo é tratado como zip bomb. XML de planilha comprime de
      5 a 30 vezes; zip bomb, centenas ou milhares. Só vale a partir de
      ``ratio_floor_bytes`` descompactados — arquivo pequeno pode ter
      razão alta sem risco nenhum.
    - ``max_sheets``: quantidade de abas (cada uma é listada com dimensão).
    """

    max_file_bytes: int = 100 * MB
    max_uncompressed_bytes: int = 2048 * MB
    max_compression_ratio: float = 100.0
    ratio_floor_bytes: int = 100 * MB
    max_sheets: int = 200


DEFAULT_LIMITS = Limits()


def _fmt_mb(n: int, casas: int = 0) -> str:
    texto = f"{n / MB:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{texto} MB"


def too_large_message(limit: int, size: int | None = None, name: str | None = None) -> str:
    """Texto do 413 de arquivo grande demais, o mesmo na CLI e na API.
    ``size`` é ``None`` quando o upload foi cortado no limite (o tamanho
    real não chega a ser conhecido)."""
    if size is None:
        inicio = f"{name or 'O arquivo'} passa de {_fmt_mb(limit)}, o limite."
    else:
        inicio = f"{name or 'O arquivo'} tem {_fmt_mb(size, 1)}; o limite é {_fmt_mb(limit)}."
    return f"{inicio} Divida o arquivo ou exporte só as colunas e linhas necessárias."


def check_file_size(path: Path, limits: Limits = DEFAULT_LIMITS) -> int:
    """Devolve o tamanho do arquivo, ou ``IngestError`` se passar do teto."""
    size = path.stat().st_size
    if size > limits.max_file_bytes:
        raise IngestError(
            "file_too_large",
            "Arquivo grande demais",
            too_large_message(limits.max_file_bytes, size, path.name),
            413,
        )
    return size


def check_zip(path: Path, limits: Limits = DEFAULT_LIMITS) -> None:
    """Verifica o tamanho descompactado declarado no índice do zip.

    O índice pode mentir; esta é a primeira barreira, barata, contra zip
    bomb. A segunda é o limite de tamanho do próprio arquivo, que restringe
    o quanto um arquivo honesto pode crescer."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise corrupted(path.name, str(exc)) from exc
    uncompressed = sum(i.file_size for i in infos)
    compressed = max(sum(i.compress_size for i in infos), 1)
    too_big = uncompressed > limits.max_uncompressed_bytes
    suspicious = (
        uncompressed > limits.ratio_floor_bytes and uncompressed / compressed > limits.max_compression_ratio
    )
    if too_big or suspicious:
        raise IngestError(
            "uncompressed_too_large",
            "Conteúdo descompactado grande demais",
            f"{path.name} se expande para {_fmt_mb(uncompressed)} ao ser aberto "
            f"(limite: {_fmt_mb(limits.max_uncompressed_bytes)}, razão máxima "
            f"de {limits.max_compression_ratio:.0f} vezes). O arquivo foi recusado por segurança.",
            413,
        )


def check_sheet_count(name: str, count: int, limits: Limits = DEFAULT_LIMITS) -> None:
    if count > limits.max_sheets:
        raise IngestError(
            "too_many_sheets",
            "Abas demais",
            f"{name} tem {count} abas; o limite é {limits.max_sheets}. "
            "Copie as abas que interessam para um arquivo novo.",
            413,
        )

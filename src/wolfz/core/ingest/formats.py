"""Identificação do formato pelo conteúdo, não só pela extensão (§6.5).

A extensão diz o que o usuário acha que o arquivo é; os primeiros bytes
dizem o que ele é. Quando os dois discordam a importação para com uma
mensagem que diz como resolver — o caso clássico é o "relatório .xls" de
sistema bancário ou ERP, que na verdade é uma página HTML.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path
from typing import Literal

from wolfz.core.ingest import errors
from wolfz.core.ingest.errors import IngestError

Format = Literal["xlsx", "xls", "ods", "csv"]

EXTENSIONS: dict[str, Format] = {
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xls",
    ".ods": "ods",
    ".csv": "csv",
    ".txt": "csv",
    ".tsv": "csv",
}

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP = b"PK\x03\x04"
_ODS_MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"
# Um .xlsx com senha não é zip: é um contêiner OLE2 com estes dois fluxos
# (MS-OFFCRYPTO). Os nomes ficam no diretório do OLE2, em UTF-16LE.
_ENCRYPTED_STREAMS = ("EncryptionInfo".encode("utf-16-le"), "EncryptedPackage".encode("utf-16-le"))

Content = Literal["xlsx", "xls", "ods", "csv", "encrypted", "html", "pdf", "zip", "binary"]


def ensure_readable(path: Path, attempts: int = 3, delay: float = 0.2) -> None:
    """Abre o arquivo para leitura, com novas tentativas curtas.

    No Windows, um arquivo bloqueado pelo Excel ou no meio de uma
    sincronização do OneDrive dá ``PermissionError``; o bloqueio da
    sincronização costuma ser transitório (§10.3)."""
    if path.name.startswith("~$"):
        raise errors.excel_lock_file(path.name)
    for attempt in range(attempts):
        try:
            with path.open("rb") as f:
                f.read(1)
            return
        except FileNotFoundError as exc:
            raise errors.not_found(path.name) from exc
        except PermissionError as exc:
            if attempt == attempts - 1:
                raise errors.locked(path.name) from exc
            time.sleep(delay)


def _contains(path: Path, needles: tuple[bytes, ...], chunk: int = 1 << 20) -> bool:
    """Procura qualquer um dos padrões no arquivo, em blocos (sem carregar
    o arquivo inteiro)."""
    overlap = max(len(n) for n in needles) - 1
    tail = b""
    with path.open("rb") as f:
        while block := f.read(chunk):
            window = tail + block
            if any(n in window for n in needles):
                return True
            tail = window[-overlap:]
    return False


def sniff(path: Path) -> Content:
    """O que o arquivo é, pelos bytes."""
    with path.open("rb") as f:
        head = f.read(8192)
    if head.startswith(_OLE2):
        return "encrypted" if _contains(path, _ENCRYPTED_STREAMS) else "xls"
    if head.startswith(_ZIP):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if "xl/workbook.xml" in names or "xl/workbook.bin" in names:
                    return "xlsx"
                if "mimetype" in names and zf.read("mimetype").strip() == _ODS_MIMETYPE:
                    return "ods"
        except zipfile.BadZipFile as exc:
            raise errors.corrupted(path.name, str(exc)) from exc
        return "zip"
    if head.startswith(b"%PDF"):
        return "pdf"
    start = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if start.startswith((b"<!doctype html", b"<html", b"<table", b"<meta")) or (
        start.startswith(b"<") and b"<table" in head.lower()
    ):
        return "html"
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "binary"
    return "csv"


_LABEL = {
    "xlsx": "planilha .xlsx",
    "xls": "planilha .xls antiga",
    "ods": "planilha .ods",
    "csv": "texto (CSV)",
}


def detect_format(path: Path) -> Format:
    """Formato de leitura do arquivo; ``IngestError`` se não for planilha ou
    se a extensão não bater com o conteúdo."""
    content = sniff(path)
    name, ext = path.name, path.suffix.lower()
    if content == "encrypted":
        raise errors.password_protected(name)
    if content == "html":
        raise IngestError(
            "extension_mismatch",
            "Extensão não bate com o conteúdo",
            f"{name} tem extensão {ext or '(nenhuma)'}, mas é uma página HTML, não uma planilha. "
            "Isso é comum em relatórios exportados por sistemas. Abra no Excel e use "
            "Salvar como > Pasta de Trabalho do Excel (.xlsx).",
        )
    if content in ("pdf", "zip", "binary"):
        kind = {"pdf": "um PDF", "zip": "um arquivo .zip", "binary": "um arquivo binário"}[content]
        raise IngestError(
            "unsupported_format",
            "Formato não suportado",
            f"{name} é {kind}, não uma planilha. Formatos aceitos: .xlsx, .xls, .ods e .csv.",
            415,
        )
    expected = EXTENSIONS.get(ext)
    if expected is not None and expected != content:
        suggestion = f"{path.stem}.{content}"
        raise IngestError(
            "extension_mismatch",
            "Extensão não bate com o conteúdo",
            f"{name} tem extensão {ext}, mas o conteúdo é de {_LABEL[content]}. "
            f"Renomeie para {suggestion} e importe de novo.",
        )
    return content

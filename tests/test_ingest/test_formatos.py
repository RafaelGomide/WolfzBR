import zipfile
from pathlib import Path

import pytest
import python_calamine

from wolfz.core.ingest import IngestError, Limits, detect_format, open_file
from wolfz.core.ingest.excel import reading
from wolfz.core.ingest.formats import _OLE2, ensure_readable, sniff
from wolfz.core.ingest.limits import check_sheet_count, check_zip


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(IngestError) as exc:
        fn(*args, **kwargs)
    return exc.value.code


def test_formatos_pelo_conteudo(relatorio_xlsx, exemplo_xls, exemplo_ods, tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("a;b\n", encoding="utf-8")
    assert detect_format(relatorio_xlsx) == "xlsx"
    assert detect_format(exemplo_xls) == "xls"
    assert detect_format(exemplo_ods) == "ods"
    assert detect_format(csv) == "csv"


def test_extensao_desconhecida_vale_o_conteudo(relatorio_xlsx, tmp_path):
    sem = tmp_path / "relatorio"
    sem.write_bytes(relatorio_xlsx.read_bytes())
    assert detect_format(sem) == "xlsx"


def test_xlsm_e_xlsx(relatorio_xlsx, tmp_path):
    xlsm = tmp_path / "macro.xlsm"
    xlsm.write_bytes(relatorio_xlsx.read_bytes())
    assert detect_format(xlsm) == "xlsx"


def test_extensao_que_nao_bate(relatorio_xlsx, tmp_path):
    falso = tmp_path / "vendas.xls"
    falso.write_bytes(relatorio_xlsx.read_bytes())
    with pytest.raises(IngestError) as exc:
        detect_format(falso)
    assert exc.value.code == "extension_mismatch"
    assert "vendas.xlsx" in exc.value.message


def test_html_salvo_como_xls(tmp_path):
    html = tmp_path / "extrato.xls"
    html.write_bytes(b"\xef\xbb\xbf<html><body><table><tr><td>1</td></tr></table></body></html>")
    with pytest.raises(IngestError) as exc:
        detect_format(html)
    assert exc.value.code == "extension_mismatch"
    assert "HTML" in exc.value.message


def test_html_com_table_depois_de_xml(tmp_path):
    html = tmp_path / "extrato.xls"
    html.write_bytes(b'<?xml version="1.0"?>\n<div><table><tr><td>1</td></tr></table></div>')
    assert sniff(html) == "html"


@pytest.mark.parametrize(
    ("content", "name"),
    [(b"%PDF-1.7 ...", "a.xlsx"), (b"\x00\x01\x02binario", "a.csv")],
)
def test_nao_e_planilha(tmp_path, content, name):
    path = tmp_path / name
    path.write_bytes(content)
    assert _code(detect_format, path) == "unsupported_format"


def test_zip_que_nao_e_planilha(tmp_path):
    path = tmp_path / "a.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("leiame.txt", "oi")
    assert _code(detect_format, path) == "unsupported_format"


def test_zip_corrompido(tmp_path):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"PK\x03\x04" + b"lixo" * 100)
    assert _code(detect_format, path) == "corrupted"


def test_utf16_nao_e_binario(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes("a;b\n1;2\n".encode("utf-16"))
    assert detect_format(path) == "csv"


def test_xlsx_com_senha(tmp_path):
    # .xlsx com senha é um contêiner OLE2 com o fluxo EncryptionInfo.
    path = tmp_path / "secreto.xlsx"
    path.write_bytes(_OLE2 + b"\x00" * 600 + "EncryptionInfo".encode("utf-16-le") + b"\x00" * 100)
    with pytest.raises(IngestError) as exc:
        detect_format(path)
    assert exc.value.code == "password_protected"
    assert "senha" in exc.value.message


def test_xls_com_senha(tmp_path):
    path = tmp_path / "secreto.xls"
    with pytest.raises(IngestError) as exc, reading(path):
        raise python_calamine.PasswordError("encrypted")
    assert exc.value.code == "password_protected"


def test_planilha_corrompida(tmp_path):
    path = tmp_path / "a.xls"
    path.write_bytes(_OLE2 + b"\x00" * 1000)
    with pytest.raises(IngestError) as exc:
        from wolfz.core.ingest import list_sheets

        list_sheets(path)
    assert exc.value.code == "corrupted"
    assert "corrompido" in exc.value.message


def test_arquivo_aberto_no_excel(tmp_path, monkeypatch):
    path = tmp_path / "vendas.xlsx"
    path.write_bytes(b"x")
    original = Path.open

    def bloqueado(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", bloqueado)
    with pytest.raises(IngestError) as exc:
        ensure_readable(path, delay=0)
    assert exc.value.code == "file_locked"
    assert "Excel" in exc.value.message
    assert exc.value.to_problem()["status"] == 409


def test_bloqueio_transitorio_passa_na_nova_tentativa(tmp_path, monkeypatch):
    path = tmp_path / "vendas.xlsx"
    path.write_bytes(b"x")
    original = Path.open
    falhas = iter([True])

    def uma_vez(self, *args, **kwargs):
        if self == path and next(falhas, False):
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", uma_vez)
    ensure_readable(path, delay=0)


def test_reading_traduz_permission_error(tmp_path):
    with pytest.raises(IngestError) as exc, reading(tmp_path / "a.xlsx"):
        raise PermissionError
    assert exc.value.code == "file_locked"


def test_arquivo_temporario_do_excel(tmp_path):
    path = tmp_path / "~$vendas.xlsx"
    path.write_bytes(b"x")
    with pytest.raises(IngestError) as exc:
        open_file(path)
    assert exc.value.code == "excel_lock_file"
    assert "Importe vendas.xlsx" in exc.value.message


def test_arquivo_inexistente(tmp_path):
    assert _code(open_file, tmp_path / "nada.xlsx") == "file_not_found"
    assert _code(ensure_readable, tmp_path / "nada.xlsx") == "file_not_found"


def test_arquivo_vazio(tmp_path):
    path = tmp_path / "vazio.csv"
    path.write_bytes(b"")
    assert _code(open_file, path) == "empty_file"


def test_arquivo_grande_demais(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(b"a;b\n" * 1000)
    with pytest.raises(IngestError) as exc:
        open_file(path, Limits(max_file_bytes=100))
    assert exc.value.code == "file_too_large"
    assert exc.value.status == 413


def _bomba(path: Path, size: int) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"\x00" * size)
    return path


def test_zip_bomb_pela_razao(tmp_path):
    path = _bomba(tmp_path / "bomba.xlsx", 2_000_000)
    limits = Limits(ratio_floor_bytes=1_000_000, max_compression_ratio=100)
    with pytest.raises(IngestError) as exc:
        check_zip(path, limits)
    assert exc.value.code == "uncompressed_too_large"
    with pytest.raises(IngestError):
        open_file(path, limits)


def test_zip_grande_demais_descompactado(tmp_path):
    path = _bomba(tmp_path / "grande.xlsx", 2_000_000)
    assert _code(check_zip, path, Limits(max_uncompressed_bytes=1_000_000)) == "uncompressed_too_large"


def test_zip_pequeno_com_razao_alta_passa(tmp_path):
    check_zip(_bomba(tmp_path / "ok.xlsx", 500_000))


def test_quantidade_de_abas():
    check_sheet_count("a.xlsx", 200)
    with pytest.raises(IngestError) as exc:
        check_sheet_count("a.xlsx", 3, Limits(max_sheets=2))
    assert exc.value.code == "too_many_sheets"


def test_list_sheets_respeita_limite_de_abas(relatorio_xlsx):
    from wolfz.core.ingest import list_sheets

    assert _code(list_sheets, relatorio_xlsx, limits=Limits(max_sheets=2)) == "too_many_sheets"


def test_problem_details():
    err = IngestError("x", "Título", "Mensagem", 400)
    assert err.to_problem("/api/projects") == {
        "type": "about:blank",
        "title": "Título",
        "status": 400,
        "detail": "Mensagem",
        "code": "x",
        "instance": "/api/projects",
    }

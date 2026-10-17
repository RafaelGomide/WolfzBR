import pytest

from wolfz.core.ingest import csv as ingest_csv
from wolfz.core.ingest.csv import grid_width, open_csv_lazy, read_csv_raw, sniff_csv

TEXTO = "Município;CPF;Valor\nSão Paulo;01234567890;1.234,56\nVitória;00011122233;10,00\n"
LINHAS = [("São Paulo", "01234567890", "1.234,56"), ("Vitória", "00011122233", "10,00")]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1252"])
def test_streaming_igual_a_leitura_em_memoria(tmp_path, monkeypatch, encoding):
    path = tmp_path / "dados.csv"
    path.write_bytes(TEXTO.encode(encoding))
    em_memoria = read_csv_raw(path)
    monkeypatch.setattr(ingest_csv, "STREAMING_THRESHOLD_BYTES", 10)
    streaming = read_csv_raw(path)
    assert streaming.equals(em_memoria)
    assert streaming.columns == ["Município", "CPF", "Valor"]
    assert streaming.rows() == LINHAS


def test_streaming_apaga_o_temporario(tmp_path):
    path = tmp_path / "dados.csv"
    path.write_bytes(TEXTO.encode("cp1252"))
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    with open_csv_lazy(path, tmp_dir=tmp_dir) as lf:
        assert len(list(tmp_dir.iterdir())) == 1
        assert lf.collect().rows() == LINHAS
    assert list(tmp_dir.iterdir()) == []


def test_grade_sem_cabecalho_na_posicao_original(tmp_path):
    # Título de um campo na primeira linha: a largura vem da linha mais larga.
    path = tmp_path / "relatorio.csv"
    path.write_bytes(("Relatório de vendas\n\n" + TEXTO + "Fonte: sistema\n").encode("cp1252"))
    with open_csv_lazy(path, has_header=False) as lf:
        df = lf.collect()
    assert df.columns == ["A", "B", "C"]
    assert df.row(0) == ("Relatório de vendas", None, None)
    assert df.row(2) == ("Município", "CPF", "Valor")
    assert df.row(3) == LINHAS[0]
    assert df.row(-1) == ("Fonte: sistema", None, None)


def test_grade_utf8_com_bom(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(TEXTO.encode("utf-8-sig"))
    with open_csv_lazy(path, has_header=False) as lf:
        assert lf.collect().row(0) == ("Município", "CPF", "Valor")


def test_sniff_csv(tmp_path):
    path = tmp_path / "dados.csv"
    path.write_bytes(TEXTO.encode("cp1252"))
    assert sniff_csv(path) == ("cp1252", ";")


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("a;b;c\n1;2;3\n", 3),
        ("titulo\na;b\n1;2;3;4", 2),  # última linha pode estar cortada
        ('"x;y";b\n', 2),
        ("", 1),
    ],
)
def test_grid_width(sample, expected):
    assert grid_width(sample, ";") == expected

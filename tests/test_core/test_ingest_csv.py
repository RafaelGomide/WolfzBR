import pytest

from wolfz.core.ingest.csv import detect_encoding, detect_separator, read_csv_raw

TEXTO = "Município;CPF;Valor\nSão Paulo;01234567890;1.234,56\nVitória;00011122233;10,00\n"


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [
        ("utf-8", "utf-8"),
        ("utf-8-sig", "utf-8-sig"),
        ("utf-16", "utf-16"),
        ("cp1252", "cp1252"),
    ],
)
def test_detect_encoding(tmp_path, encoding, expected):
    path = tmp_path / "dados.csv"
    path.write_bytes(TEXTO.encode(encoding))
    assert detect_encoding(path) == expected


def test_detect_encoding_latin1(tmp_path):
    path = tmp_path / "dados.csv"
    path.write_bytes(b"a\x81b")  # 0x81 não existe em cp1252
    assert detect_encoding(path) == "latin-1"


def test_detect_encoding_amostra_corta_multibyte(tmp_path):
    path = tmp_path / "dados.csv"
    path.write_bytes(("ã" * 10).encode("utf-8"))
    assert detect_encoding(path, sample_size=5) == "utf-8"


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("a;b;c\n1;2;3\n", ";"),
        ("a,b,c\n1,2,3\n", ","),
        ("a\tb\n1\t2\n", "\t"),
        ("a|b\n1|2\n", "|"),
        ("", ";"),
    ],
)
def test_detect_separator(sample, expected):
    assert detect_separator(sample) == expected


def test_read_csv_raw_preserva_texto(tmp_path):
    path = tmp_path / "dados.csv"
    path.write_bytes(TEXTO.encode("cp1252"))
    df = read_csv_raw(path)
    assert df.columns == ["Município", "CPF", "Valor"]
    assert df.rows() == [("São Paulo", "01234567890", "1.234,56"), ("Vitória", "00011122233", "10,00")]
    assert all(str(t) == "String" for t in df.dtypes)

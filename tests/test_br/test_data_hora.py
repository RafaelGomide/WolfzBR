"""Data e hora (F4 da 1.1, ADR-13, R12): ``wolfz.br.parse_datetime_br``, a
operação ``parse_datetime_br``, o caminho vetorizado, o perfil, a sugestão
e as exportações.
"""

import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st
from openpyxl import load_workbook

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.br import parse_date_br, parse_datetime_br
from wolfz.core.engine import collect
from wolfz.core.profile import profile_column
from wolfz.core.profile.infer import infer_br_type
from wolfz.core.recipe import recipe_from_dict
from wolfz.core.suggest import suggest
from wolfz.export.dados import escrever_csv, escrever_parquet, escrever_xlsx
from wolfz.ops.br import ParseDateBr, map_unique, parse_datetime_serie


def _receita(*passos):
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "t",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


# ---------------------------------------------------------------------------
# Valor (critérios 1, 2, 6 e 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("31/01/2026 14:35:22", datetime(2026, 1, 31, 14, 35, 22)),
        ("31/01/2026 14:35", datetime(2026, 1, 31, 14, 35)),
        ("31/01/2026 8:05", datetime(2026, 1, 31, 8, 5)),
        ("2026-01-31T14:35:22", datetime(2026, 1, 31, 14, 35, 22)),
        ("2026-01-31 14:35:22.123", datetime(2026, 1, 31, 14, 35, 22, 123000)),
        ("2026-01-31 14:35:22.1234567", datetime(2026, 1, 31, 14, 35, 22, 123456)),
        ("46053.6079", datetime(2026, 1, 31, 14, 35, 22, 560000)),  # serial: ao milissegundo
        ("46053,5", datetime(2026, 1, 31, 12, 0)),
        ("31/01/2026", datetime(2026, 1, 31)),  # sem hora: 00:00:00
        ("31 de janeiro de 2026 10:00", datetime(2026, 1, 31, 10, 0)),
        ("  31/01/2026   14:35 ", datetime(2026, 1, 31, 14, 35)),
        (datetime(2026, 1, 31, 14, 35), datetime(2026, 1, 31, 14, 35)),
        (date(2026, 1, 31), datetime(2026, 1, 31)),
    ],
)
def test_mantem_a_hora(valor, esperado):
    assert parse_datetime_br(valor) == esperado


@pytest.mark.parametrize("sufixo", ["Z", "-03:00", "+0000", "+05:30"])
def test_fuso_e_ignorado(sufixo):
    """R12: fica a hora do relógio, sem converter."""
    assert parse_datetime_br(f"2026-01-31T14:35:22{sufixo}") == datetime(2026, 1, 31, 14, 35, 22)


def test_datetime_com_fuso_perde_o_fuso_sem_converter():
    from datetime import UTC

    assert parse_datetime_br(datetime(2026, 1, 31, 14, 35, tzinfo=UTC)) == datetime(2026, 1, 31, 14, 35)


@pytest.mark.parametrize(
    "valor",
    [
        "1e300",
        "-1",
        "31/02/2026 25:61",
        "31/01/2026 25:00",
        "31/01/2026 23:60",
        "31/01/2026 23:59:60",
        "QXZ",
        "31.12.9999 10:00",
        "00/00/0000 00:00",
        "99999.5",
        "19999.5",
        "31/01/2026 14:35 xyz",
        "2026-01-31T14:35:22+3",
        "",
        "-",
        "#N/D",
        None,
    ],
)
def test_valor_estranho_vira_nulo(valor):
    assert parse_datetime_br(valor) is None


@given(st.text(max_size=40))
def test_nunca_levanta_excecao(texto):
    """R12: um ``run`` agendado não cai por causa de uma célula."""
    resultado = parse_datetime_br(texto)
    assert resultado is None or resultado.tzinfo is None


@pytest.mark.parametrize("exemplo", ParseDateBr.examples)
def test_a_data_e_a_mesma_do_parse_date_br(exemplo):
    """Critério 4: a data lida é a do ``parse_date_br``, com os mesmos
    parâmetros (o refator do núcleo não mudou nenhuma data)."""
    params = {k: v for k, v in exemplo["step"].items() if k != "cols"}
    for v in exemplo["input"]["d"]:
        dh = parse_datetime_br(v, **params)
        assert (dh.date() if dh else None) == parse_date_br(v, **params)


# ---------------------------------------------------------------------------
# Caminho vetorizado = parse_datetime_br
# ---------------------------------------------------------------------------


def _casos_vetor():
    r = random.Random(7)
    base = [
        (datetime(1990, 1, 1) + timedelta(seconds=r.randint(0, 1_200_000_000))).strftime(fmt)
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")
        for _ in range(300)
    ]
    bordas = [
        "31/01/2026 23:59:60",
        "31/02/2026 10:00:00",
        "31/01/0099 10:00:00",
        "31/01/1799 10:00:00",
        "31/01/9999 10:00:00",
        "29/02/2024 00:00",
        "29/02/2023 00:00",
        "31/01/2026 24:00",
        "13/13/2026 10:00",
        "2026-13-01 10:00",
        "2026-01-31 14:35:22.5",
        "2026-01-31T14:35:22Z",
        "31/01/2026",
        "46053.6079",
        "QXZ",
        "",
        None,
    ]
    return base + bordas


@pytest.mark.parametrize(
    "params", [{}, {"accept_excel_serial": False}, {"eight_digits": "dmy", "century_pivot": 50}]
)
def test_vetorizado_igual_ao_valor_a_valor(params):
    s = pl.Series("d", _casos_vetor())
    esperado = map_unique(lambda v: parse_datetime_br(v, **params), pl.Datetime("us"))(s)
    assert parse_datetime_serie(s, **params).to_list() == esperado.to_list()


def test_vetorizado_mantem_nome_e_tipo():
    out = parse_datetime_serie(pl.Series("Abertura", ["31/01/2026 14:35:22", None]))
    assert out.name == "Abertura" and out.dtype == pl.Datetime("us")


# ---------------------------------------------------------------------------
# Operação
# ---------------------------------------------------------------------------


def test_op_no_motor():
    df = pl.DataFrame({"Abertura": ["31/01/2026 14:35:22", "QXZ", None], "x": ["1", "2", "3"]})
    out = collect(_receita({"op": "parse_datetime_br", "cols": ["Abertura"]}), df.lazy())
    assert out.schema["Abertura"] == pl.Datetime("us")
    assert out["Abertura"].dtype.time_zone is None
    assert out["Abertura"].to_list() == [datetime(2026, 1, 31, 14, 35, 22), None, None]


def test_parse_date_br_continua_so_com_a_data():
    df = pl.DataFrame({"d": ["31/01/2026 14:35:22"]})
    out = collect(_receita({"op": "parse_date_br", "cols": ["d"]}), df.lazy())
    assert out.schema["d"] == pl.Date and out["d"][0] == date(2026, 1, 31)


_SCRIPT_FUSO = """
import polars as pl, wolfz.ops, sys
from wolfz.core.engine import collect
from wolfz.core.recipe import recipe_from_dict
r = recipe_from_dict({"wolfz_version": "1.0", "name": "t", "created_at": "2026-01-01T00:00:00Z",
    "source": {"type": "csv"}, "steps": [{"id": "s1", "op": "parse_datetime_br", "cols": ["d"]}]})
valores = ["2026-01-31T14:35:22Z", "2026-01-31T14:35:22-03:00", "31/01/2026 23:30", "46053.6079"]
df = pl.DataFrame({"d": valores})
out = collect(r, df.lazy())
out.write_parquet(sys.argv[1])
print(out["d"].to_list(), out.schema["d"])
"""


def test_mesmo_resultado_em_dois_fusos(tmp_path):
    """R12: o resultado e o Parquet não dependem do fuso da máquina."""
    saidas = []
    for i, tz in enumerate(["America/Sao_Paulo", "UTC"]):
        destino = tmp_path / f"{i}.parquet"
        r = subprocess.run(
            [sys.executable, "-c", _SCRIPT_FUSO, str(destino)],
            env={**os.environ, "TZ": tz},
            capture_output=True,
            text=True,
            check=True,
        )
        saidas.append(r.stdout)
        assert pl.read_parquet_schema(destino)["d"].time_zone is None
    assert saidas[0] == saidas[1]


# ---------------------------------------------------------------------------
# Perfil e sugestão (critérios 3 e 8)
# ---------------------------------------------------------------------------


def _coluna_data_hora(n=40):
    return [f"{(i % 28) + 1:02d}/01/2026 {8 + i % 10:02d}:{i % 60:02d}:00" for i in range(n)]


def test_perfil_data_hora():
    p = profile_column(pl.Series("Abertura", _coluna_data_hora()))
    assert p.inferred_type == "data_hora"
    assert p.minimum == datetime(2026, 1, 1, 8, 0) and p.maximum == datetime(2026, 1, 28, 15, 27)


def test_perfil_de_coluna_ja_convertida():
    s = pl.Series("d", [datetime(2026, 1, 31, 14, 35), datetime(2025, 1, 1, 8, 0), None])
    p = profile_column(s)
    assert (p.minimum, p.maximum) == (datetime(2025, 1, 1, 8, 0), datetime(2026, 1, 31, 14, 35))


def test_inspect_mostra_dia_e_hora():
    from wolfz.cli import _valor

    assert _valor(datetime(2026, 1, 31, 14, 35, 22)) == "31/01/2026 14:35"
    assert _valor(date(2026, 1, 31)) == "31/01/2026"


@pytest.mark.parametrize(
    ("valores", "tipo"),
    [
        (["31/01/2026", "01/02/2026", "02/02/2026 00:00"], "data"),  # só data: igual a hoje
        (["31/01/2026 10:00", "01/02/2026 11:30", "02/02/2026"], "data_hora"),  # 2 de 3 com hora
        (["31/01/2026 10:00", "01/02/2026", "02/02/2026"], "data"),  # 1 de 3: não passa da metade
        (["1.234,56", "10,00"], "moeda"),
        (["SIM", "NÃO"], "booleano"),
    ],
)
def test_inferencia(valores, tipo):
    assert infer_br_type(valores)[0] == tipo


def test_sugere_parse_datetime_br_e_nao_volta():
    df = pl.DataFrame({"Abertura": [*_coluna_data_hora(39), "QXZ"], "Dia": ["31/01/2026"] * 40})
    sugestoes = {s.steps[0]["op"]: s for s in suggest(df) if s.rule == "data"}
    assert sugestoes["parse_datetime_br"].steps[0]["cols"] == ["Abertura"]
    assert sugestoes["parse_date_br"].steps[0]["cols"] == ["Dia"]
    motivo = sugestoes["parse_datetime_br"].reason
    assert motivo.startswith("A coluna Abertura tem data e hora (31/01/2026 14:35:22).")
    assert motivo.endswith("Muda 40 células; 1 vira vazio porque não é data.")
    assert "QXZ" not in motivo
    passos = [{"id": f"s{i}", **s.steps[0]} for i, s in enumerate(sugestoes.values(), 1)]
    convertida = collect(_receita(*[{k: v for k, v in p.items() if k != "id"} for p in passos]), df.lazy())
    assert not [s for s in suggest(convertida) if s.rule == "data"]


# ---------------------------------------------------------------------------
# Exportações (critério 5)
# ---------------------------------------------------------------------------


@pytest.fixture
def convertida():
    df = pl.DataFrame({"Abertura": ["31/01/2026 14:35:22", "2026-01-31 14:35:22.123", None]})
    return collect(_receita({"op": "parse_datetime_br", "cols": ["Abertura"]}), df.lazy())


def test_csv_parquet_xlsx(convertida, tmp_path):
    escrever_csv(convertida, tmp_path / "a.csv")
    linhas = (tmp_path / "a.csv").read_text(encoding="utf-8-sig").splitlines()
    assert linhas == ["Abertura", "2026-01-31 14:35:22", "2026-01-31 14:35:22.123", ""]
    escrever_parquet(convertida, tmp_path / "a.parquet")
    tipo = pl.read_parquet_schema(tmp_path / "a.parquet")["Abertura"]
    assert isinstance(tipo, pl.Datetime) and tipo.time_zone is None
    escrever_xlsx(convertida, tmp_path / "a.xlsx")
    celula = load_workbook(tmp_path / "a.xlsx").active["A2"]
    assert celula.is_date and celula.value == datetime(2026, 1, 31, 14, 35, 22)
    assert "hh:mm" in celula.number_format.lower()


def test_pbip_e_tableau(convertida):
    from wolfz.export.pbip import _coluna
    from wolfz.export.tableau import _tipo_tds

    coluna = _coluna("Abertura", convertida.schema["Abertura"], None)
    assert (coluna.tipo_tmdl, coluna.tipo_m) == ("dateTime", "type datetime")
    assert _tipo_tds(convertida.schema["Abertura"])[0] == "datetime"


def test_hyper_sem_fuso(convertida, tmp_path):
    pytest.importorskip("tableauhyperapi", reason="extra wolfzbr[tableau] não instalado")
    from wolfz.export.tableau import _tipo_hyper

    assert str(_tipo_hyper(convertida["Abertura"], None)) == "TIMESTAMP"

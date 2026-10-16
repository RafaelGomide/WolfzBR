from datetime import date

import polars as pl
from polars.testing import assert_frame_equal

from wolfz.br.datas import parse_date_br
from wolfz.br.numeros import parse_brl
from wolfz.ops.tabela import (
    apply_parser,
    clean_column_names,
    drop_empty_columns,
    drop_empty_rows,
    drop_repeated_headers,
    drop_total_rows,
    fill_down,
    normalize_text_columns,
    promote_header,
)


def test_apply_parser_infere_dtype():
    df = pl.DataFrame({"valor": ["R$ 1,00", "(2,50)", None]})
    out = apply_parser(df, "valor", parse_brl)
    assert out.schema["valor"] == pl.Float64
    assert out["valor"].to_list() == [1.0, -2.5, None]


def test_apply_parser_com_sufixo_e_dtype():
    df = pl.DataFrame({"data": ["31/12/2024", "x"]})
    out = apply_parser(df, ["data"], lambda v: parse_date_br(v), pl.Date, suffix="_dt")
    assert out.columns == ["data", "data_dt"]
    assert out["data_dt"].to_list() == [date(2024, 12, 31), None]


def test_clean_column_names():
    df = pl.DataFrame({"﻿Regiao - Sigla": [1], "Valor": [2], "valor": [3]})
    assert clean_column_names(df).columns == ["regiao_sigla", "valor", "valor_2"]


def test_normalize_text_columns():
    df = pl.DataFrame({"a": ["  x\xa0 y ", "#N/D", "z​"], "n": [1, 2, 3]})
    out = normalize_text_columns(df)
    assert out["a"].to_list() == ["x y", None, "z"]
    assert out["n"].to_list() == [1, 2, 3]


def test_normalize_text_columns_sem_marcadores():
    df = pl.DataFrame({"a": ["x", "y"]})
    assert_frame_equal(normalize_text_columns(df), df)


def test_drop_empty_rows_e_columns():
    df = pl.DataFrame({"a": ["1", None, " "], "b": [None, None, ""], "c": ["x", None, None]})
    assert drop_empty_rows(df).height == 1
    assert drop_empty_columns(df).columns == ["a", "c"]


def test_drop_repeated_headers():
    df = pl.DataFrame({"Região": ["Sul", "Região", "Norte"], "Valor": ["1", "Valor", "2"]})
    assert drop_repeated_headers(df)["Região"].to_list() == ["Sul", "Norte"]


def test_drop_total_rows():
    df = pl.DataFrame(
        {
            "grupo": ["A", None, "Total Geral", "B"],
            "item": ["x", "Subtotal Região Sul", None, "Totalmente"],
            "v": [1, 2, 3, 4],
        }
    )
    kept, removed = drop_total_rows(df, return_removed=True)
    assert kept["v"].to_list() == [1, 4]
    assert removed["v"].to_list() == [2, 3]
    assert drop_total_rows(df, label_columns=["grupo"])["v"].to_list() == [1, 2, 4]


def test_fill_down():
    df = pl.DataFrame({"regiao": ["Sul", None, "", "Norte", None]})
    assert fill_down(df, "regiao")["regiao"].to_list() == ["Sul", "Sul", "Sul", "Norte", "Norte"]


def test_promote_header_uma_linha():
    df = pl.DataFrame({"column_1": ["Nome", "Ana"], "column_2": [None, "1"]})
    out = promote_header(df)
    assert out.columns == ["Nome", "coluna_2"]
    assert out.height == 1


def test_promote_header_multinivel():
    df = pl.DataFrame(
        {
            "c1": ["2024", "Jan", "1"],
            "c2": [None, "Fev", "2"],
            "c3": ["2025", "Jan", "3"],
            "c4": [None, "Jan", "4"],
        }
    )
    assert promote_header(df, n_rows=2).columns == ["2024_Jan", "2024_Fev", "2025_Jan", "2025_Jan_2"]

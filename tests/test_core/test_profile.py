import polars as pl
import pytest

from wolfz.core.profile import infer_br_type, quick_profile, value_shape


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["11.222.333/0001-81", "00.000.000/0001-91"], "cnpj"),
        (["123.456.789-09", "52998224725"], "cpf"),
        (["29100-000", "01310-100"], "cep"),
        (["31/12/2024", "01/01/2025"], "data"),
        (["jan/24", "fev/24"], "mes_ano"),
        (["12,5%", "3%"], "percentual"),
        (["001", "002", "010"], "codigo"),
        (["R$ 1,00", "R$ 2.000,50", "(3,00)"], "moeda"),
        (["1,5", "2", "3.000"], "numero"),
        (["01,5", "2"], "codigo"),  # número com zero à esquerda continua texto
        (["Sim", "Não"], "booleano"),
        (["Vitória", "Serra"], "texto"),
        ([None, "", "#N/D"], "vazio"),
    ],
)
def test_infer_br_type(values, expected):
    assert infer_br_type(values)[0] == expected


def test_infer_br_type_taxa():
    tipo, taxa = infer_br_type(["R$ 1,00"] * 9 + ["abc"])
    assert (tipo, taxa) == ("moeda", 0.9)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123.456.789-09", "999.999.999-99"),
        ("R$ 1.234,56", "a$ 9.999,99"),
        (None, "<null>"),
    ],
)
def test_value_shape(value, expected):
    assert value_shape(value) == expected


def test_quick_profile():
    df = pl.DataFrame({"cpf": ["123.456.789-09", "12345678909", None, "#N/D"]})
    perfil = quick_profile(df).row(0, named=True)
    assert perfil["coluna"] == "cpf"
    assert perfil["nulos"] == 1
    assert perfil["vazios_ou_marcadores"] == 1
    assert perfil["distintos"] == 4
    assert perfil["formas"].startswith("999.999.999-99 (1)")

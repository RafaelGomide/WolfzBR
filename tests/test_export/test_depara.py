"""``normalize_municipio`` e o de-para exportado (F2.C3, F2.C5, ADR-7)."""

import polars as pl
import pytest
from m_parser import parse_m

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.recipe import RecipeError, recipe_from_dict
from wolfz.export.depara import ARQUIVO_DEPARA, depara_municipios, gravar_depara
from wolfz.export.m import parameter_to_m, recipe_to_m
from wolfz.export.python import recipe_to_python
from wolfz.ops.municipio import PARAMETRO_DEPARA, aplicar_depara_municipios

ENTRADA = pl.DataFrame(
    {"municipio": ["Vitória", "V. Velha", "Guarapary", None, "Serra"], "uf": ["ES", "ES", "ES", "ES", "ES"]}
)


def _receita(**passo):
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "municípios",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": "s1", "op": "normalize_municipio", "col": "municipio", "uf_col": "uf", **passo}],
        }
    )


def test_codigo_manual_precisa_existir():
    with pytest.raises(RecipeError, match="não é um código de município"):
        _receita(manual={"Guarapary|ES": "1234567"})
    with pytest.raises(RecipeError, match="chave vazia"):
        _receita(manual={" ": None})


def test_manual_vale_mais_que_o_casamento():
    receita = _receita(manual={"Guarapary|ES": "3202405", "Serra|ES": None})
    saida = receita.steps[0].to_polars(ENTRADA.lazy()).collect()
    assert saida["municipio_status"].to_list() == [
        "exato",
        "abreviacao",
        "manual",
        None,
        "sem_correspondencia",
    ]
    assert saida["municipio_nome_ibge"].to_list() == ["Vitória", "Vila Velha", "Guarapari", None, None]


def test_depara_tem_uma_linha_por_valor():
    depara = depara_municipios(_receita(), ENTRADA.lazy())
    assert depara.columns == [
        "passo",
        "valor",
        "uf",
        "codigo_ibge",
        "nome_ibge",
        "status",
        "nota",
        "sugestao",
    ]
    assert depara.height == 4  # o vazio fica de fora
    revisar = depara.filter(pl.col("status") == "revisar").row(0, named=True)
    assert revisar["valor"] == "Guarapary"
    assert revisar["codigo_ibge"] is None
    assert revisar["sugestao"] == "Guarapari (ES)"


def test_valor_novo_fica_fora_do_depara(tmp_path):
    """O de-para foi gerado no mês 1; o mês 2 traz um município novo. A
    linha continua lá, com status fora_do_depara (ADR-7)."""
    caminho = tmp_path / ARQUIVO_DEPARA
    gravar_depara(depara_municipios(_receita(), ENTRADA.lazy()), caminho)
    mes2 = pl.DataFrame({"municipio": ["Vitória", "Linhares", None], "uf": ["ES", "ES", None]})
    saida = aplicar_depara_municipios(mes2.lazy(), "s1", "municipio", "uf", str(caminho)).collect()
    assert saida.height == 3
    assert saida["municipio_status"].to_list() == ["exato", "fora_do_depara", None]
    assert saida["municipio_codigo_ibge"].to_list() == ["3205309", None, None]


def test_depara_abre_no_excel(tmp_path):
    caminho = tmp_path / ARQUIVO_DEPARA
    gravar_depara(depara_municipios(_receita(), ENTRADA.lazy()), caminho)
    bruto = caminho.read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf")
    assert (
        bruto[3:].decode("utf-8").splitlines()[0]
        == "passo;valor;uf;codigo_ibge;nome_ibge;status;nota;sugestao"
    )


def test_receita_sem_municipio_nao_tem_depara():
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": "s1", "op": "trim", "cols": ["municipio"]}],
        }
    )
    assert depara_municipios(receita, ENTRADA.lazy()) is None


def test_m_pede_o_parametro_do_depara():
    m = recipe_to_m(_receita())
    assert f"File.Contents({PARAMETRO_DEPARA})" in m
    assert f"parâmetro {PARAMETRO_DEPARA}" in m
    assert '"fora_do_depara"' in m
    parametro = parameter_to_m("C:\\saida\\depara_municipios.csv", "municípios", PARAMETRO_DEPARA)
    assert f"// Nome {PARAMETRO_DEPARA}, Tipo Texto" in parametro
    assert all(r["ok"] for r in parse_m([m, parametro]))


def test_script_le_o_depara_ao_lado():
    script = recipe_to_python(_receita())
    assert 'DEPARA_MUNICIPIOS = Path(__file__).with_name("depara_municipios.csv")' in script
    assert 'aplicar_depara_municipios(lf, "s1", "municipio", "uf", DEPARA_MUNICIPIOS)' in script
    assert "rapidfuzz" not in script


def test_verificacao_reprovada_nao_impede_o_depara():
    """O de-para não roda as verificações: uma que reprova nos dados de hoje
    (aqui, município vazio) não pode impedir a exportação do M."""
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [
                {"id": "s1", "op": "assert", "check": "not_null", "cols": ["municipio"]},
                {"id": "s2", "op": "normalize_municipio", "col": "municipio", "uf_col": "uf"},
                {"id": "s3", "op": "assert", "check": "row_count_min", "min_rows": 1000},
            ],
        }
    )
    assert depara_municipios(receita, ENTRADA.lazy()).height == 4

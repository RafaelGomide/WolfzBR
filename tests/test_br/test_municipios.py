"""Municípios do IBGE (F2.C1–F2.C3): a tabela empacotada e o casamento."""

import re
from pathlib import Path

import polars as pl
import pytest

from wolfz.br.constants import UFS
from wolfz.br.municipios import buscar, casar_municipio, chave_municipio, por_codigo, sugestoes, tabela

RAIZ = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Tabela (F2.C1) e NOTICE (F2.C2)
# ---------------------------------------------------------------------------


def test_tabela_tem_todos_os_municipios():
    df = tabela()
    assert df.columns == ["codigo_ibge", "codigo_ibge_6", "nome", "nome_normalizado", "uf"]
    assert df.height >= 5570
    assert df["codigo_ibge"].n_unique() == df.height
    assert set(df["uf"]) == set(UFS)
    assert df["codigo_ibge"].str.contains(r"^\d{7}$").all()
    assert (df["codigo_ibge"].str.slice(0, 6) == df["codigo_ibge_6"]).all()
    assert df["nome_normalizado"].to_list() == [chave_municipio(n) for n in df["nome"]]


def test_notice_cita_a_fonte_e_a_extracao():
    notice = (RAIZ / "NOTICE").read_text(encoding="utf-8")
    assert "IBGE" in notice
    assert "servicodados.ibge.gov.br" in notice
    m = re.search(r"Extraído em (\d{4}-\d{2}-\d{2}) \((\d+) municípios\)", notice)
    assert m, "NOTICE precisa da data da extração e do total"
    assert int(m[2]) == tabela().height


def test_capitais():
    capitais = {"3205309": ("Vitória", "ES"), "3550308": ("São Paulo", "SP"), "5300108": ("Brasília", "DF")}
    for codigo, (nome, uf) in capitais.items():
        m = por_codigo(codigo)
        assert (m.nome, m.uf) == (nome, uf)
    assert por_codigo("9999999") is None


# ---------------------------------------------------------------------------
# Casamento (F2.C3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Alta Floresta D'Oeste", "alta floresta doeste"),
        ("  SÃO   Paulo ", "sao paulo"),
        ("Embu-Guaçu", "embu guacu"),
        (f"Pau D{chr(0x2019)}Arco", "pau darco"),  # apóstrofo tipográfico
        (None, ""),
    ],
)
def test_chave_municipio(nome, esperado):
    assert chave_municipio(nome) == esperado


@pytest.mark.parametrize(
    ("valor", "uf", "status", "codigo"),
    [
        ("Vitória", "ES", "exato", "3205309"),
        ("VITORIA", None, "exato", "3205309"),
        ("vitória", "Espírito Santo", "exato", "3205309"),
        ("V. Velha", "ES", "abreviacao", "3205200"),
        ("Sto. Antônio de Pádua", "RJ", "abreviacao", "3304706"),
        ("S. Mateus", "ES", "abreviacao", "3204906"),
        ("Cachoeiro Itapemirim", "ES", "fuzzy", "3201209"),
        ("Guarapary", "ES", "revisar", None),
        ("Bom Jesus", None, "revisar", None),
        ("Bom Jesus", "RS", "exato", "4302303"),
    ],
)
def test_casar_municipio(valor, uf, status, codigo):
    r = casar_municipio(valor, uf)
    assert r.status == status
    assert (r.municipio.codigo if r.municipio else None) == codigo


def test_revisar_nunca_aplica_e_traz_candidatos():
    r = casar_municipio("Guarapary", "ES")
    assert r.municipio is None
    assert r.candidatos[0][0].nome == "Guarapari"
    assert r.nota < 90
    # Com o limiar mais baixo, o mesmo valor passa a ser aplicado como fuzzy.
    assert casar_municipio("Guarapary", "ES", limiar=85).status == "fuzzy"


def test_fuzzy_fica_na_uf():
    """Com UF, o parecido só vem dela: 'Vila Velhaa' do PI não vira Vila Velha (ES)."""
    assert casar_municipio("Vila Velhaa", "ES").municipio.uf == "ES"
    r = casar_municipio("Vila Velhaa", "PI")
    assert r.status == "revisar"
    assert all(m.uf == "PI" for m, _ in r.candidatos)


def test_vazio_e_marcador_de_ausencia():
    assert casar_municipio(None) is None
    assert casar_municipio("  ") is None
    assert casar_municipio("#N/D") is None


def test_sugestoes_e_busca():
    assert [m.nome for m, _ in sugestoes("Vitoria", "ES", 1)] == ["Vitória"]
    nomes = [m.nome for m, _ in buscar("vila v", "ES")]
    assert "Vila Velha" in nomes and "Vila Valério" in nomes
    assert buscar("") == []
    assert len(buscar("sao", n=3)) == 3


def test_tabela_e_somente_leitura_em_cache():
    assert tabela() is tabela()
    assert isinstance(tabela(), pl.DataFrame)

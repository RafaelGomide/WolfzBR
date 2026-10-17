"""Regressão da detecção no corpus (§12.3 do design: piorar a detecção
reprova o build).

``FALHAS_CONHECIDAS`` lista o que a detecção v1 ainda erra, com o motivo.
Um arquivo que passa a errar fora dessa lista é regressão. Um que sai da
lista (a detecção melhorou) também falha o teste, para a lista ser
atualizada e a melhora ficar registrada.
"""

import pytest
from corpus_lib import _script

FALHAS_CONHECIDAS = {
    "area": {
        "anuario_tabelas_lado_a_lado",  # duas tabelas lado a lado viram uma (split_table, F2)
        "ibge_ipca_serie_historica",  # cabeçalho repetido a cada página quebra a área
    },
    "cabecalho": {
        # Cabeçalho multinível (F2.D): a v1 acha só a última linha.
        "boletim_saude_multinivel",
        "ibge_ipca_serie_historica",
        "ibge_lspa_2025_01",
        "ibge_ppm_2012_linhares",
        "sidra_pam_area",
    },
    "totais": {
        "erp_totvs_razao",  # 'SALDO ANTERIOR' não é total, mas também sai
        # Brasil e regiões como subtotais: sem palavra-chave nem negrito (.xls/.ods).
        "ibge_estimativa_populacao_2021",
        "ibge_estimativa_populacao_2024",
        "ibge_ppm_2012_linhares",  # subtotais por porte, sem negrito no .xls
    },
    "fill_down": set(),
}


@pytest.fixture(scope="module")
def resultados():
    return _script("medir_deteccao").medir()


@pytest.mark.parametrize("criterio", sorted(FALHAS_CONHECIDAS))
def test_deteccao_sem_regressao(resultados, criterio):
    erros = {r.nome for r in resultados if r.erro or not r.acertos[criterio]}
    novos = erros - FALHAS_CONHECIDAS[criterio]
    corrigidos = (FALHAS_CONHECIDAS[criterio] - erros) & {r.nome for r in resultados}
    detalhes = {r.nome: r.detalhes.get(criterio, r.erro) for r in resultados if r.nome in novos}
    assert not novos, f"a detecção piorou em {criterio}: {detalhes}"
    assert not corrigidos, (
        f"a detecção melhorou em {criterio}: tire {sorted(corrigidos)} de FALHAS_CONHECIDAS"
    )


def test_medicao_em_markdown(resultados):
    medir = _script("medir_deteccao")
    texto = medir.markdown(resultados)
    assert texto.startswith("| Arquivo | Área | Cabeçalho | Totais | fill_down |")
    assert f"**{len(resultados)} arquivos**" in texto
    assert medir.resumo(resultados)["arquivos"] == len(resultados)

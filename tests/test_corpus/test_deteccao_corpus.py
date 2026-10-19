"""Regressão da detecção no corpus (§12.3 do design: piorar a detecção
reprova o build).

``FALHAS_CONHECIDAS`` lista o que a detecção ainda erra, com o motivo.
Um arquivo que passa a errar fora dessa lista é regressão. Um que sai da
lista (a detecção melhorou) também falha o teste, para a lista ser
atualizada e a melhora ficar registrada.
"""

import pytest
from corpus_lib import _script

FALHAS_CONHECIDAS = {
    # Cabeçalho repetido a cada página (com título e linhas vazias): cada
    # página vira uma tabela e a área fica na primeira.
    "area": {"ibge_ipca_serie_historica"},
    "cabecalho": {"ibge_ipca_serie_historica"},
    "totais": {
        "erp_totvs_razao",  # 'SALDO ANTERIOR' é linha a tirar, mas não é soma nem tem palavra de total
    },
    "fill_down": set(),
    "tabelas": {"ibge_ipca_serie_historica"},
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
    assert texto.startswith("| Arquivo | Área | Cabeçalho | Totais | fill_down | Tabelas |")
    assert f"**{len(resultados)} arquivos**" in texto
    assert medir.resumo(resultados)["arquivos"] == len(resultados)


def test_passos_da_deteccao_rodam_em_todo_o_corpus():
    """A detecção propõe a receita inicial (F1.C7); com o catálogo da F1.E,
    essa receita tem de validar e rodar em todo arquivo do corpus."""
    import polars as pl
    from corpus_lib import entradas

    import wolfz
    from wolfz.core.detect import detect_structure
    from wolfz.core.ingest import read_sheet
    from wolfz.core.ingest.csv import open_csv_lazy
    from wolfz.core.recipe import recipe_from_dict

    falhas = {}
    for entrada in entradas():
        if entrada.original is None:
            continue
        aba = entrada.estrutura["aba"]
        if entrada.original.suffix == ".csv":
            with open_csv_lazy(entrada.original, has_header=False) as lf:
                df, estrutura, tipo = lf.collect(), None, "csv"
        else:
            dados = read_sheet(entrada.original, aba)
            df, estrutura, tipo = dados.frame, dados.structure, "excel"
        passos = detect_structure(df, estrutura).to_steps()
        receita = recipe_from_dict(
            {
                "wolfz_version": "0.1",
                "name": entrada.nome,
                "created_at": "2026-01-01T00:00:00Z",
                "source": {"type": tipo, "sheet": aba},
                "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
            }
        )
        try:
            resultado = wolfz.run(receita, entrada.original)
        except Exception as exc:
            falhas[entrada.nome] = f"{type(exc).__name__}: {exc}"
            continue
        assert isinstance(resultado, pl.DataFrame)
        assert resultado.height > 0, entrada.nome
    assert not falhas, falhas

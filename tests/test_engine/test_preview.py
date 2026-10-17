import os
import time

import polars as pl
import pytest
from filelock import FileLock

from wolfz.core.engine import StepError
from wolfz.core.engine.cache import Checkpoints, chave_passo, chaves, recolher
from wolfz.core.engine.preview import Page, preview, preview_project
from wolfz.core.ingest import import_file
from wolfz.core.recipe import recipe_from_dict
from wolfz.core.workspace import Workspace

PASSOS = [
    {"op": "header_rows", "n": 1},
    {"op": "parse_decimal_br", "cols": ["valor"]},  # checkpoint completo
    {"op": "sort", "by": ["valor"], "descending": True},  # checkpoint completo
    {"op": "filter", "col": "uf", "match": "not_equals", "value": "SP"},
]


def _recipe(passos=PASSOS, ids=None):
    ids = ids or [f"s{i}" for i in range(1, len(passos) + 1)]
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "preview",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel"},
            "steps": [{"id": i, **p} for i, p in zip(ids, passos, strict=True)],
        }
    )


@pytest.fixture
def raw(tmp_path):
    n = 50
    ufs = ["ES", "SP", "RJ", "MG", "BA"]
    grade = pl.DataFrame(
        {
            "A": ["uf", *[ufs[i % 5] for i in range(n)]],
            "B": ["valor", *[f"{i * 37 % 101},{i % 10}0" for i in range(n)]],
        }
    )
    path = tmp_path / "raw.parquet"
    grade.write_parquet(path)
    return path


def _sem_cache(raw, recipe, step=None):
    """Referência: a tabela inteira depois do passo, sem cache nenhum."""
    lf = pl.scan_parquet(raw)
    for passo in recipe.steps:
        lf = passo.to_polars(lf)
        if passo.id == step:
            break
    return lf.collect()


# ---------------------------------------------------------------------------
# Chaves (F1.F1)
# ---------------------------------------------------------------------------


def test_chave_nao_depende_do_id():
    a = _recipe(ids=["s1", "s2", "s3", "s4"])
    b = _recipe(ids=["s7", "s8", "s9", "s10"])
    assert chaves("raw", a.steps) == chaves("raw", b.steps)


def test_editar_o_passo_n_muda_so_de_n_em_diante():
    original = chaves("raw", _recipe().steps)
    passos = [*PASSOS[:2], {"op": "sort", "by": ["valor"]}, PASSOS[3]]
    editada = chaves("raw", _recipe(passos).steps)
    assert original[:3] == editada[:3]  # raw, s1, s2
    assert all(x != y for x, y in zip(original[3:], editada[3:], strict=True))


def test_chave_depende_do_raw():
    assert chaves("a", _recipe().steps)[-1] != chaves("b", _recipe().steps)[-1]
    assert chave_passo("x", _recipe().steps[0]) != chave_passo("y", _recipe().steps[0])


# ---------------------------------------------------------------------------
# Preview (F1.F2 e F1.F3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step", [None, "s1", "s2", "s3", "s4"])
@pytest.mark.parametrize(("offset", "limit"), [(0, 5), (7, 10), (35, 200)])
def test_pagina_igual_ao_calculo_sem_cache(raw, tmp_path, step, offset, limit):
    recipe = _recipe()
    esperado = _sem_cache(raw, recipe, step)
    cache = Checkpoints(tmp_path / "ck")
    for _ in range(2):  # a segunda vem do cache e tem de ser igual
        page = preview(raw, "k", recipe, step, offset, limit, cache)
        assert page.frame.equals(esperado.slice(offset, limit))
        assert page.total_rows == esperado.height
    assert page.origem == "pagina"


def test_sem_cache_nao_grava_nada(raw, tmp_path):
    page = preview(raw, "k", _recipe(), None, 0, 5)
    assert page.origem == "raw" and page.checkpoints_gravados == []
    assert not (tmp_path / "ck").exists()


def test_raw_e_receita_inteira(raw, tmp_path):
    cache = Checkpoints(tmp_path / "ck")
    assert preview(raw, "k", _recipe(), "raw", 0, 3, cache).frame.row(0) == ("uf", "valor")
    assert preview(raw, "k", _recipe(), None, 0, 3, cache).frame.columns == ["uf", "valor"]


def test_checkpoint_completo_dos_passos_caros(raw, tmp_path):
    cache = Checkpoints(tmp_path / "ck")
    page = preview(raw, "k", _recipe(), "s4", 0, 5, cache)
    assert page.checkpoints_gravados == [2, 3]  # parse_decimal_br e sort
    assert page.origem == "checkpoint:3"
    ks = chaves("k", _recipe().steps)
    assert cache.completo(ks[3]) is not None
    assert cache.completo(ks[4]) is None  # filter é barato: só a página


def test_editar_o_ultimo_passo_reaproveita_os_checkpoints(raw, tmp_path):
    cache = Checkpoints(tmp_path / "ck")
    preview(raw, "k", _recipe(), "s4", 0, 5, cache)
    editada = _recipe([*PASSOS[:3], {"op": "filter", "col": "uf", "match": "equals", "value": "ES"}])
    page = preview(raw, "k", editada, "s4", 0, 5, cache)
    assert page.checkpoints_gravados == []
    assert page.origem == "checkpoint:3"
    assert set(page.frame["uf"]) == {"ES"}


def test_editar_passo_antes_do_sort_refaz_o_checkpoint(raw, tmp_path):
    cache = Checkpoints(tmp_path / "ck")
    preview(raw, "k", _recipe(), "s4", 0, 5, cache)
    editada = _recipe(
        [PASSOS[0], {"op": "parse_decimal_br", "cols": ["valor"], "dash_is_zero": True}, *PASSOS[2:]]
    )
    assert preview(raw, "k", editada, "s4", 0, 5, cache).checkpoints_gravados == [2, 3]


def test_passo_inexistente_e_limites(raw):
    with pytest.raises(ValueError, match="não tem o passo 's9'"):
        preview(raw, "k", _recipe(), "s9")
    with pytest.raises(ValueError, match="limit"):
        preview(raw, "k", _recipe(), None, 0, 0)
    with pytest.raises(ValueError, match="offset"):
        preview(raw, "k", _recipe(), None, -1, 10)


def test_erro_de_dados_aponta_o_passo(raw, tmp_path):
    # Comparar texto com número só falha na execução: o motor localiza o passo.
    passos = [PASSOS[0], {"op": "filter", "col": "uf", "match": "gt", "value": 3}]
    with pytest.raises(StepError) as exc:
        preview(raw, "k", _recipe(passos), None, 0, 5, Checkpoints(tmp_path / "ck"))
    assert exc.value.step_id == "s2"


def test_erro_ao_gravar_checkpoint_aponta_o_passo(raw, tmp_path):
    passos = [PASSOS[0], {"op": "filter", "col": "uf", "match": "gt", "value": 3}, PASSOS[2]]
    with pytest.raises(StepError) as exc:
        preview(raw, "k", _recipe(passos), None, 0, 5, Checkpoints(tmp_path / "ck"))
    assert exc.value.step_id == "s2"


def test_page_to_dict(raw):
    d = preview(raw, "k", _recipe(), "s2", 0, 2).to_dict()
    assert d["columns"] == [{"name": "uf", "dtype": "String"}, {"name": "valor", "dtype": "Float64"}]
    assert d["total_rows"] == 50 and len(d["rows"]) == 2 and d["offset"] == 0
    assert isinstance(Page(pl.DataFrame(), 0, 0).columns, list)


def test_preview_de_projeto(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["uf", "valor"])
    for uf, v in [("ES", "1,5"), ("SP", "2,5"), ("RJ", "3,5")]:
        wb.active.append([uf, v])
    planilha = tmp_path / "p.xlsx"
    wb.save(planilha)
    projeto = import_file(planilha, workspace=Workspace(tmp_path / "home"))
    page = preview_project(projeto.path, _recipe(), None, 0, 10)
    assert page.frame.to_dict(as_series=False) == {"uf": ["RJ", "ES"], "valor": [3.5, 1.5]}
    assert (projeto.path / "checkpoints").is_dir()


# ---------------------------------------------------------------------------
# Limpeza LRU (F1.F4)
# ---------------------------------------------------------------------------


def _entrada(projeto, chave, tamanho, idade):
    pasta = projeto / "checkpoints" / chave
    pasta.mkdir(parents=True)
    (pasta / "completo.parquet").write_bytes(b"x" * tamanho)
    instante = time.time() - idade
    os.utime(pasta, (instante, instante))
    return pasta


def _projeto(home, nome):
    projeto = home / "projects" / nome
    projeto.mkdir(parents=True)
    (projeto / "raw.parquet").write_bytes(b"raw")
    return projeto


def test_recolhe_do_menos_usado_ate_caber(tmp_path):
    p = _projeto(tmp_path, "A")
    velho = _entrada(p, "velho", 100, idade=300)
    medio = _entrada(p, "medio", 100, idade=200)
    novo = _entrada(p, "novo", 100, idade=100)
    r = recolher(tmp_path / "projects", limite=150)
    assert (r.antes, r.depois, r.apagados) == (300, 100, 2)
    assert not velho.exists() and not medio.exists() and novo.exists()
    assert (p / "raw.parquet").exists()  # o raw nunca é recolhido


def test_dentro_do_limite_nao_apaga(tmp_path):
    p = _projeto(tmp_path, "A")
    _entrada(p, "a", 10, idade=10)
    assert recolher(tmp_path / "projects", limite=100).apagados == 0
    assert recolher(tmp_path / "nada", limite=0).apagados == 0


def test_pula_projeto_aberto_e_protegido(tmp_path):
    aberto, protegido, livre = (_projeto(tmp_path, n) for n in ("A", "B", "C"))
    a = _entrada(aberto, "a", 100, idade=300)
    b = _entrada(protegido, "b", 100, idade=200)
    c = _entrada(livre, "c", 100, idade=100)
    lock = FileLock(aberto / ".lock")
    lock.acquire()
    try:
        r = recolher(tmp_path / "projects", limite=0, protegidos={protegido})
    finally:
        lock.release()
    assert r.pulados_por_lock == 1
    assert a.exists() and b.exists() and not c.exists()


def test_uso_atualiza_a_ordem_do_lru(raw, tmp_path):
    home = tmp_path / "home"
    projeto = _projeto(home, "A")
    cache = Checkpoints(projeto / "checkpoints")
    preview(raw, "k", _recipe(), "s1", 0, 5, cache)
    preview(raw, "k", _recipe(), "s4", 0, 5, cache)
    pastas = sorted((projeto / "checkpoints").iterdir(), key=lambda p: p.stat().st_mtime)
    antiga = time.time() - 1000
    for pasta in pastas:
        os.utime(pasta, (antiga, antiga))
    preview(raw, "k", _recipe(), "s1", 0, 5, cache)  # toca só a pasta do s1
    s1 = Checkpoints(projeto / "checkpoints").pasta(chaves("k", _recipe().steps)[1])
    assert s1.stat().st_mtime > antiga + 500


def test_preview_de_projeto_recolhe_o_cache_dos_outros(tmp_path):
    import openpyxl

    home = tmp_path / "home"
    outro = _projeto(home, "OUTRO")
    velho = _entrada(outro, "velho", 10_000, idade=1000)
    wb = openpyxl.Workbook()
    wb.active.append(["uf", "valor"])
    wb.active.append(["ES", "1,5"])
    planilha = tmp_path / "p.xlsx"
    wb.save(planilha)
    projeto = import_file(planilha, workspace=Workspace(home))
    page = preview_project(projeto.path, _recipe(), None, 0, 10, limite_cache=1)
    assert page.checkpoints_gravados  # gravou checkpoint completo -> recolheu
    assert not velho.exists()  # o cache do outro projeto saiu
    assert (projeto.path / "checkpoints").is_dir()  # o do projeto aberto ficou


def test_benchmark_roda_pequeno(tmp_path):
    import importlib.util
    import sys
    from pathlib import Path

    caminho = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_preview.py"
    spec = importlib.util.spec_from_file_location("benchmark_preview", caminho)
    bench = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_preview"] = bench
    spec.loader.exec_module(bench)
    r = bench.medir(2_000, 3, tmp_path)
    assert r["linhas"] == 2_000 and r["cache"] is True
    assert r["edicao_ultimo_passo"]["p50_ms"] > 0
    assert set(r) >= {"abertura_ms", "rolagem", "dentro_do_slo"}

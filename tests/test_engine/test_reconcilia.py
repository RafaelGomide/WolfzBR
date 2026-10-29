"""Reconciliação de linhas por passo (F1 da 1.1, ADR-10).

``reconciliar``/``wolfz.run_report`` executam a receita em trechos e contam
as linhas depois de cada passo que muda o número de linhas; ``contagens``
faz o mesmo sobre o cache do preview, para a API. As duas têm de dar os
mesmos números, e a tabela tem de ser a mesma do ``wolfz.run``.
"""

import json

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import wolfz
from wolfz.core.engine import StepError, collect, reconciliar, run_file
from wolfz.core.engine.cache import Checkpoints
from wolfz.core.engine.preview import contagens
from wolfz.core.engine.reconcilia import LIMITE_PERDA, MINIMO_ALERTA
from wolfz.core.recipe import recipe_from_dict, registered_ops


def _receita(*passos, tipo="excel"):
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "teste",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": tipo},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


def _passos(r):
    return {s.id: s for s in r.steps}


# ---------------------------------------------------------------------------
# Contrato: o efeito declarado de cada op
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nome", sorted(registered_ops()))
def test_op_que_muda_o_numero_de_linhas_nao_e_mantem(nome):
    """Uma op mal classificada esconderia a perda: o motor não conta as
    linhas depois de um passo ``mantem``."""
    cls = registered_ops()[nome]
    for i, exemplo in enumerate(cls.examples):
        receita = _receita({"op": nome, **exemplo["step"]})
        entrada = pl.DataFrame(exemplo["input"])
        saida = collect(receita, entrada.lazy())
        if saida.height != entrada.height:
            assert cls.efeito_linhas != "mantem", f"{nome}, exemplo {i}: {entrada.height} -> {saida.height}"


def test_classificacao_das_ops():
    efeito = {n: c.efeito_linhas for n, c in registered_ops().items()}
    assert {n for n, e in efeito.items() if e == "remove"} == {
        "drop_empty_rows",
        "drop_rows_where",
        "filter",
        "dedupe",
    }
    assert {n for n, e in efeito.items() if e == "estrutura"} == {"select_range", "header_rows"}
    assert {n for n, e in efeito.items() if e == "multiplica"} == {"unpivot"}


# ---------------------------------------------------------------------------
# Caso feliz
# ---------------------------------------------------------------------------


def _grade_feliz():
    return pl.DataFrame(
        {
            "A": ["Vendas de janeiro", "Nome", *[f"P{i}" for i in range(40)], None, "Total"],
            "B": [None, "Valor", *[str(i) for i in range(40)], " ", "780"],
        }
    )


def test_caso_feliz_conta_cada_passo_sem_alerta():
    receita = _receita(
        {"op": "select_range", "start": "A2"},
        {"op": "header_rows", "n": 1},
        {"op": "drop_empty_rows"},
        {"op": "trim", "cols": ["Nome"]},
        {"op": "drop_rows_where", "col": "Nome", "match": "equals", "value": "Total"},
    )
    grade = _grade_feliz()
    r = reconciliar(receita, grade)
    assert_frame_equal(r.table, collect(receita, grade.lazy()))
    assert (r.rows_read, r.rows_written) == (43, 40)
    p = _passos(r)
    assert (p["s1"].rows_in, p["s1"].rows_out, p["s1"].structure_removed) == (44, 43, 1)
    assert (p["s2"].structure_removed, p["s3"].empty_removed) == (1, 1)
    assert (p["s4"].rows_in, p["s4"].rows_out) == (41, 41)  # mantem: contado sem calcular
    assert (p["s5"].rows_in, p["s5"].rows_out, p["s5"].lost) == (41, 40, 1)
    assert not r.alert and not any(s.alert for s in r.steps)
    assert r.lost == 1


def test_to_dict_tem_as_chaves_do_report():
    r = reconciliar(_receita({"op": "select_range", "start": "A2"}, {"op": "header_rows"}), _grade_feliz())
    d = r.to_dict()
    assert set(d) == {"linhas_lidas", "linhas_gravadas", "alerta", "passos", "colunas_fora_da_area", "partes"}
    assert d["partes"] == []
    assert set(d["passos"][0]) == {
        "id",
        "op",
        "entrada",
        "saida",
        "vazias_removidas",
        "estrutura_removidas",
        "fora_da_area",
        "fator",
        "alerta",
        "motivo",
    }
    json.dumps(d)  # serializável


def test_run_report_publico_igual_ao_run(tmp_path):
    entrada = tmp_path / "v.csv"
    entrada.write_text("nome;valor\nAna;1\n;\nBia;2\n", encoding="utf-8")
    receita = _receita({"op": "drop_empty_rows"}, tipo="csv")
    r = wolfz.run_report(receita, entrada)
    assert isinstance(r, wolfz.RunReport)
    assert_frame_equal(r.table, wolfz.run(receita, entrada))
    assert (r.rows_read, r.rows_written) == (2, 2)
    assert r.steps[0].empty_removed == 1


# ---------------------------------------------------------------------------
# Dado sujo
# ---------------------------------------------------------------------------


def test_area_com_fim_fixo_acusa_linhas_e_colunas_fora_da_area():
    """C1: a receita de janeiro (A2:B11) no arquivo de março, que tem mais
    linhas e uma coluna nova em C."""
    grade = pl.DataFrame(
        {
            "A": ["Título", "Nome", *[f"P{i}" for i in range(30)], None, "Fonte: X"],
            "B": [None, "Valor", *[str(i) for i in range(30)], None, None],
            "C": [None, "Canal\x1b[2J", *["web"] * 30, None, None],
        }
    )
    receita = _receita({"op": "select_range", "start": "A2", "end": "B11"}, {"op": "header_rows"})
    r = reconciliar(receita, grade)
    s1 = r.steps[0]
    assert (s1.rows_in, s1.rows_out) == (34, 10)
    assert (s1.structure_removed, s1.empty_removed, s1.outside_area) == (1, 1, 22)
    assert s1.alert and s1.reason == "fora_da_area"
    assert r.alert and r.lost == 22
    assert r.rows_read == 33
    [col] = r.outside_columns
    assert (col.letter, col.cells, col.area, col.step) == ("C", 10, "A:B", "s1")
    assert col.header == "Canal\x1b[2J"  # o terminal escapa; aqui é o texto cru
    assert r.area_ends["s1"] == (11, 34)
    # O cabeçalho é só do terminal e da interface: o JSON leva letra e células.
    assert r.to_dict()["colunas_fora_da_area"] == [{"letra": "C", "celulas": 10}]
    assert "Canal" not in json.dumps(r.to_dict())


def test_linhas_vazias_nao_alertam_mesmo_muitas():
    grade = pl.DataFrame({"a": ["1", None, " ", None] * 100, "b": ["x", None, None, ""] * 100})
    r = reconciliar(_receita({"op": "drop_empty_rows"}), grade)
    assert r.steps[0].empty_removed == 300
    assert not r.alert and r.lost == 0


def test_tabela_pequena_nao_alerta_por_pouco():
    """3 linhas de total em 50 (6%) ficam abaixo do mínimo de 10 linhas."""
    df = pl.DataFrame({"tipo": ["dado"] * 47 + ["Total"] * 3})
    r = reconciliar(
        _receita({"op": "drop_rows_where", "col": "tipo", "match": "equals", "value": "Total"}), df
    )
    assert r.steps[0].lost == 3
    assert not r.steps[0].alert and not r.alert


def test_perda_acima_do_limite_alerta():
    df = pl.DataFrame({"v": [str(i) for i in range(1000)]})
    r = reconciliar(
        _receita({"op": "filter", "col": "v", "match": "not_in", "value": [str(i) for i in range(20)]}), df
    )
    s = r.steps[0]
    assert s.lost == 20 > LIMITE_PERDA * 1000 and s.lost >= MINIMO_ALERTA
    assert s.alert and s.reason == "perda"


def test_varios_passos_pequenos_somados_alertam_no_total():
    df = pl.DataFrame({"v": ["a"] * 90 + ["b"] * 90 + ["c"] * 90 + ["z"] * 9730})
    passos = [{"op": "drop_rows_where", "col": "v", "match": "equals", "value": v} for v in "abc"]
    r = reconciliar(_receita(*passos), df)
    assert not any(s.alert for s in r.steps)  # 90 de ~10.000 em cada: menos de 1%
    assert r.lost == 270 and r.alert


def test_segundo_unpivot_alerta_multiplicacao():
    """C4 (base 22): dois unpivot em sequência. O primeiro só mostra o
    fator; o segundo alerta."""
    df = pl.DataFrame({"uf": ["ES", "RJ"], "jan": ["1", "2"], "fev": ["3", "4"]})
    receita = _receita(
        {"op": "unpivot", "index": ["uf"], "variable_name": "mes", "value_name": "valor"},
        {"op": "unpivot", "index": ["uf"], "variable_name": "campo", "value_name": "x"},
    )
    r = reconciliar(receita, df)
    s1, s2 = r.steps
    assert (s1.rows_out, s1.factor, s1.alert) == (4, 2.0, False)
    assert (s2.rows_out, s2.factor, s2.reason) == (8, 2.0, "multiplicacao")
    assert r.alert


def test_passo_que_falha_leva_a_contagem_dos_anteriores():
    df = pl.DataFrame({"a": ["1", None, "2"]})
    receita = _receita(
        {"op": "drop_empty_rows"}, {"op": "trim", "cols": ["a"]}, {"op": "rename", "mapping": {"x": "y"}}
    )
    with pytest.raises(StepError) as exc:
        reconciliar(receita, df)
    assert exc.value.step_id == "s3"
    lidas, feitos = exc.value.contagem_parcial
    assert lidas == 2
    assert [s.id for s in feitos] == ["s1", "s2"]


def test_mensagem_de_erro_igual_a_do_run():
    """O erro aponta o mesmo passo, com o mesmo texto, nos dois caminhos."""
    df = pl.DataFrame({"a": ["1", "2"]})
    receita = _receita({"op": "drop_empty_rows"}, {"op": "trim", "cols": ["nao_existe"]})
    with pytest.raises(StepError) as a:
        collect(receita, df.lazy())
    with pytest.raises(StepError) as b:
        reconciliar(receita, df)
    assert a.value.message == b.value.message


# ---------------------------------------------------------------------------
# Contagem do preview (API)
# ---------------------------------------------------------------------------

_RECEITA_PREVIEW = (
    {"op": "select_range", "start": "A2", "end": "C30"},
    {"op": "header_rows"},
    {"op": "drop_empty_rows"},
    {"op": "trim", "cols": ["Nome"]},
    {"op": "dedupe"},
    {"op": "parse_decimal_br", "cols": ["Valor"]},
    {"op": "filter", "col": "Valor", "match": "gt", "value": 3},
    {"op": "unpivot", "index": ["Nome"]},
)


def _grade_preview():
    nomes = [f"P{i % 25}" for i in range(40)]
    return pl.DataFrame(
        {
            "A": ["Título", "Nome", *nomes, None, "nota"],
            "B": [None, "Valor", *[f"{i},5" for i in range(40)], None, None],
            "C": [None, "Canal", *["web"] * 40, None, None],
            "D": [None, None, *["x"] * 40, None, None],
        }
    )


def test_contagem_do_preview_igual_a_do_motor(tmp_path):
    grade = _grade_preview()
    receita = _receita(*_RECEITA_PREVIEW)
    raw = tmp_path / "raw.parquet"
    grade.write_parquet(raw)
    esperado = reconciliar(receita, grade)
    cache = Checkpoints(tmp_path / "checkpoints")
    for c in (None, cache, cache):  # sem cache, gravando, lendo do cache
        r = contagens(raw, "chave", receita, c)
        assert r.to_dict() == esperado.to_dict()
        assert r.outside_columns == esperado.outside_columns
        assert r.area_ends == esperado.area_ends


def test_contagem_do_preview_depois_de_editar_o_ultimo_passo(tmp_path):
    grade = _grade_preview()
    raw = tmp_path / "raw.parquet"
    grade.write_parquet(raw)
    cache = Checkpoints(tmp_path / "checkpoints")
    contagens(raw, "chave", _receita(*_RECEITA_PREVIEW), cache)
    editada = _receita(*_RECEITA_PREVIEW[:-2], {"op": "filter", "col": "Valor", "match": "gt", "value": 10})
    assert contagens(raw, "chave", editada, cache).to_dict() == reconciliar(editada, grade).to_dict()


def test_contagem_do_preview_falha_com_os_passos_anteriores(tmp_path):
    raw = tmp_path / "raw.parquet"
    _grade_preview().write_parquet(raw)
    receita = _receita(*_RECEITA_PREVIEW[:3], {"op": "trim", "cols": ["nao_existe"]})
    with pytest.raises(StepError) as exc:
        contagens(raw, "chave", receita, Checkpoints(tmp_path / "checkpoints"))
    assert exc.value.step_id == "s4"
    assert [s.id for s in exc.value.contagem_parcial[1]] == ["s1", "s2", "s3"]


def test_run_file_continua_um_plano_so(monkeypatch, tmp_path):
    """``wolfz.run`` não paga a contagem (ADR-10): não passa por
    ``reconciliar``."""
    import wolfz.core.engine as engine

    def proibido(*_a, **_k):
        raise AssertionError("wolfz.run não pode contar")

    monkeypatch.setattr(engine, "reconciliar", proibido)
    entrada = tmp_path / "v.csv"
    entrada.write_text("a\n1\n", encoding="utf-8")
    assert run_file(_receita({"op": "drop_empty_rows"}, tipo="csv"), entrada).height == 1

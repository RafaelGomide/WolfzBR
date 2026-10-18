"""Script Python exportado (F2.B): autônomo, com cabeçalho, lendo a entrada
como ``wolfz.run`` e passando no ruff."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from test_equivalencia import CASOS, _recipe, _step

import wolfz
import wolfz.ops
from wolfz.core.engine import read_input
from wolfz.core.recipe import load_recipe, recipe_from_dict, registered_ops
from wolfz.export.leitura import ler_entrada, letra_coluna
from wolfz.export.python import recipe_to_python

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


def _corpus():
    """Receitas do corpus que só usam operações já implementadas e têm o
    original no disco."""
    casos = []
    for receita in sorted(CORPUS.glob("*/receita_esperada*.wolfz.json")):
        ops = {p["op"] for p in json.loads(receita.read_text(encoding="utf-8"))["steps"]}
        originais = sorted(receita.parent.glob("original.*"))
        if ops <= registered_ops().keys() and originais:
            saida = receita.parent / receita.name.replace("receita_esperada", "saida_esperada").replace(
                ".wolfz.json", ".parquet"
            )
            casos.append(
                pytest.param(receita, originais[0], saida, id=f"{receita.parent.name}/{receita.stem}")
            )
    return casos


CORPUS_CASOS = _corpus()


def _receita(name="vendas", steps=None):
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": name,
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel", "sheet": "Vendas", "match": {"sheet_name_regex": r"Vendas \d{4}"}},
            "steps": steps or [{"id": "s1", "op": "select_range", "start": "A3", "end_detect": "auto"}],
        }
    )


# ---------------------------------------------------------------------------
# Cabeçalho (F2.B2)
# ---------------------------------------------------------------------------


def test_cabecalho_com_versao_data_e_receita():
    script = recipe_to_python(_receita(), today=date(2026, 10, 18))
    primeira = script.splitlines()[0]
    assert primeira == f'"""Receita "vendas", exportada pelo WolfzBR {wolfz.__version__} em 2026-10-18.'
    namespace: dict = {"__name__": "script_exportado"}
    exec(script, namespace)
    assert (namespace["ABA"], namespace["ABA_REGEX"], namespace["GRADE"]) == ("Vendas", r"Vendas \d{4}", True)


@pytest.mark.parametrize("nome", ['a """ b', "a\\N{x}", "linha\nquebrada", 'fim"', "\\"])
def test_nome_hostil_no_cabecalho(nome):
    """O nome da receita vai no docstring: não pode fechá-lo nem quebrar
    a linha."""
    script = recipe_to_python(_receita(name=nome), today=date(2026, 1, 1))
    modulo = compile(script, "<script>", "exec")
    assert modulo.co_consts[0].startswith("Receita ")
    assert script.splitlines()[0].endswith("em 2026-01-01.")


def test_data_de_hoje_por_padrao():
    assert f"em {date.today().isoformat()}." in recipe_to_python(_receita()).splitlines()[0]


# ---------------------------------------------------------------------------
# Autônomo (F2.B1)
# ---------------------------------------------------------------------------


def test_letra_coluna():
    assert [letra_coluna(i) for i in (0, 25, 26, 51, 52, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "AZ",
        "BA",
        "ZZ",
        "AAA",
    ]


@pytest.mark.parametrize(("receita", "original", "saida"), CORPUS_CASOS)
def test_leitura_igual_a_do_motor(receita, original, saida):
    recipe = load_recipe(receita)
    match = recipe.source.match
    grade = recipe.active_steps[0].op in {"select_range", "header_rows"}
    obtido = ler_entrada(str(original), recipe.source.sheet, match.sheet_name_regex if match else None, grade)
    assert_frame_equal(obtido, read_input(recipe, original))


@pytest.mark.parametrize(("receita", "original", "saida"), CORPUS_CASOS)
def test_script_reproduz_o_corpus(receita, original, saida):
    """O script exportado, sozinho, chega na saída esperada do corpus."""
    namespace: dict = {"__name__": "script_exportado"}
    exec(compile(recipe_to_python(load_recipe(receita)), "<script exportado>", "exec"), namespace)
    entrada = namespace["ler_entrada"](
        str(original), namespace["ABA"], namespace["ABA_REGEX"], namespace["GRADE"]
    )
    assert_frame_equal(namespace["transform"](entrada.lazy()).collect(), pl.read_parquet(saida))


def test_script_le_planilha_sem_o_wolfzbr(tmp_path):
    """Processo separado, em modo isolado (sem ``wolfz`` no caminho):
    lê o .xlsx, aplica a receita e grava Parquet."""
    pasta = CORPUS / "receita_municipal"
    script = tmp_path / "limpeza.py"
    script.write_text(recipe_to_python(load_recipe(pasta / "receita_esperada.wolfz.json")), encoding="utf-8")
    saida = tmp_path / "saida.parquet"
    subprocess.run([sys.executable, "-I", str(script), str(pasta / "original.xlsx"), str(saida)], check=True)
    assert_frame_equal(pl.read_parquet(saida), pl.read_parquet(pasta / "saida_esperada.parquet"))


def test_script_sem_argumentos_explica_o_uso(tmp_path):
    script = tmp_path / "limpeza.py"
    script.write_text(recipe_to_python(_receita()), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True)
    assert r.returncode != 0
    assert "uso: python" in r.stderr


# ---------------------------------------------------------------------------
# Ruff (F2.B3)
# ---------------------------------------------------------------------------


def test_script_passa_no_ruff(tmp_path):
    """Todo script gerado (exemplos do catálogo e receitas do corpus) passa
    no ``ruff check`` e no ``ruff format --check`` com a configuração
    padrão, que é a que o usuário tem sem configurar nada."""
    from ruff.__main__ import find_ruff_bin

    scripts = {case.id: recipe_to_python(_recipe(_step(*case.values))) for case in CASOS}
    scripts.update({case.id: recipe_to_python(load_recipe(case.values[0])) for case in CORPUS_CASOS})
    for i, script in enumerate(scripts.values()):
        (tmp_path / f"script_{i}.py").write_text(script, encoding="utf-8")
    ruff = find_ruff_bin()
    regras = ["--select", "E4,E7,E9,F,I,UP,B,SIM"]
    check = subprocess.run(
        [ruff, "check", "--isolated", *regras, "."], cwd=tmp_path, capture_output=True, text=True
    )
    assert check.returncode == 0, check.stdout
    fmt = subprocess.run(
        [ruff, "format", "--isolated", "--check", "."], cwd=tmp_path, capture_output=True, text=True
    )
    assert fmt.returncode == 0, fmt.stdout

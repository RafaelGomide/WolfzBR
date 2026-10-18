"""Teste de equivalência (F0.F4): cada operação do catálogo, executada no
Polars e no script Python exportado, dá exatamente o mesmo resultado.

Os casos vêm dos ``examples`` de cada operação, então toda operação nova
entra aqui sozinha. Operação sem exemplo reprova.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from m_parser import parse_m
from m_sintaxe import check_m
from polars.testing import assert_frame_equal

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.recipe import Recipe, Source, recipe_from_dict, registered_ops
from wolfz.export.m import recipe_to_m
from wolfz.export.python import recipe_to_python

CATALOGO = {
    name: cls for name, cls in sorted(registered_ops().items()) if cls.__module__.startswith("wolfz.")
}
CASOS = [
    pytest.param(cls, example, id=f"{name}-{i}")
    for name, cls in CATALOGO.items()
    for i, example in enumerate(cls.examples)
]


def _recipe(*steps) -> Recipe:
    return Recipe(
        wolfz_version="0.1",
        name="equivalência",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source=Source(type="csv"),
        steps=list(steps),
    )


def _step(cls, example, step_id="s1"):
    return cls.model_validate(
        {"id": step_id, "op": cls.model_fields["op"].annotation.__args__[0], **example["step"]}
    )


def _run_script(recipe: Recipe, df: pl.DataFrame) -> pl.DataFrame:
    namespace: dict = {}
    exec(compile(recipe_to_python(recipe), "<script exportado>", "exec"), namespace)
    return namespace["transform"](df.lazy()).collect()


def test_catalogo_nao_esta_vazio():
    assert {"rename", "drop_rows_where", "parse_brl"} <= set(CATALOGO)


@pytest.mark.parametrize("name", list(CATALOGO))
def test_toda_operacao_tem_exemplo(name):
    assert CATALOGO[name].examples, f"{name} precisa de pelo menos um exemplo em `examples`"


@pytest.mark.parametrize(("cls", "example"), CASOS)
def test_polars_igual_script_python(cls, example):
    step = _step(cls, example)
    df = pl.DataFrame(example["input"])
    polars_out = step.to_polars(df.lazy()).collect()
    assert_frame_equal(polars_out, _run_script(_recipe(step), df))
    if "expected" in example:
        assert polars_out.to_dict(as_series=False) == example["expected"]


@pytest.mark.parametrize(("cls", "example"), CASOS)
def test_m_estruturalmente_valido(cls, example):
    m = recipe_to_m(_recipe(_step(cls, example)))
    check_m(m)
    assert f"// s1 {cls.model_fields['op'].annotation.__args__[0]}\n" in m


RECEITA_COMPLETA = [
    {"id": "s1", "op": "rename", "mapping": {"Vlr Venda": "valor", "Região": "regiao"}},
    {
        "id": "s2",
        "op": "drop_rows_where",
        "col": "regiao",
        "match": "starts_with",
        "value": "total",
        "ignore_case": True,
    },
    {"id": "s3", "op": "parse_brl", "cols": ["valor"]},
]
ENTRADA = pl.DataFrame(
    {
        "Região": ["Sul", "Sudeste", "TOTAL GERAL", None],
        "Vlr Venda": ["R$ 1.234,56", "(10,00)", "R$ 1.224,56", "#N/D"],
    }
)


def _receita_completa() -> Recipe:
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "completa",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": RECEITA_COMPLETA,
        }
    )


def test_receita_com_varios_passos():
    recipe = _receita_completa()
    lf = ENTRADA.lazy()
    for step in recipe.steps:
        lf = step.to_polars(lf)
    polars_out = lf.collect()
    assert polars_out.to_dict(as_series=False) == {
        "regiao": ["Sul", "Sudeste", None],
        "valor": [1234.56, -10.0, None],
    }
    assert_frame_equal(polars_out, _run_script(recipe, ENTRADA))
    check_m(recipe_to_m(recipe))


def test_script_roda_sem_o_wolfzbr(tmp_path):
    """O script exportado é autônomo: roda num processo separado, sem
    ``wolfz`` no caminho, e grava o mesmo resultado."""
    script = recipe_to_python(_receita_completa())
    assert "wolfz" not in "\n".join(line for line in script.splitlines() if "import" in line)
    path = tmp_path / "limpeza.py"
    path.write_text(script, encoding="utf-8")
    entrada, saida = tmp_path / "entrada.csv", tmp_path / "saida.csv"
    ENTRADA.write_csv(entrada)
    # -I: modo isolado, ignora PYTHONPATH e o diretório atual
    subprocess.run([sys.executable, "-I", str(path), str(entrada), str(saida)], check=True, cwd=tmp_path)
    resultado = pl.read_csv(saida, schema={"regiao": pl.String, "valor": pl.Float64})
    assert resultado.to_dict(as_series=False) == {
        "regiao": ["Sul", "Sudeste", None],
        "valor": [1234.56, -10.0, None],
    }


def test_script_e_deterministico():
    """Mesmo script em processos com hash aleatório diferente: conjuntos
    copiados para o script não podem depender da ordem de iteração."""
    code = (
        f"import sys; sys.path[:0] = [r'{Path(__file__).parent}']; "
        "from test_equivalencia import _receita_completa; "
        "from wolfz.export.python import recipe_to_python; "
        "sys.stdout.buffer.write(recipe_to_python(_receita_completa()).encode())"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2", "3")
    }
    assert len(outputs) == 1


def test_m_aceito_pelo_parser_da_microsoft():
    """Todo M gerado pelos exemplos do catálogo, mais a receita completa,
    passa no parser oficial (uma chamada ao Node para todos)."""
    documents = {case.id: recipe_to_m(_recipe(_step(*case.values))) for case in CASOS}
    documents["receita completa"] = recipe_to_m(_receita_completa())
    results = parse_m(list(documents.values()))
    falhas = {name: r["error"] for name, r in zip(documents, results, strict=True) if not r["ok"]}
    assert not falhas

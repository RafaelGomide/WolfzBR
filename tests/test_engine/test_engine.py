import re

import polars as pl
import pytest

import wolfz
from wolfz.core.engine import StepError, collect, run
from wolfz.core.engine.errors import missing_column
from wolfz.core.recipe import recipe_from_dict, save_recipe


def _recipe(*steps):
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "motor",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **s} for i, s in enumerate(steps, start=1)],
        }
    )


RENOMEAR = {"op": "rename", "mapping": {"Vlr": "valor"}}
SEM_TOTAL = {"op": "drop_rows_where", "col": "regiao", "match": "starts_with", "value": "Total"}
BRL = {"op": "parse_brl", "cols": ["valor"]}
ENTRADA = pl.DataFrame({"regiao": ["Sul", "Total"], "Vlr": ["R$ 1,50", "R$ 9,00"]})


def test_run_compoe_os_passos_em_ordem():
    lf = run(_recipe(RENOMEAR, SEM_TOTAL, BRL), ENTRADA.lazy())
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect().to_dict(as_series=False) == {"regiao": ["Sul"], "valor": [1.5]}


def test_receita_sem_passos_devolve_a_entrada():
    assert collect(_recipe(), ENTRADA.lazy()).equals(ENTRADA)


def test_coluna_inexistente_aponta_o_passo_sem_ler_os_dados():
    with pytest.raises(StepError) as exc:
        run(_recipe(RENOMEAR, {"op": "parse_brl", "cols": ["valor_bruto"]}), ENTRADA.lazy())
    err = exc.value
    assert (err.step_id, err.op, err.title) == ("s2", "parse_brl", "Coluna não encontrada")
    assert err.message == (
        "O passo s2 (parse_brl) referencia a coluna 'valor_bruto', que não existe após o passo s1."
    )
    assert err.available_columns == ["regiao", "valor"]


def test_coluna_inexistente_no_primeiro_passo():
    with pytest.raises(StepError, match="'Valor', que não existe na tabela de entrada"):
        run(_recipe({"op": "rename", "mapping": {"Valor": "v"}}), ENTRADA.lazy())


def test_problem_details():
    with pytest.raises(StepError) as exc:
        run(_recipe({"op": "parse_brl", "cols": ["x"]}), ENTRADA.lazy())
    assert exc.value.to_problem(instance="/api/projects/abc/preview") == {
        "type": "about:blank",
        "title": "Coluna não encontrada",
        "status": 422,
        "detail": "O passo s1 (parse_brl) referencia a coluna 'x', que não existe na tabela de entrada.",
        "instance": "/api/projects/abc/preview",
        "step_id": "s1",
        "op": "parse_brl",
        "available_columns": ["regiao", "Vlr"],
    }
    assert "instance" not in exc.value.to_problem()


def test_erro_com_os_dados_e_localizado_no_passo(monkeypatch):
    """Erro que só aparece no collect (dentro do parser) também aponta o passo."""
    import wolfz.ops.br as br

    def quebra(value, **kwargs):
        if value == "R$ 9,00":
            raise ZeroDivisionError("division by zero")
        return 1.0

    monkeypatch.setattr(br, "parse_brl", quebra)
    with pytest.raises(StepError) as exc:
        collect(_recipe(RENOMEAR, BRL), ENTRADA.lazy())
    assert exc.value.step_id == "s2"
    assert exc.value.message == "O passo s2 (parse_brl) falhou: division by zero"
    assert exc.value.available_columns == ["regiao", "valor"]
    assert isinstance(exc.value.__cause__, ZeroDivisionError)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('unable to find column "valor"; valid columns: ["a"]', "valor"),
        ('"x" not found\n\nResolved plan', "x"),
        ("outra coisa", None),
        ("", None),
    ],
)
def test_missing_column(text, expected):
    assert missing_column(Exception(text)) == expected


# ---------------------------------------------------------------------------
# wolfz.run (API pública)
# ---------------------------------------------------------------------------


@pytest.fixture
def arquivos(tmp_path):
    receita = tmp_path / "vendas.wolfz.json"
    save_recipe(_recipe(RENOMEAR, SEM_TOTAL, BRL), receita)
    dados = tmp_path / "vendas_jan.csv"
    dados.write_bytes("regiao;Vlr\nSul;R$ 1.234,56\nTotal;R$ 1.234,56\nNorte;(10,00)\n".encode("cp1252"))
    return receita, dados


def test_wolfz_run_com_caminhos(arquivos):
    receita, dados = arquivos
    df = wolfz.run(receita, dados)
    assert df.to_dict(as_series=False) == {"regiao": ["Sul", "Norte"], "valor": [1234.56, -10.0]}


def test_wolfz_run_com_receita_carregada(arquivos):
    receita, dados = arquivos
    assert wolfz.run(wolfz.load_recipe(receita), str(dados)).height == 2


def test_wolfz_run_so_csv_por_enquanto(arquivos, tmp_path):
    receita, _ = arquivos
    with pytest.raises(ValueError, match=re.escape("só arquivos CSV; .xlsx entra na versão 0.2")):
        wolfz.run(receita, tmp_path / "vendas.xlsx")


def test_wolfz_run_erro_de_passo(arquivos, tmp_path):
    receita, _ = arquivos
    outro = tmp_path / "outro.csv"
    outro.write_text("regiao;Valor\nSul;1\n", encoding="utf-8")
    with pytest.raises(wolfz.StepError, match="referencia a coluna 'Vlr'"):
        wolfz.run(receita, outro)

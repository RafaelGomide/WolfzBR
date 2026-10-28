"""``wolfz run`` com a reconciliação de linhas (F1 e S2 da 1.1).

- o ``stdout`` continua igual e o resumo de lidas e gravadas vai para o
  ``stderr`` (D12);
- ``--max-drop`` para sem gravar (código 1);
- aviso de coluna preenchida fora da área, com o cabeçalho escapado (R9);
- ``--report`` com um arquivo só, com as contagens, e que nunca destrói
  nada (R2).
"""

import json

import polars as pl
import pytest
from typer.testing import CliRunner

from wolfz.cli import _max_drop, app
from wolfz.core.recipe import recipe_from_dict, save_recipe

runner = CliRunner()


def _receita(path, *passos, tipo="csv"):
    save_recipe(
        recipe_from_dict(
            {
                "wolfz_version": "1.0",
                "name": "vendas",
                "created_at": "2026-01-01T00:00:00Z",
                "source": {"type": tipo},
                "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
            }
        ),
        path,
    )
    return path


def _run(*args):
    return runner.invoke(app, ["run", *map(str, args)])


@pytest.fixture
def janeiro(tmp_path):
    """Receita feita em janeiro, com o fim da área fixo (A2:B32: cabeçalho e
    30 linhas), como a 1.0.0 gravava (C1)."""
    return _receita(
        tmp_path / "janeiro.wolfz.json",
        {"op": "select_range", "start": "A2", "end": "B32"},
        {"op": "header_rows"},
        {"op": "drop_empty_rows"},
    )


def _marco(tmp_path, linhas=40, canal="Canal", nome="marco.csv"):
    """O arquivo de março: mais linhas que janeiro e uma coluna nova em C."""
    corpo = ["Vendas de março;;", f"Nome;Valor;{canal}"]
    corpo += [f"P{i};{i};web" for i in range(linhas)]
    path = tmp_path / nome
    path.write_text("\n".join(corpo) + "\n", encoding="utf-8")
    return path


def test_sem_perda_stdout_igual_e_resumo_no_stderr(tmp_path):
    receita = _receita(tmp_path / "r.wolfz.json", {"op": "drop_empty_rows"})
    entrada = tmp_path / "v.csv"
    entrada.write_text("a;b\n1;2\n;\n3;4\n", encoding="utf-8")
    saida = tmp_path / "s.csv"
    result = _run(receita, entrada, "-o", saida)
    assert result.exit_code == 0, result.output
    assert result.stdout == f"2 linhas, 2 colunas -> {saida}\n"
    assert result.stderr == "Lidas 2 · gravadas 2 · 1 linha vazia removida\n"


def test_perda_fora_da_area_avisa_e_grava(tmp_path, janeiro):
    entrada = _marco(tmp_path)
    saida = tmp_path / "s.csv"
    result = _run(janeiro, entrada, "-o", saida)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == f"30 linhas, 2 colunas -> {saida}"
    linhas = result.stderr.splitlines()
    # As 31 células da coluna C são as das linhas da área, cabeçalho incluído.
    assert linhas[0] == "Atenção: lidas 42 · gravadas 30 · 10 fora da área recortada (23,8%)"
    assert linhas[1] == (
        "  s1 Recortar a área: -10 linhas (23,8%). A área termina na linha 32; o arquivo vai até a linha 42."
    )
    assert linhas[2] == (
        "Atenção: a coluna C (Canal) tem 31 células preenchidas fora da área A:B do passo s1. "
        "Elas não entram na saída."
    )
    assert pl.read_csv(saida).height == 30


def test_cabecalho_fora_da_area_e_literal_e_curto(tmp_path, janeiro):
    """R9: o cabeçalho vem da planilha; sai sem caractere de controle e
    cortado em 60 caracteres."""
    entrada = _marco(tmp_path, linhas=5, canal="[red]x[/red]\x1b[2J" + "y" * 80)
    result = _run(janeiro, entrada, "-o", tmp_path / "s.csv")
    assert result.exit_code == 0, result.output
    aviso = next(linha for linha in result.stderr.splitlines() if "a coluna C" in linha)
    assert "\x1b" not in aviso
    cabecalho = aviso.split("a coluna C (")[1].split(") tem")[0]
    assert cabecalho.startswith("[red]x[/red][2J") and len(cabecalho) == 60 and cabecalho.endswith("…")


def test_coluna_sem_cabecalho(tmp_path, janeiro):
    entrada = _marco(tmp_path, linhas=5, canal="")
    result = _run(janeiro, entrada, "-o", tmp_path / "s.csv")
    assert "a coluna C (sem cabeçalho) tem 5 células preenchidas" in result.stderr


@pytest.mark.parametrize(
    ("texto", "fracao"), [("1%", 0.01), ("1", 0.01), ("0.5%", 0.005), ("0,5%", 0.005), ("0", 0.0)]
)
def test_max_drop_aceita(texto, fracao):
    assert _max_drop(texto) == pytest.approx(fracao)


@pytest.mark.parametrize("texto", ["abc", "-1", "101%"])
def test_max_drop_recusa(tmp_path, janeiro, texto):
    result = _run(janeiro, _marco(tmp_path), "-o", tmp_path / "s.csv", "--max-drop", texto)
    assert result.exit_code == 2
    assert not (tmp_path / "s.csv").exists()


def test_max_drop_para_sem_gravar(tmp_path, janeiro):
    saida = tmp_path / "s.csv"
    result = _run(janeiro, _marco(tmp_path), "-o", saida, "--max-drop", "1%")
    assert result.exit_code == 1
    linhas = result.stderr.splitlines()
    assert linhas[0] == (
        "Parado: o passo s1 Recortar a área tirou 23,8% das linhas, acima do limite de 1% (--max-drop)."
    )
    assert linhas[-1] == "Nada foi gravado."
    assert not saida.exists()


def test_max_drop_nao_conta_vazias_nem_estrutura(tmp_path):
    receita = _receita(
        tmp_path / "r.wolfz.json",
        {"op": "select_range", "start": "A2"},
        {"op": "header_rows"},
        {"op": "drop_empty_rows"},
    )
    entrada = tmp_path / "v.csv"
    entrada.write_text("Título;\nNome;Valor\n" + "a;1\n;\n" * 50, encoding="utf-8")
    result = _run(receita, entrada, "-o", tmp_path / "s.csv", "--max-drop", "0")
    assert result.exit_code == 0, result.output


def test_max_drop_em_lote_vale_por_arquivo(tmp_path, janeiro):
    pasta = tmp_path / "entrada"
    pasta.mkdir()
    _marco(pasta, linhas=40)
    _marco(pasta, linhas=20, nome="abril.csv")
    saida = tmp_path / "saida"
    result = runner.invoke(
        app,
        ["run", str(janeiro), str(pasta / "*.csv"), "-o", str(saida), "--max-drop", "1%"],
        terminal_width=200,
    )
    assert result.exit_code == 1
    assert [p.name for p in saida.iterdir()] == ["abril.csv"]
    assert "Parado:" in result.stdout


def test_report_com_um_arquivo(tmp_path, janeiro, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _marco(tmp_path)
    result = _run(janeiro, "marco.csv", "-o", "s.csv", "--report", "rel.json")
    assert result.exit_code == 0, result.output
    dados = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    [item] = dados["arquivos"]
    assert item["arquivo"] == "marco.csv"  # como foi digitado, nunca absoluto
    assert {k: item[k] for k in ("ok", "saida", "linhas", "colunas", "linhas_lidas", "linhas_gravadas")} == {
        "ok": True,
        "saida": "s.csv",
        "linhas": 30,
        "colunas": 2,
        "linhas_lidas": 42,
        "linhas_gravadas": 30,
    }
    assert item["alerta"] is True
    assert item["colunas_fora_da_area"] == [{"letra": "C", "celulas": 31}]
    assert item["passos"][0]["motivo"] == "fora_da_area"
    assert "Canal" not in json.dumps(dados)  # cabeçalho só no terminal (D3)


def test_report_de_um_arquivo_que_falha(tmp_path, janeiro):
    relatorio = tmp_path / "rel.json"
    result = _run(
        janeiro, _marco(tmp_path), "-o", tmp_path / "s.csv", "--max-drop", "1%", "--report", relatorio
    )
    assert result.exit_code == 1
    [item] = json.loads(relatorio.read_text(encoding="utf-8"))["arquivos"]
    assert not item["ok"] and item["codigo"] == 1
    assert item["erro"].startswith("Parado: o passo s1")
    assert item["linhas_lidas"] == 42 and item["linhas_gravadas"] == 30


def test_report_existente_sem_overwrite_nao_toca_em_nada(tmp_path, janeiro):
    relatorio = tmp_path / "rel.json"
    relatorio.write_text("antigo", encoding="utf-8")
    saida = tmp_path / "s.csv"
    result = _run(janeiro, _marco(tmp_path), "-o", saida, "--report", relatorio)
    assert result.exit_code == 2
    assert "O relatório já existe" in result.stderr
    assert relatorio.read_text(encoding="utf-8") == "antigo"
    assert not saida.exists()


@pytest.mark.parametrize("alvo", ["entrada", "receita"])
def test_report_nunca_cai_na_entrada_nem_na_receita(tmp_path, janeiro, alvo):
    entrada = _marco(tmp_path)
    caminho = entrada if alvo == "entrada" else janeiro
    antes = caminho.read_bytes()
    result = _run(janeiro, entrada, "-o", tmp_path / "s.csv", "--report", caminho, "--overwrite")
    assert result.exit_code == 2
    assert caminho.read_bytes() == antes
    assert not (tmp_path / "s.csv").exists()


def test_erro_do_polars_so_com_show_values():
    """A mensagem de um erro do Polars pode citar o valor da célula: sem
    --show-values, o terminal só diz o passo, e o relatório nunca leva o
    texto do erro (R1, D9)."""
    from wolfz.cli import _falha_de_passo
    from wolfz.core.engine import StepError

    exc = StepError("s3", "cast", 'O passo s3 (cast) falhou: conversion failed: ["QXZ7"]', ["v"])
    exc.detalhe_seguro = False
    sem = _falha_de_passo(exc, mostrar_valores=False)
    assert "QXZ" not in " ".join(sem.lines)
    assert "--show-values" in " ".join(sem.lines)
    assert "QXZ" in " ".join(_falha_de_passo(exc, mostrar_valores=True).lines)
    for falha in (sem, _falha_de_passo(exc, mostrar_valores=True)):
        assert falha.relatorio["erro"] == "Erro ao executar o passo: o passo s3 (cast) falhou."

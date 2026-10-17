"""``wolfz ui`` (F1.J1) e ``wolfz run`` com planilha e aba renomeada (F1.J2).

O servidor não sobe de verdade nos testes de ``ui``: ``uvicorn.Server.run``
é trocado por uma função que só marca o servidor como pronto."""

import json
import socket
import time
from pathlib import Path

import polars as pl
import pytest
import uvicorn
from openpyxl import load_workbook
from typer.testing import CliRunner

from wolfz.api import security, server
from wolfz.cli import app

runner = CliRunner()
CORPUS = Path(__file__).resolve().parent / "corpus"


@pytest.fixture
def servidores(monkeypatch, tmp_path):
    """Servidores que o comando "rodou", e URLs abertas no navegador."""
    monkeypatch.setenv("WOLFZ_HOME", str(tmp_path / "home"))
    rodados, abertas = [], []

    def run(self):
        self.started = True
        rodados.append(self)

    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setattr(server.webbrowser, "open", abertas.append)
    return rodados, abertas


def _esperar(lista, segundos=3.0):
    fim = time.monotonic() + segundos
    while not lista and time.monotonic() < fim:
        time.sleep(0.02)
    return lista


def test_ui_abre_o_navegador_com_o_token(servidores):
    rodados, abertas = servidores
    result = runner.invoke(app, ["ui"])
    assert result.exit_code == 0, result.output
    (srv,) = rodados
    token = srv.config.app.state.settings.token
    url = f"http://127.0.0.1:{srv.config.port}/#token={token}"
    assert srv.config.host == "127.0.0.1" and srv.config.port > 0
    assert f"WolfzBR rodando em {url}" in result.output
    assert _esperar(abertas) == [url]


def test_ui_sem_navegador(servidores):
    rodados, abertas = servidores
    result = runner.invoke(app, ["ui", "--no-browser", "--port", "8791"])
    assert result.exit_code == 0, result.output
    assert rodados[0].config.port == 8791
    time.sleep(0.2)
    assert abertas == []


def test_ui_tokens_diferentes_a_cada_execucao(servidores):
    rodados, _ = servidores
    runner.invoke(app, ["ui", "--no-browser"])
    runner.invoke(app, ["ui", "--no-browser"])
    a, b = (s.config.app.state.settings.token for s in rodados)
    assert a != b


def test_ui_porta_ocupada(servidores):
    rodados, _ = servidores
    with socket.socket() as ocupada:
        ocupada.bind(("127.0.0.1", 0))
        ocupada.listen()
        porta = ocupada.getsockname()[1]
        result = runner.invoke(app, ["ui", "--port", str(porta)])
    assert result.exit_code == 2
    assert f"A porta {porta} já está em uso" in result.output
    assert rodados == []


def test_ui_avisa_sem_interface_compilada(servidores, monkeypatch, tmp_path):
    monkeypatch.setattr(security, "STATIC_DIR", tmp_path / "vazio")
    result = runner.invoke(app, ["ui", "--no-browser"])
    assert result.exit_code == 0
    assert "a interface não foi compilada" in result.output


def test_navegador_nao_abre_se_o_servidor_nao_subir():
    class Parado:
        started = False
        should_exit = False

    abertas = []
    server.abrir_quando_pronto(Parado(), "http://x", abrir=abertas.append, espera=0.1).join()
    assert abertas == []


def test_porta_disponivel():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert server.porta_disponivel(s.getsockname()[1]) is False
    assert server.porta_disponivel(server.porta_livre()) is True


# ---------------------------------------------------------------------------
# wolfz run com planilha (F1.J2)
# ---------------------------------------------------------------------------


def _receita(tmp_path, **source):
    pasta = CORPUS / "receita_municipal"
    dados = json.loads((pasta / "receita_esperada.wolfz.json").read_text(encoding="utf-8"))
    dados["source"].update(source)
    destino = tmp_path / "receita.wolfz.json"
    destino.write_text(json.dumps(dados), encoding="utf-8")
    return destino


def _planilha_com_aba(tmp_path, nome_aba):
    wb = load_workbook(CORPUS / "receita_municipal" / "original.xlsx")
    wb.active.title = nome_aba
    destino = tmp_path / "receita_2026.xlsx"
    wb.save(destino)
    return destino


def test_run_planilha_do_corpus(tmp_path):
    pasta = CORPUS / "receita_municipal"
    saida = tmp_path / "saida.parquet"
    args = ["run", str(pasta / "receita_esperada.wolfz.json"), str(pasta / "original.xlsx")]
    result = runner.invoke(app, [*args, "-o", str(saida), "-f", "parquet"])
    assert result.exit_code == 0, result.output
    assert pl.read_parquet(saida).equals(pl.read_parquet(pasta / "saida_esperada.parquet"))


def test_run_acha_a_aba_renomeada_pela_regex(tmp_path):
    receita = _receita(tmp_path, match={"sheet_name_regex": r"Receita \d{4}"})
    planilha = _planilha_com_aba(tmp_path, "Receita 2026")
    result = runner.invoke(app, ["run", str(receita), str(planilha), "-o", str(tmp_path / "s.csv")])
    assert result.exit_code == 0, result.output
    assert "12 linhas" in result.output


def test_run_aba_que_nao_casa_sai_com_3(tmp_path):
    receita = _receita(tmp_path, match={"sheet_name_regex": r"Receita \d{4}"})
    planilha = _planilha_com_aba(tmp_path, "Despesa 2026")
    result = runner.invoke(app, ["run", str(receita), str(planilha), "-o", str(tmp_path / "s.csv")])
    assert result.exit_code == 3
    assert "Despesa 2026" in result.output and not (tmp_path / "s.csv").exists()

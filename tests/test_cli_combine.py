"""``wolfz run`` com abas e arquivos juntos (F3 da 1.1, ADR-12, R3, R4, R7, R9).

- ``--sheet`` escolhe a aba;
- ``--combine`` junta os arquivos num só, tudo ou nada;
- a saída nunca vira entrada, e arquivo de bloqueio do Excel é ignorado;
- o lote grande demais é recusado antes de ler.
"""

import json
from pathlib import Path

import polars as pl
import pytest
from openpyxl import Workbook
from typer.testing import CliRunner

from wolfz.cli import app
from wolfz.core.recipe import recipe_from_dict, save_recipe

runner = CliRunner()


def planilha(path, abas: dict[str, list[list]], ocultas: dict[str, str] | None = None):
    wb = Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(linha)
    for nome, estado in (ocultas or {}).items():
        wb[nome].sheet_state = estado
    wb.save(path)
    return path


def _mes(nome, n, colunas=("Vendedor", "Valor")):
    return [
        [f"Vendas {nome}"],
        list(colunas),
        *[[f"V{i}", str(i * 10), "x"][: len(colunas)] for i in range(n)],
    ]


def _receita(path, source=None, *passos):
    save_recipe(
        recipe_from_dict(
            {
                "wolfz_version": "1.1",
                "name": "vendas",
                "created_at": "2026-01-01T00:00:00Z",
                "source": source or {"type": "csv"},
                "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
            }
        ),
        path,
    )
    return path


def _run(*args):
    return runner.invoke(app, ["run", *map(str, args)])


def _csv(path, linhas, cabecalho="Vendedor;Valor"):
    path.write_text(cabecalho + "\n" + "".join(f"{v};{n}\n" for v, n in linhas), encoding="utf-8")
    return path


@pytest.fixture
def meses(tmp_path):
    pasta = tmp_path / "entrada"
    pasta.mkdir()
    for mes, n in [("2026-01", 3), ("2026-02", 2), ("2026-03", 4)]:
        _csv(pasta / f"{mes}.csv", [(f"V{i}", str(i)) for i in range(n)])
    return pasta


@pytest.fixture
def simples(tmp_path):
    return _receita(tmp_path / "r.wolfz.json", None, {"op": "parse_decimal_br", "cols": ["Valor"]})


# ---------------------------------------------------------------------------
# --sheet (F3.1)
# ---------------------------------------------------------------------------


@pytest.fixture
def trimestre(tmp_path):
    return planilha(
        tmp_path / "vendas_1tri.xlsx", {"JAN": _mes("JAN", 3), "FEV": _mes("FEV", 2), "Resumo": [["x"]]}
    )


@pytest.fixture
def receita_jan(tmp_path):
    return _receita(
        tmp_path / "jan.wolfz.json",
        {"type": "excel", "sheet": "JAN"},
        {"op": "select_range", "start": "A2"},
        {"op": "header_rows"},
    )


def test_sheet_escolhe_a_aba(tmp_path, trimestre, receita_jan):
    result = _run(receita_jan, trimestre, "-o", tmp_path / "s.csv", "--sheet", "FEV")
    assert result.exit_code == 0, result.output
    assert pl.read_csv(tmp_path / "s.csv").height == 2


def test_sheet_que_nao_existe(tmp_path, trimestre, receita_jan):
    result = _run(receita_jan, trimestre, "-o", tmp_path / "s.csv", "--sheet", "FEVEREIRO")
    assert result.exit_code == 3
    assert result.stderr.splitlines() == [
        "A aba FEVEREIRO não existe em vendas_1tri.xlsx.",
        "Abas do arquivo: JAN, FEV, Resumo.",
        "Nada foi gravado.",
    ]
    assert not (tmp_path / "s.csv").exists()


def test_sheet_em_csv_e_uso_errado(tmp_path, meses, simples):
    result = _run(simples, meses / "2026-01.csv", "-o", tmp_path / "s.csv", "--sheet", "X")
    assert result.exit_code == 2 and "não tem abas" in result.stderr


def test_abas_juntas_no_run_avisam_as_ocultas(tmp_path):
    arq = planilha(
        tmp_path / "a.xlsx",
        {
            "JAN": _mes("JAN", 1),
            "FEV": _mes("FEV", 1, ("Vendedor", "Valor", "Canal")),
            "Base": _mes("Base", 1),
        },
        {"Base": "hidden"},
    )
    receita = _receita(
        tmp_path / "r.wolfz.json",
        {"type": "excel", "sheet": "JAN", "combine_sheets": {}},
        {"op": "select_range", "start": "A2"},
        {"op": "header_rows"},
    )
    result = _run(receita, arq, "-o", tmp_path / "s.csv")
    assert result.exit_code == 0, result.output
    erros = result.stderr
    assert "Atenção: 1 aba oculta não foi incluída: Base." in erros
    assert "Atenção: as abas não têm as mesmas colunas." in erros
    assert "  JAN: falta Canal." in erros and "  FEV: tem a mais Canal." in erros


# ---------------------------------------------------------------------------
# --combine (F3.5, F3.6)
# ---------------------------------------------------------------------------


def test_combine_junta_com_o_nome_do_arquivo(tmp_path, meses, simples, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run(simples, "entrada/*.csv", "--combine", "-o", "saida/vendas.csv", "--report", "rel.json")
    assert result.exit_code == 0, result.output
    destino = Path("saida/vendas.csv")
    assert result.stdout.splitlines()[0] == f"9 linhas, 3 colunas -> {destino} (3 arquivos juntos)"
    df = pl.read_csv(tmp_path / "saida" / "vendas.csv")
    assert df.columns == ["arquivo", "Vendedor", "Valor"]
    assert df["arquivo"].unique(maintain_order=True).to_list() == [
        "2026-01.csv",
        "2026-02.csv",
        "2026-03.csv",
    ]
    assert "  2026-02.csv  lidas 2 · gravadas 2" in result.stderr
    rel = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    assert [i["ok"] for i in rel["arquivos"]] == [True] * 3
    assert rel["combinado"]["linhas"] == 9
    assert [p["origem"] for p in rel["combinado"]["partes"]] == ["2026-01.csv", "2026-02.csv", "2026-03.csv"]
    assert str(tmp_path) not in json.dumps(rel)


@pytest.mark.parametrize(
    ("opcao", "colunas"),
    [(["--origin-col", "Mes"], ["Mes", "Vendedor", "Valor"]), (["--no-origin-col"], ["Vendedor", "Valor"])],
)
def test_combine_nome_da_origem(tmp_path, meses, simples, opcao, colunas):
    result = _run(simples, meses / "*.csv", "--combine", "-o", tmp_path / "v.csv", *opcao)
    assert result.exit_code == 0, result.output
    assert pl.read_csv(tmp_path / "v.csv").columns == colunas


def test_combine_com_combine_sheets_gera_as_duas_origens(tmp_path):
    pasta = tmp_path / "e"
    pasta.mkdir()
    for nome in ("a.xlsx", "b.xlsx"):
        planilha(pasta / nome, {"JAN": _mes("JAN", 1), "FEV": _mes("FEV", 2)})
    receita = _receita(
        tmp_path / "r.wolfz.json",
        {"type": "excel", "sheet": "JAN", "combine_sheets": {}},
        {"op": "select_range", "start": "A2"},
        {"op": "header_rows"},
    )
    result = _run(receita, pasta / "*.xlsx", "--combine", "-o", tmp_path / "v.csv")
    assert result.exit_code == 0, result.output
    df = pl.read_csv(tmp_path / "v.csv")
    assert df.columns[:2] == ["arquivo", "aba"] and df.height == 6


def test_combine_saida_precisa_ser_arquivo(tmp_path, meses, simples):
    result = _run(simples, meses / "*.csv", "--combine", "-o", tmp_path)
    assert result.exit_code == 2 and "precisa ser um arquivo" in result.stderr


def test_origin_col_sem_combine_e_uso_errado(tmp_path, meses, simples):
    result = _run(simples, meses / "2026-01.csv", "-o", tmp_path / "v.csv", "--origin-col", "x")
    assert result.exit_code == 2


def test_combine_tudo_ou_nada(tmp_path, meses, tmp_path_factory):
    receita = _receita(
        tmp_path / "r.wolfz.json",
        None,
        {"op": "parse_decimal_br", "cols": ["Valor"]},
        {"op": "assert", "check": "unique", "cols": ["Vendedor"]},
    )
    _csv(meses / "2026-02.csv", [("CPF529", "1"), ("CPF529", "2")])  # fevereiro reprova
    saida = tmp_path / "v.csv"
    result = _run(receita, meses / "*.csv", "--combine", "-o", saida, "--report", tmp_path / "rel.json")
    assert result.exit_code == 1
    assert not saida.exists()
    linhas = result.stderr.splitlines()
    assert linhas[0] == "Lote parado: 1 arquivo não passou."
    assert linhas[1].startswith("  2026-02.csv: Verificação reprovada")
    assert "Os outros 2 arquivos passaram, mas a saída junta todos." in linhas
    assert linhas[-1] == "Nenhum arquivo consolidado foi gravado."
    assert "CPF529" not in result.stderr  # S2: sem o valor
    rel = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    assert "combinado" not in rel and [i["ok"] for i in rel["arquivos"]] == [True, False, True]


def test_combine_com_tipo_diferente_nao_grava(tmp_path, meses):
    receita = _receita(tmp_path / "r.wolfz.json", None)
    _csv(meses / "2026-02.csv", [("V", "1")], cabecalho="Vendedor;Outra")
    result = _run(receita, meses / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    # Tudo é texto (sem conversão): não há conflito de tipo, só colunas diferentes, com aviso.
    assert result.exit_code == 0, result.output
    assert "os arquivos não têm as mesmas colunas" in result.stderr


# ---------------------------------------------------------------------------
# R4: a saída não vira entrada; arquivos de bloqueio
# ---------------------------------------------------------------------------


def test_consolidado_do_mes_passado_nao_entra_de_novo(tmp_path, meses, simples):
    """O caso que dobraria as linhas em silêncio: -o dentro da pasta do padrão."""
    consolidado = meses / "consolidado.csv"
    assert _run(simples, meses / "2026-*.csv", "--combine", "-o", consolidado).exit_code == 0
    result = _run(simples, meses / "*.csv", "--combine", "-o", consolidado, "--overwrite")
    assert result.exit_code == 0, result.output
    assert "consolidado.csv é a saída deste comando e foi tirado das entradas" in result.stderr
    assert pl.read_csv(consolidado).height == 9


def test_lote_comum_tambem_tira_a_saida(tmp_path, meses, simples):
    assert _run(simples, meses / "*.csv", "-o", meses).exit_code == 2  # cada saída cairia na entrada


def test_um_arquivo_com_a_saida_igual_a_entrada(tmp_path, meses, simples):
    entrada = meses / "2026-01.csv"
    antes = entrada.read_bytes()
    result = _run(simples, entrada, "-o", entrada, "--overwrite")
    assert result.exit_code == 2
    assert entrada.read_bytes() == antes


def test_arquivo_de_bloqueio_do_excel(tmp_path, meses, simples):
    (meses / "~$2026-01.csv").write_bytes(b"\x00lixo")
    (meses / ".~lock.2026-01.csv#").write_bytes(b"lixo")
    result = _run(simples, meses / "*", "--combine", "-o", tmp_path / "v.csv")
    assert result.exit_code == 0, result.output
    assert "~$2026-01.csv é o arquivo de bloqueio de uma planilha aberta e foi ignorado" in result.stderr
    # Pelo nome exato, continua sendo lido (e falhando).
    exato = _run(simples, meses / "~$2026-01.csv", "-o", tmp_path / "x.csv")
    assert exato.exit_code != 0


# ---------------------------------------------------------------------------
# R3: teto antes de ler
# ---------------------------------------------------------------------------


def test_lote_grande_demais_e_recusado_antes_de_ler(tmp_path, meses, simples, monkeypatch):
    import wolfz.cli as cli
    import wolfz.core.engine.juntar as juntar

    monkeypatch.setattr(juntar, "tamanho_declarado", lambda _p: 1024**3)  # 1 GB cada
    lidos = []
    monkeypatch.setattr(
        cli, "read_parts", lambda *a, **k: lidos.append(a) or (_ for _ in ()).throw(AssertionError)
    )
    result = _run(simples, meses / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    assert result.exit_code == 2
    assert "Lote grande demais para juntar" in result.stderr and "Rode sem --combine" in result.stderr
    assert not lidos and not (tmp_path / "v.csv").exists()


def test_arquivos_demais(tmp_path, meses, simples, monkeypatch):
    import wolfz.core.engine.juntar as juntar

    monkeypatch.setattr(juntar, "MAX_PARTES", 2)
    result = _run(simples, meses / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    assert result.exit_code == 2 and "o limite é 2" in result.stderr


# ---------------------------------------------------------------------------
# R7 e R9: nome de arquivo é texto de dado
# ---------------------------------------------------------------------------


def test_nome_de_arquivo_com_cara_de_formula(tmp_path, simples):
    pasta = tmp_path / "e"
    pasta.mkdir()
    _csv(pasta / "=1+1.csv", [("V", "1")])
    _csv(pasta / "b.csv", [("V", "2")])
    result = _run(simples, pasta / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    assert "1 células de texto começam com =" in result.stderr
    neutro = _run(simples, pasta / "*.csv", "--combine", "-o", tmp_path / "n.csv", "--neutralize-formulas")
    assert neutro.exit_code == 0
    assert "'=1+1.csv" in (tmp_path / "n.csv").read_text(encoding="utf-8-sig")


def test_nome_de_arquivo_com_marcacao_sai_literal(tmp_path, simples):
    pasta = tmp_path / "e"
    pasta.mkdir()
    _csv(pasta / "[green]ok[green].csv", [("V", "1")])
    _csv(pasta / "b.csv", [("V", "2")])
    result = _run(simples, pasta / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    assert result.exit_code == 0, result.output
    assert "[green]ok[green].csv  lidas 1" in result.stderr


def test_caminho_nao_vai_para_a_coluna_de_origem(tmp_path, meses, simples):
    _run(simples, Path(meses).resolve() / "*.csv", "--combine", "-o", tmp_path / "v.csv")
    assert all("/" not in a and "\\" not in a for a in pl.read_csv(tmp_path / "v.csv")["arquivo"])

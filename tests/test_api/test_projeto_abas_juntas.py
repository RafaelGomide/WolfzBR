"""API com abas juntas (F3, critérios 2 a 4; D8).

O projeto guarda a grade de cada aba visível na importação, e a regra de
abas da receita escolhe, a cada pedido, quais entram: a mesma regra que o
``wolfz run`` aplica no arquivo.
"""

import io
import json

import polars as pl
import pytest
from apoio_api import XLSX
from openpyxl import Workbook

import wolfz
from wolfz.core.recipe import loads_recipe


def _xlsx(abas: dict[str, int], ocultas=(), extra_col: str | None = None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for nome, n in abas.items():
        ws = wb.create_sheet(nome)
        ws.append([f"Vendas {nome}"])
        cab = ["Vendedor", "Valor"] + ([extra_col] if extra_col and nome == "MAR" else [])
        ws.append(cab)
        for i in range(n):
            ws.append([f"{nome}{i}", str(i)] + (["x"] if extra_col and nome == "MAR" else []))
    for nome in ocultas:
        wb[nome].sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ARQUIVO = _xlsx({"JAN": 3, "FEV": 2, "Base": 1, "MAR": 4}, ocultas=["Base"], extra_col="Canal")


def _criar(client, conteudo=ARQUIVO, **data):
    return client.post("/api/projects", files={"file": ("tri.xlsx", conteudo, XLSX)}, data=data)


def _url(projeto, rota):
    return f"/api/projects/{projeto['id']}/{rota}"


@pytest.fixture
def juntas(client):
    r = _criar(client, sheet="JAN", combine_sheets=json.dumps({}))
    assert r.status_code == 201, r.text
    return r.json()


def test_cria_projeto_com_abas_juntas(juntas):
    receita = juntas["recipe"]
    assert receita["wolfz_version"] == "1.1"
    assert receita["source"]["combine_sheets"] == {"origin_col": "aba"}
    assert "match" not in receita["source"]


def test_preview_atravessa_as_abas(client, juntas):
    corpo = client.get(_url(juntas, "preview"), params={"limit": 4, "offset": 2}).json()
    assert corpo["total_rows"] == 9  # 3 + 2 + 4; a oculta fica de fora
    assert [c["name"] for c in corpo["columns"]] == ["aba", "Vendedor", "Valor", "Canal"]
    assert [r[0] for r in corpo["rows"]] == ["JAN", "FEV", "FEV", "MAR"]
    assert corpo["rows"][0][3] is None  # JAN não tem Canal


def test_preview_igual_ao_run_no_mesmo_arquivo(client, juntas, tmp_path):
    """D8: o que se vê na tela é o que o run grava."""
    arquivo = tmp_path / "tri.xlsx"
    arquivo.write_bytes(ARQUIVO)
    esperado = wolfz.run(loads_recipe(json.dumps(juntas["recipe"])), arquivo)
    corpo = client.get(_url(juntas, "preview"), params={"limit": 1000}).json()
    assert corpo["total_rows"] == esperado.height
    assert corpo["rows"] == [list(r) for r in esperado.rows()]


def test_reconciliacao_por_aba(client, juntas):
    corpo = client.get(_url(juntas, "reconciliation")).json()
    assert corpo["linhas_gravadas"] == 9
    assert [(p["origem"], p["linhas_gravadas"]) for p in corpo["partes"]] == [
        ("JAN", 3),
        ("FEV", 2),
        ("MAR", 4),
    ]
    assert corpo["abas_ocultas"] == ["Base"]
    por_aba = {d["parte"]: d for d in corpo["divergencias"]}
    assert por_aba["MAR"]["a_mais"] == ["Canal"] and por_aba["JAN"]["falta"] == ["Canal"]


def test_trocar_a_regra_muda_as_abas(client, juntas):
    receita = {**juntas["recipe"]}
    receita["source"] = {
        **receita["source"],
        "combine_sheets": {"sheets_regex": "JAN|MAR", "origin_col": "aba"},
    }
    r = client.put(_url(juntas, "recipe"), json=receita, headers={"If-Match": juntas["etag"]})
    assert r.status_code == 200, r.text
    corpo = client.get(_url(juntas, "preview"), params={"limit": 100}).json()
    assert corpo["total_rows"] == 7 and {r[0] for r in corpo["rows"]} == {"JAN", "MAR"}


def test_perfil_e_sugestoes_veem_todas_as_abas(client, juntas):
    perfil = client.get(_url(juntas, "profile")).json()
    assert perfil["total_rows"] == 9
    assert client.get(_url(juntas, "suggestions")).status_code == 200


def test_exportacao_junta_e_o_m_tambem(client, juntas, tmp_path):
    pedido = {"formats": ["csv", "powerquery"], "output_dir": str(tmp_path)}
    r = client.post(_url(juntas, "exports"), json=pedido)
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 9 and r.json()["m_warning"] is None
    csv = next(tmp_path.glob("*.csv"))
    assert pl.read_csv(csv)["aba"].unique(maintain_order=True).to_list() == ["JAN", "FEV", "MAR"]
    m = next(p for p in tmp_path.glob("*.pq") if "CaminhoArquivo" not in p.name).read_text(encoding="utf-8")
    assert "Table.Combine" in m


def test_regra_escrita_a_mao_avisa_que_nao_vai_para_o_m(client, juntas, tmp_path):
    receita = {**juntas["recipe"]}
    receita["source"] = {**receita["source"], "combine_sheets": {"sheets_regex": "JAN|MAR"}}
    client.put(_url(juntas, "recipe"), json=receita, headers={"If-Match": juntas["etag"]})
    r = client.post(_url(juntas, "exports"), json={"formats": ["powerquery"], "output_dir": str(tmp_path)})
    assert "não vai para o Power Query" in r.json()["m_warning"]


def test_projeto_de_uma_aba_so_nao_junta(client):
    projeto = _criar(client, sheet="JAN").json()
    receita = {**projeto["recipe"]}
    receita["source"] = {"type": "excel", "sheet": "JAN", "combine_sheets": {}}
    assert (
        client.put(_url(projeto, "recipe"), json=receita, headers={"If-Match": projeto["etag"]}).status_code
        == 200
    )
    r = client.get(_url(projeto, "preview"))
    assert r.status_code == 422 and "importe o arquivo de novo" in r.json()["detail"]


def test_combine_sheets_invalido(client):
    r = _criar(client, sheet="JAN", combine_sheets=json.dumps({"arquivos": "../*.xlsx"}))
    assert r.status_code == 422
    r = _criar(client, sheet="JAN", combine_sheets=json.dumps({"sheets_regex": "NADA"}))
    assert r.status_code == 422 and "Nenhuma aba" in r.json()["detail"]


@pytest.mark.parametrize(
    ("marcadas", "regra", "casam"),
    [
        (["JAN", "FEV", "MAR"], None, ["JAN", "FEV", "MAR"]),
        (["JAN", "MAR"], "JAN|MAR", ["JAN", "MAR"]),
        # Nome com número: o padrão do mês escolhe as mesmas abas e aceita as próximas.
        (["a.b (1)"], r"(?i)a\.b\ \(\d+\)", ["a.b (1)"]),
    ],
)
def test_regra_das_abas_marcadas(client, marcadas, regra, casam):
    disponiveis = ["JAN", "FEV", "MAR", "a.b (1)"] if "a.b (1)" in marcadas else ["JAN", "FEV", "MAR"]
    r = client.post("/api/sheets/combine-rule", json={"sheets": marcadas, "available": disponiveis})
    assert r.status_code == 200, r.text
    assert r.json()["sheets_regex"] == regra and r.json()["matches"] == casam


def test_regra_prefere_o_padrao_do_mes(client):
    disponiveis = ["Vendas JAN 2025", "Vendas FEV 2025", "Resumo"]
    r = client.post(
        "/api/sheets/combine-rule",
        json={"sheets": disponiveis[:2], "available": disponiveis, "recipe_sheet": "Vendas JAN 2025"},
    ).json()
    assert r["sheets_regex"].startswith("(?i)Vendas") and r["matches"] == disponiveis[:2]


def test_regra_com_aba_que_nao_existe(client):
    r = client.post("/api/sheets/combine-rule", json={"sheets": ["X"], "available": ["JAN"]})
    assert r.status_code == 422

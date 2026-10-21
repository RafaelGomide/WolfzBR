"""Aba que muda de nome todo mês (F2.F4)."""

import re
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

import wolfz
import wolfz.ops
from wolfz.core.engine import StepError
from wolfz.core.ingest import IngestError
from wolfz.core.ingest.abas import molde_de_aba, padrao_de_aba
from wolfz.core.recipe import recipe_from_dict
from wolfz.export.m import recipe_to_m
from wolfz.export.python import recipe_to_python

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "test_export"))
from m_parser import parse_m


@pytest.mark.parametrize(
    ("nome", "aceita", "recusa"),
    [
        ("DEZEMBRO_2025", ["JANEIRO_2026", "Março_2026", "dez_2024"], ["RESUMO_2026", "DEZEMBRO"]),
        ("Vendas 2024", ["vendas 2025"], ["Vendas", "Compras 2025"]),
        ("Jan-25", ["Fev-26", "jan.-24"], ["Jan-2025"]),
        ("2025", ["2026"], ["Resumo", "202"]),
    ],
)
def test_padrao_e_molde_concordam(nome, aceita, recusa):
    padrao = padrao_de_aba(nome)
    for outra in aceita:
        assert re.fullmatch(padrao, outra), outra
    for outra in recusa:
        assert not re.fullmatch(padrao, outra), outra
        assert molde_de_aba(outra) != molde_de_aba(nome), outra
    for outra in aceita:
        if "." not in outra:
            assert molde_de_aba(outra) == molde_de_aba(nome), outra


@pytest.mark.parametrize("nome", ["Resumo", "Plan1", "Planilha 2", "Sheet1", "", None])
def test_aba_sem_numero_nem_mes_nao_tem_padrao(nome):
    assert padrao_de_aba(nome) is None


def test_padrao_escapa_o_nome():
    assert padrao_de_aba("a.b (2024)") == r"(?i)a\.b\ \(\d{4}\)"


def _planilha(path: Path, aba: str) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws2 = wb.create_sheet(aba)
    for linha in [["Município", "Valor"], ["Vitória", "10"], ["Serra", "20"]]:
        ws2.append(linha)
    wb.save(path)
    return path


def _receita(match: bool):
    source = {"type": "excel", "sheet": "DEZEMBRO_2025"}
    if match:
        source["match"] = {"sheet_name_regex": padrao_de_aba("DEZEMBRO_2025")}
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "mensal",
            "created_at": "2026-01-01T00:00:00Z",
            "source": source,
            "steps": [{"id": "s1", "op": "header_rows", "n": 1}],
        }
    )


def test_reaplica_no_mes_seguinte(tmp_path):
    janeiro = _planilha(tmp_path / "janeiro.xlsx", "JANEIRO_2026")
    df = wolfz.run(_receita(match=True), janeiro)
    assert df.to_dict(as_series=False) == {"Município": ["Vitória", "Serra"], "Valor": ["10", "20"]}
    with pytest.raises((IngestError, StepError)):
        wolfz.run(_receita(match=False), janeiro)


def test_script_exportado_acha_a_aba_do_mes_seguinte(tmp_path):
    janeiro = _planilha(tmp_path / "janeiro.xlsx", "JANEIRO_2026")
    script = tmp_path / "limpeza.py"
    script.write_text(recipe_to_python(_receita(match=True)), encoding="utf-8")
    saida = tmp_path / "saida.csv"
    subprocess.run([sys.executable, "-I", str(script), str(janeiro), str(saida)], check=True)
    assert saida.read_text(encoding="utf-8").splitlines() == ["Município,Valor", "Vitória,10", "Serra,20"]


def test_m_cai_no_molde_quando_a_aba_exata_nao_existe():
    m = recipe_to_m(_receita(match=True))
    assert 'molde = WolfzMoldeAba("DEZEMBRO_2025")' in m
    assert "WolfzMoldeAba = " in m
    assert "Nenhuma aba se chama" in m
    sem = recipe_to_m(_receita(match=False))
    assert "WolfzMoldeAba" not in sem
    assert all(r["ok"] for r in parse_m([m, sem]))

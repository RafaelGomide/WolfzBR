"""Juntar abas no M e no script Python exportados (F3, critério 10; R8).

O nome de cada aba é lido do arquivo na hora de rodar: ele nunca entra no
código gerado. Na consulta e no script só entram a regex (no script) ou o
molde (no M) e o nome da coluna de origem, pelo escape de cada linguagem.
"""

import ast
import subprocess
import sys

import polars as pl
import pytest
from m_parser import parse_m
from m_sintaxe import check_m
from openpyxl import Workbook
from polars.testing import assert_frame_equal

import wolfz
from wolfz.core.ingest.abas import padrao_de_aba
from wolfz.core.recipe import recipe_from_dict
from wolfz.export.m import aviso_de_abas, recipe_to_m
from wolfz.export.python import recipe_to_python

# Nomes válidos no Excel (sem / \ ? * [ ] :), escolhidos para fechar a string
# do M ou do Python se entrassem crus.
HOSTIS = ['a"b', 'x") , Web.Contents("exemplo', "x'); import os #"]  # o Excel recusa ' no começo


def _planilha(path, abas, ocultas=()):
    wb = Workbook()
    wb.remove(wb.active)
    for i, nome in enumerate(abas):
        ws = wb.create_sheet(nome)
        ws.append([f"Relatório {i}"])
        ws.append(["Vendedor", "Valor"])
        for j in range(i + 1):
            ws.append([f"V{j}", str(j)])
    for nome in ocultas:
        wb[nome].sheet_state = "hidden"
    wb.save(path)
    return path


def _receita(combine, sheet="JAN"):
    return recipe_from_dict(
        {
            "wolfz_version": "1.1",
            "name": "vendas",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel", "sheet": sheet, "combine_sheets": combine},
            "steps": [
                {"id": "s1", "op": "select_range", "start": "A2"},
                {"id": "s2", "op": "header_rows"},
                {"id": "s3", "op": "parse_decimal_br", "cols": ["Valor"]},
            ],
        }
    )


@pytest.mark.parametrize("origem", ["aba", None, 'x") , Web.Contents("http://exemplo")) //'])
def test_m_junta_as_abas_visiveis(origem):
    m = recipe_to_m(_receita({"origin_col": origem}))
    check_m(m)
    assert 'Table.SelectRows(Arquivo, each [Kind] = "Sheet" and not [Hidden])' in m
    assert "Table.Combine(List.Transform(Table.ToRecords(Abas)" in m
    assert "Limpar = (Aba as table) as table =>" in m
    if origem is not None and "Web" in origem:
        # Só aparece dentro de um literal do M, escapado: nenhuma chamada a mais.
        comum = recipe_to_m(_receita({"origin_col": "aba"}))
        assert "Web.Contents" not in comum
        assert m.replace('"x"") , Web.Contents(""http://exemplo"")) //"', '"aba"') == comum


def test_m_com_o_parser_oficial():
    documentos = [recipe_to_m(_receita({"origin_col": o})) for o in ("aba", None, 'a"b')]
    for r in parse_m(documentos):
        assert r["ok"], r


def test_m_com_o_padrao_do_mes_vira_molde():
    receita = _receita({"sheets_regex": padrao_de_aba("Vendas JAN 2025")}, sheet="Vendas JAN 2025")
    m = recipe_to_m(receita)
    assert 'WolfzMoldeAba([Item]) = WolfzMoldeAba("Vendas JAN 2025")' in m
    assert aviso_de_abas(receita) is None


def test_m_com_regex_a_mao_avisa():
    receita = _receita({"sheets_regex": "(?i)jan|fev"})
    assert "não vai para o Power Query" in aviso_de_abas(receita)
    assert "// Atenção: O padrão de nome das abas" in recipe_to_m(receita)


@pytest.mark.parametrize("origem", ["aba", None, "'); import os #"])
def test_script_python_e_codigo_valido(origem):
    script = recipe_to_python(_receita({"origin_col": origem, "sheets_regex": r"a'\); import os #|.*"}))
    arvore = ast.parse(script)
    chamadas = {
        n.func.attr for n in ast.walk(arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    comum = {
        n.func.attr
        for n in ast.walk(ast.parse(recipe_to_python(_receita({}))))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert chamadas == comum
    assert "import os" not in [ln.strip() for ln in script.splitlines()]


def test_script_python_junta_as_mesmas_abas_que_o_wolfzbr(tmp_path):
    """R8 e critério 10: abas com nome hostil, uma oculta; o script lê e
    junta exatamente as mesmas abas e bate com o WolfzBR."""
    arquivo = _planilha(tmp_path / "hostil.xlsx", ["JAN", *HOSTIS, "Oculta"], ocultas=["Oculta"])
    receita = _receita({})
    esperado = wolfz.run(receita, arquivo)
    assert esperado["aba"].unique(maintain_order=True).to_list() == ["JAN", *HOSTIS]
    script = tmp_path / "limpeza.py"
    script.write_text(recipe_to_python(receita), encoding="utf-8")
    saida = tmp_path / "saida.parquet"
    subprocess.run([sys.executable, "-I", str(script), str(arquivo), str(saida)], check=True)
    assert_frame_equal(pl.read_parquet(saida), esperado)


def test_script_python_com_regex_e_sem_origem(tmp_path):
    arquivo = _planilha(tmp_path / "tri.xlsx", ["JAN", "FEV", "Resumo"])
    receita = _receita({"sheets_regex": "JAN|FEV", "origin_col": None})
    script = tmp_path / "limpeza.py"
    script.write_text(recipe_to_python(receita), encoding="utf-8")
    saida = tmp_path / "saida.parquet"
    subprocess.run([sys.executable, "-I", str(script), str(arquivo), str(saida)], check=True)
    assert_frame_equal(pl.read_parquet(saida), wolfz.run(receita, arquivo))

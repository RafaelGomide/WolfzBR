"""Riscos do §11.5 do design, cada um com o teste da sua mitigação (FH.C1).

``RISCOS`` liga cada linha da tabela aos testes que provam a mitigação. O
primeiro teste lê a tabela no próprio design: linha nova sem teste, ou
teste que sumiu, quebra aqui. Os demais cobrem o que ainda não tinha teste,
inclusive as mitigações do §11.4 (regex, caminhos, receita de terceiros).
"""

import ast
import json
import re
import time
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from wolfz.api.rotas import _nome_seguro
from wolfz.core.engine import StepError, collect
from wolfz.core.recipe import RecipeError, recipe_from_dict
from wolfz.core.workspace import Workspace
from wolfz.export.python import recipe_to_python

RAIZ = Path(__file__).resolve().parents[2]
TESTES = RAIZ / "tests"

RISCOS = {
    "Página web maliciosa chamando a API local": [
        "test_api/test_seguranca.py::test_api_exige_token_bearer",
        "test_api/test_seguranca.py::test_host_estranho_e_recusado",
        "test_api/test_seguranca.py::test_sem_cors_em_producao",
        "test_api/test_seguranca.py::test_token_vai_no_fragmento_da_url",
    ],
    "Outro usuário da rede acessando a API": [
        "test_api/test_seguranca.py::test_servidor_escuta_so_no_loopback",
    ],
    "Injeção de código no M ou no Python exportado": [
        "test_export/test_m.py::test_escapes_hostis_passam_no_parser",
        "test_export/test_python.py::test_nome_hostil_no_cabecalho",
        "test_api/test_riscos.py::test_python_exportado_com_nomes_e_valores_hostis",
        "test_export/test_tableau.py::test_tds_escapa_nomes",
    ],
    "Injeção de fórmula em CSV/Excel exportado": [
        "test_export/test_dados.py::test_neutralizar_desligado_por_padrao",
        "test_export/test_dados.py::test_neutralizar_no_csv",
        "test_export/test_dados.py::test_xlsx_texto_nunca_vira_formula",
        "test_api/test_rotas.py::test_exportar_conta_e_neutraliza_formulas",
    ],
    "Zip bomb / arquivo gigante": [
        "test_ingest/test_formatos.py::test_zip_bomb_pela_razao",
        "test_ingest/test_formatos.py::test_zip_grande_demais_descompactado",
        "test_ingest/test_formatos.py::test_arquivo_grande_demais",
        "test_api/test_seguranca.py::test_upload_acima_do_limite_pelo_content_length",
        "test_api/test_seguranca.py::test_upload_sem_content_length_para_na_copia_sem_deixar_rastro",
    ],
    "Consumo irrestrito de recurso": [
        "test_api/test_rotas.py::test_preview_parametros_invalidos",
        "test_api/test_rotas.py::test_um_preview_por_projeto_por_vez",
        "test_api/test_riscos.py::test_regex_do_usuario_roda_em_tempo_linear",
    ],
    "Dependência comprometida (supply chain)": [
        "test_api/test_riscos.py::test_ci_instala_pelo_lockfile_e_audita",
    ],
    "Dado de cliente em log ou relatório de erro": [
        "test_api/test_privacidade.py::test_fluxo_completo_sem_rede_e_sem_dado_no_log",
        "test_api/test_rotas.py::test_erro_inesperado_nao_vaza_detalhe",
    ],
}


def _linhas_da_tabela() -> list[str]:
    design = (RAIZ / "docs" / "system_design.md").read_text(encoding="utf-8")
    secao = design.split("### 11.5", 1)[1].split("\n### ", 1)[0]
    linhas = [ln for ln in secao.splitlines() if ln.startswith("| ") and not ln.startswith("| Risco")]
    return [ln.split("|")[1].strip() for ln in linhas if not set(ln) <= set("|- ")]


def _testes_do_arquivo(caminho: Path) -> set[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    return {n.name for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


def test_cada_risco_do_design_tem_teste():
    riscos = _linhas_da_tabela()
    assert len(riscos) == 8
    sem_mapa = [r for r in riscos if not any(r.startswith(chave) for chave in RISCOS)]
    assert not sem_mapa, f"risco sem teste em RISCOS: {sem_mapa}"
    for chave, testes in RISCOS.items():
        assert any(r.startswith(chave) for r in riscos), f"{chave!r} não está mais no §11.5"
        assert testes
        for alvo in testes:
            arquivo, nome = alvo.split("::")
            assert nome in _testes_do_arquivo(TESTES / arquivo), f"{alvo} não existe"


# ---------------------------------------------------------------------------
# Injeção no Python exportado: nome de coluna e literal da receita
# ---------------------------------------------------------------------------

HOSTIS = ['a"; import os; os.system("x"); "', "linha\nquebrada", "fim\\", "'''", "{__import__('os')}"]


def test_python_exportado_com_nomes_e_valores_hostis():
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "hostil",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [
                {"id": "s1", "op": "header_rows", "n": 1},
                {"id": "s2", "op": "rename", "mapping": {"A": HOSTIS[0], "B": HOSTIS[1]}},
                *(
                    {"id": f"s{i}", "op": "replace", "cols": [HOSTIS[0]], "old": "x", "new": h}
                    for i, h in enumerate(HOSTIS, 3)
                ),
            ],
        }
    )
    script = recipe_to_python(receita, today=date(2026, 1, 1))
    arvore = ast.parse(script)
    constantes = {n.value for n in ast.walk(arvore) if isinstance(n, ast.Constant)}
    for hostil in HOSTIS:
        assert hostil in constantes, f"{hostil!r} não ficou como literal"
    chamadas = {
        n.func.attr for n in ast.walk(arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "system" not in chamadas
    # O script importa o mesmo que o de uma receita sem passos com nome hostil.
    assert _imports(arvore) == _imports(ast.parse(recipe_to_python(_sem_hostis(receita))))


def _imports(arvore: ast.AST) -> set[str]:
    nomes = {a.name for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
    return nomes | {n.module for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom) and n.module}


def _sem_hostis(receita):
    """A mesma receita com os textos hostis trocados por inofensivos."""
    texto = receita.model_dump_json()
    for i, hostil in enumerate(HOSTIS):
        texto = texto.replace(json.dumps(hostil)[1:-1], f"nome{i}")
    return recipe_from_dict(json.loads(texto))


# ---------------------------------------------------------------------------
# Regex do usuário: motor do Polars, tempo linear (§11.4)
# ---------------------------------------------------------------------------


def test_regex_do_usuario_roda_em_tempo_linear():
    """'(a+)+$' contra 'aaa…b' é backtracking catastrófico no ``re`` do
    Python (anos). No motor do Polars (crate regex), é linear."""
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "regex",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": "s1", "op": "assert", "check": "matches", "cols": ["A"], "pattern": "(a+)+$"}],
        }
    )
    grade = pl.DataFrame({"A": ["a" * 50_000 + "b"] * 200})
    inicio = time.perf_counter()
    with pytest.raises(StepError):  # a verificação reprova: nenhum valor casa
        collect(receita, grade.lazy())
    assert time.perf_counter() - inicio < 5


# ---------------------------------------------------------------------------
# Caminhos (§11.4): nada escapa da pasta escolhida
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("project_id", ["..", "../x", "..\\x", "01ABC/../..", "C:\\Windows", "%2e%2e"])
def test_id_de_projeto_nao_vira_caminho(tmp_path, project_id):
    with pytest.raises(ValueError, match="inválido"):
        Workspace(tmp_path).project_dir(project_id)


@pytest.mark.parametrize("project_id", ["..", "..%2F..%2Fsegredo", "%2e%2e", "x" * 26])
def test_api_responde_404_para_id_estranho(client, project_id):
    assert client.get(f"/api/projects/{project_id}").status_code == 404


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("../../fora.csv", "fora.csv"),
        ("..\\..\\fora.csv", "fora.csv"),
        ("C:\\Windows\\system32\\x.xlsx", "x.xlsx"),
        ("/etc/passwd", "passwd"),
        ("..", "tabela"),
        ("", "tabela"),
        ("nome com espaço;e|pipe.csv", "nome_com_espaço_e_pipe.csv"),
    ],
)
def test_nome_de_arquivo_seguro(nome, esperado):
    assert _nome_seguro(nome) == esperado


def test_upload_com_nome_que_tenta_sair_da_pasta(client, settings, tmp_path):
    caminho = Path(__file__).resolve().parents[1] / "corpus" / "receita_municipal" / "original.xlsx"
    with caminho.open("rb") as f:
        r = client.post(
            "/api/projects", files={"file": ("../../../fora.xlsx", f, "application/octet-stream")}
        )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "fora.xlsx"
    raiz = settings.workspace.root
    assert not list(raiz.parent.glob("fora.xlsx")) and not list(raiz.parent.parent.glob("fora.xlsx"))


# ---------------------------------------------------------------------------
# Receita de terceiros: catálogo fechado, nada executa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "passo",
    [
        {"id": "s1", "op": "eval", "code": "__import__('os').system('x')"},
        {"id": "s1", "op": "trim", "cols": ["A"], "__class__": "os.system"},
        {"id": "s1", "op": "python", "source": "import os"},
    ],
)
def test_receita_de_terceiros_so_tem_operacoes_do_catalogo(passo):
    with pytest.raises(RecipeError):
        recipe_from_dict(
            {
                "wolfz_version": "1.0",
                "name": "de fora",
                "created_at": "2026-01-01T00:00:00Z",
                "source": {"type": "csv"},
                "steps": [passo],
            }
        )


# ---------------------------------------------------------------------------
# Supply chain: instalação pelo lockfile e auditoria no CI
# ---------------------------------------------------------------------------


def test_ci_instala_pelo_lockfile_e_audita():
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    instalacoes = re.findall(r"uv sync[^\n]*", ci)
    assert instalacoes and all("--locked" in i for i in instalacoes)
    assert "npm install" not in ci and "npm ci" in ci
    auditoria = (RAIZ / ".github" / "workflows" / "auditoria.yml").read_text(encoding="utf-8")
    assert "uv export --frozen" in auditoria and "pip-audit" in auditoria
    assert "npm audit --audit-level=high --prefix frontend" in auditoria
    assert "schedule:" in auditoria

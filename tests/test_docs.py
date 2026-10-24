"""Documentação em dia com o código (FH.D).

- ``docs/operacoes.md`` é gerado do catálogo: operação nova, parâmetro
  renomeado ou exemplo mudado sem regerar o arquivo quebra aqui;
- todo link relativo dos documentos aponta para um arquivo que existe e,
  com ``#âncora`` para outro ``.md`` do repositório, para um título dele.
"""

import importlib.util
import re
import unicodedata
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DOCUMENTOS = [
    RAIZ / "README.md",
    RAIZ / "CONTRIBUTING.md",
    RAIZ / "SECURITY.md",
    RAIZ / "CHANGELOG.md",
    *sorted((RAIZ / "docs").rglob("*.md")),
]


def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_operacoes", RAIZ / "scripts" / "gerar_operacoes.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_operacoes_md_em_dia():
    gerado = _gerador().gerar()
    atual = (RAIZ / "docs" / "operacoes.md").read_text(encoding="utf-8")
    assert atual == gerado, "docs/operacoes.md desatualizado: rode uv run python scripts/gerar_operacoes.py"


def _ancoras(caminho: Path) -> set[str]:
    """Âncoras que o GitHub gera para os títulos, mais os <a id> explícitos."""
    texto = caminho.read_text(encoding="utf-8")
    ancoras = set(re.findall(r'<a id="([^"]+)"', texto))
    for titulo in re.findall(r"^#{1,6} (.+)$", texto, flags=re.MULTILINE):
        slug = unicodedata.normalize("NFC", titulo.strip().lower())
        slug = re.sub(r"[^\w\- ]", "", slug).replace(" ", "-")
        ancoras.add(slug)
    return ancoras


LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=lambda p: p.relative_to(RAIZ).as_posix())
def test_links_relativos_existem(documento):
    texto = re.sub(r"```.*?```", "", documento.read_text(encoding="utf-8"), flags=re.DOTALL)
    quebrados = []
    for alvo in LINK.findall(texto):
        caminho, _, ancora = alvo.partition("#")
        destino = (documento.parent / caminho).resolve()
        sem_ancora = bool(ancora) and destino.suffix == ".md" and ancora not in _ancoras(destino)
        if not destino.exists() or sem_ancora:
            quebrados.append(alvo)
    assert not quebrados, f"links quebrados em {documento.name}: {quebrados}"


def test_ancora_do_github():
    """O slug segue o do GitHub: minúsculas, sem pontuação, espaço vira hífen."""
    caminho = RAIZ / "docs" / "system_design.md"
    assert "11-segurança" in _ancoras(caminho)


def test_exemplo_de_receita_md_e_valido_e_canonico():
    """O exemplo de docs/receita.md abre e é exatamente o que o WolfzBR grava."""
    from wolfz.core.recipe import dumps_recipe, loads_recipe

    texto = (RAIZ / "docs" / "receita.md").read_text(encoding="utf-8")
    exemplo = re.search(r"```json\n(.*?)```", texto, flags=re.DOTALL)[1]
    assert dumps_recipe(loads_recipe(exemplo)) == exemplo

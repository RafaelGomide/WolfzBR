"""Engenharia de release (FH.E): conferência do pacote, notas e workflow."""

import importlib.util
import io
import re
import tarfile
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _script(nome: str):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "scripts" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


pacote = _script("conferir_pacote")
notas = _script("notas_da_versao")

WHEEL_BOM = {
    "wolfz/__init__.py": "",
    "wolfz/static/index.html": "<html>",
    "wolfz/static/assets/index-abc.js": "",
    "wolfz/br/data/municipios.parquet": "",
    "wolfz/export/pbip/templates/model.tmdl": "",
    "wolfzbr-1.0.0.dist-info/licenses/LICENSE": "MIT",
    "wolfzbr-1.0.0.dist-info/licenses/NOTICE": "IBGE",
    "wolfzbr-1.0.0.dist-info/METADATA": "Metadata-Version: 2.4\nName: wolfzbr\nVersion: 1.0.0\n",
    "wolfzbr-1.0.0.dist-info/entry_points.txt": "[console_scripts]\nwolfz = wolfz.cli:app\n",
}


def _wheel(tmp_path: Path, arquivos: dict[str, str]) -> Path:
    caminho = tmp_path / "wolfzbr-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(caminho, "w") as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo)
    return caminho


def _sdist(tmp_path: Path, nomes: list[str]) -> Path:
    caminho = tmp_path / "wolfzbr-1.0.0.tar.gz"
    with tarfile.open(caminho, "w:gz") as tf:
        for nome in nomes:
            info = tarfile.TarInfo(f"wolfzbr-1.0.0/{nome}")
            tf.addfile(info, io.BytesIO(b""))
    return caminho


SDIST_BOM = [
    "src/wolfz/static/index.html",
    "src/wolfz/static/assets/index-abc.js",
    "src/wolfz/br/data/municipios.parquet",
    "src/wolfz/export/pbip/templates/model.tmdl",
    "pyproject.toml",
    "hatch_build.py",
    "README.md",
    "LICENSE",
    "NOTICE",
]


def test_wheel_completo_passa(tmp_path):
    assert pacote.conferir_wheel(_wheel(tmp_path, WHEEL_BOM), "1.0.0") == []


def test_wheel_sem_interface_e_com_testes_reprova(tmp_path):
    arquivos = {k: v for k, v in WHEEL_BOM.items() if "static" not in k}
    arquivos["tests/corpus/x/original.csv"] = "a;b"
    erros = pacote.conferir_wheel(_wheel(tmp_path, arquivos), "1.0.0")
    assert any("interface compilada" in e for e in erros)
    assert any("tests/corpus/x/original.csv" in e for e in erros)


def test_wheel_de_outra_versao_ou_sem_comando_reprova(tmp_path):
    arquivos = {**WHEEL_BOM, "wolfzbr-1.0.0.dist-info/entry_points.txt": ""}
    erros = pacote.conferir_wheel(_wheel(tmp_path, arquivos), "1.0.1")
    assert "falta o comando wolfz em entry_points.txt" in erros
    assert "a versão no METADATA não é 1.0.1" in erros


def test_sdist(tmp_path):
    assert pacote.conferir_sdist(_sdist(tmp_path, SDIST_BOM)) == []
    erros = pacote.conferir_sdist(_sdist(tmp_path, [*SDIST_BOM[1:], "frontend/src/App.tsx", "dev/x.md"]))
    assert any("interface compilada" in e for e in erros)
    assert any("frontend/src/App.tsx" in e for e in erros) and any("dev/x.md" in e for e in erros)


CHANGELOG = """# Changelog

## [Não publicado]

Congelamento.

### Adicionado

- [`docs/receita.md`](docs/receita.md) e [site](https://exemplo.org).

## [0.9.0] - 2026-10-22

Power BI.

[Não publicado]: https://github.com/RafaelGomide/WolfzBR/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.8.0...v0.9.0
"""


def test_notas_da_versao_publicada():
    texto = notas.notas("0.9.0", CHANGELOG)
    assert texto.startswith("Power BI.")
    assert "Congelamento" not in texto and "compare/" not in texto
    assert "pipx install wolfzbr\n" in texto


def test_notas_da_rc_usam_nao_publicado_com_links_absolutos():
    texto = notas.notas("1.0.0rc1", CHANGELOG)
    assert texto.startswith("Versão de teste")
    assert "Congelamento." in texto
    assert "(https://github.com/RafaelGomide/WolfzBR/blob/v1.0.0rc1/docs/receita.md)" in texto
    assert "[site](https://exemplo.org)" in texto
    assert 'pipx install "wolfzbr==1.0.0rc1"' in texto


def test_versao_final_sem_secao_e_erro():
    with pytest.raises(SystemExit, match=r"## \[1.0.0\]"):
        notas.notas("1.0.0", CHANGELOG)


def test_changelog_de_verdade_tem_as_versoes_publicadas():
    for versao in ("0.1.0", "0.9.0"):
        assert notas.notas(versao).strip()


def test_workflow_de_release():
    texto = (RAIZ / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert re.search(r"tags: \[\"v\*\"\]", texto)
    # Trusted Publishing: nenhum token salvo, id-token só nos jobs que publicam.
    assert "secrets." not in texto
    assert texto.count("id-token: write") == 2
    assert "repository-url: https://test.pypi.org/legacy/" in texto
    passos = ("npm run build", "uv build", "conferir_pacote.py", "notas_da_versao.py", "gh release create")
    for passo in passos:
        assert passo in texto
    assert "name: pypi" in texto and "name: testpypi" in texto

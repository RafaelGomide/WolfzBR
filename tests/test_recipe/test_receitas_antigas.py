"""Receitas reais de cada versão publicada abrem no WolfzBR atual (F2.G1).

``tests/receitas_antigas/<tag>/`` foi gravado pelo código daquela tag
(``scripts/receitas_antigas.py``): receitas do corpus como ela as salvava e
a tabela que o motor dela produzia, mais ``catalogo.wolfz.json``, com um
passo por exemplo de cada operação que ela tinha. Aqui elas passam pela
migração e precisam:

- carregar sem erro e chegar ao formato atual;
- manter cada parâmetro gravado (nada some nem muda de valor ao carregar);
- dar a mesma tabela no mesmo arquivo.

Os arquivos não são editados à mão. Se um teste quebrar, ou o resultado
mudou sem querer, ou a mudança foi de propósito e precisa de uma migração
em ``wolfz.core.recipe.migrate``.
"""

import json
import re
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import wolfz
from wolfz.core.engine import run_file
from wolfz.core.recipe import CURRENT_VERSION, load_recipe, migrate

TESTES = Path(__file__).resolve().parents[1]
ANTIGAS = TESTES / "receitas_antigas"
RAIZ = TESTES.parent
TAGS = sorted(p.name for p in ANTIGAS.iterdir() if p.is_dir())


def _manifesto(tag: str) -> dict:
    return json.loads((ANTIGAS / tag / "manifesto.json").read_text(encoding="utf-8"))


RECEITAS = [
    pytest.param(tag, nome, entrada, id=f"{tag}-{nome}")
    for tag in TAGS
    for nome, entrada in sorted(_manifesto(tag)["entradas"].items())
]


def _contem(gravado, atual) -> bool:
    """Tudo o que estava gravado continua lá, com o mesmo valor."""
    if isinstance(gravado, dict):
        return isinstance(atual, dict) and all(
            k in atual and _contem(v, atual[k]) for k, v in gravado.items()
        )
    if isinstance(gravado, list):
        return (
            isinstance(atual, list)
            and len(gravado) == len(atual)
            and all(_contem(g, a) for g, a in zip(gravado, atual, strict=True))
        )
    return gravado == atual


def _confere_parametros(caminho: Path):
    gravado = migrate(json.loads(caminho.read_text(encoding="utf-8")))
    receita = load_recipe(caminho)
    assert receita.wolfz_version == CURRENT_VERSION
    atual = receita.model_dump(mode="json")
    for antes, depois in zip(gravado["steps"], atual["steps"], strict=True):
        assert _contem(antes, depois), (antes, depois)
    assert _contem(gravado["source"], atual["source"])
    assert gravado["name"] == atual["name"]
    return receita


def test_ha_receitas_de_toda_versao_publicada():
    """Toda versão do CHANGELOG, menos a que está saindo agora, tem a sua
    pasta: ao publicar, rode ``scripts/receitas_antigas.py`` com a tag."""
    changelog = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    publicadas = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, flags=re.MULTILINE)
    assert publicadas
    faltam = [v for v in publicadas if v != wolfz.__version__ and f"v{v}" not in TAGS]
    assert not faltam, f"sem receitas guardadas: {faltam}"


@pytest.mark.parametrize("tag", TAGS)
def test_catalogo_da_versao_carrega(tag):
    """Um passo por exemplo de cada operação que a versão tinha."""
    manifesto = _manifesto(tag)
    receita = _confere_parametros(ANTIGAS / tag / "catalogo.wolfz.json")
    assert {s.op for s in receita.steps} == set(manifesto["catalogo"])


@pytest.mark.parametrize(("tag", "nome", "entrada"), RECEITAS)
def test_receita_antiga_da_a_mesma_tabela(tag, nome, entrada):
    receita = _confere_parametros(ANTIGAS / tag / f"{nome}.wolfz.json")
    caminho = RAIZ / entrada if entrada.startswith("tests/") else ANTIGAS / entrada
    esperado = pl.read_parquet(ANTIGAS / tag / f"{nome}.parquet")
    assert_frame_equal(run_file(receita, caminho), esperado)

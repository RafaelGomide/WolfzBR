"""O caso de uso central, de ponta a ponta: a receita montada na interface
com o arquivo de junho, reaplicada ao de julho (mesmo layout, o dobro de
linhas), traz a tabela inteira. Os arquivos são os do roteiro de smoke test
(``docs/smoke_test.md``, em ``tests/corpus/_fixtures/smoke/``).

Antes da 1.0, a receita inicial fixava a célula final da área e o arquivo
de julho saía cortado nas linhas de junho, com código 0."""

from pathlib import Path

import pytest

from wolfz.core.engine import StepError, run_file
from wolfz.core.recipe import recipe_from_dict

SMOKE = Path(__file__).resolve().parents[1] / "corpus" / "_fixtures" / "smoke"
FORMA, VERIFICACAO = 40, 50


def _etapa(order: int) -> int:
    return 0 if order < FORMA else 1 if order < VERIFICACAO else 2


def _receita_da_interface(client) -> dict:
    """Importa junho.csv e aceita todas as sugestões, uma etapa por vez,
    como o botão "Aceitar todas" faz."""
    with (SMOKE / "junho.csv").open("rb") as f:
        projeto = client.post("/api/projects", files={"file": ("junho.csv", f, "text/csv")}).json()
    url = f"/api/projects/{projeto['id']}"
    receita, etag = projeto["recipe"], projeto["etag"]
    for _ in range(4):
        sugestoes = [s for s in client.get(url + "/suggestions").json() if s["steps"]]
        if not sugestoes:
            break
        primeira = min(_etapa(s["order"]) for s in sugestoes)
        novos = [p for s in sugestoes if _etapa(s["order"]) == primeira for p in s["steps"]]
        n = len(receita["steps"])
        passos = receita["steps"] + [{**p, "id": f"s{n + i}"} for i, p in enumerate(novos, 1)]
        r = client.put(url + "/recipe", json={**receita, "steps": passos}, headers={"If-Match": etag})
        assert r.status_code == 200, r.text
        receita, etag = r.json()["recipe"], r.json()["etag"]
    return receita


def test_receita_de_junho_traz_julho_inteiro(client):
    receita = recipe_from_dict(_receita_da_interface(client))
    assert run_file(receita, SMOKE / "junho.csv").height == 15
    julho = run_file(receita, SMOKE / "julho.csv")
    assert julho.height == 30
    assert any(s.op == "assert" for s in receita.steps), "as verificações sugeridas entraram"


def test_arquivo_de_outro_formato_falha_com_a_coluna_que_falta(client):
    receita = recipe_from_dict(_receita_da_interface(client))
    with pytest.raises(StepError) as exc:
        run_file(receita, SMOKE / "outro_formato.csv")
    assert "REMUNERAÇÃO BÁSICA BRUTA (R$)" in exc.value.message
    assert "Data da Coleta" in exc.value.available_columns

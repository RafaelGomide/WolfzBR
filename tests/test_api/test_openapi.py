"""O OpenAPI versionado em ``frontend/`` precisa bater com a API: é dele que
sai o cliente TypeScript da interface (F1.H1)."""

import importlib.util
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location("gerar_openapi", RAIZ / "scripts" / "gerar_openapi.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_openapi_da_interface_esta_em_dia():
    script = _script()
    assert script.DESTINO.read_text(encoding="utf-8") == script.openapi(), (
        "frontend/src/api/openapi.json desatualizado: rode python scripts/gerar_openapi.py "
        "e depois npm run api em frontend/"
    )


def test_openapi_tipa_as_respostas():
    spec = json.loads(_script().openapi())
    esquemas = spec["components"]["schemas"]
    for nome in ("Projeto", "ProjetoCriado", "ProjetoResumo", "Pagina", "Perfil", "Operacao", "Aba"):
        assert nome in esquemas
    assert "version" not in spec["info"]  # trocar de versão não muda o contrato
    assert "schema" in esquemas["Operacao"]["properties"]  # alias, não "schema_"

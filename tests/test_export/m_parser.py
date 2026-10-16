"""Validação de sintaxe do M com o parser oficial da Microsoft (F0.F5).

Chama ``tools/m-parser/check.mjs`` (Node) em lote. Sem Node ou sem
``npm ci`` em ``tools/m-parser``, os testes são pulados localmente; no CI,
``WOLFZ_REQUIRE_M_PARSER=1`` transforma a ausência em falha, para o teste
nunca deixar de rodar em silêncio.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "m-parser"


def parse_m(documents: list[str]) -> list[dict]:
    """Uma entrada por documento: {"ok": True} ou {"ok": False, "error": ...}."""
    node = shutil.which("node")
    missing = None
    if node is None:
        missing = "Node não encontrado no PATH"
    elif not (TOOL / "node_modules" / "@microsoft" / "powerquery-parser").exists():
        missing = f"rode `npm ci --prefix {TOOL}`"
    if missing:
        if os.environ.get("WOLFZ_REQUIRE_M_PARSER") == "1":
            pytest.fail(f"parser de M indisponível: {missing}")
        pytest.skip(f"parser de M indisponível: {missing}")
    result = subprocess.run(
        [node, str(TOOL / "check.mjs")],
        input=json.dumps(documents).encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=120,
    )
    return json.loads(result.stdout)

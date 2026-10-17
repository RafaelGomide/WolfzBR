"""Grava o OpenAPI da API local em ``frontend/src/api/openapi.json`` (F1.H1).

A interface gera os tipos do cliente a partir dele (``npm run api`` roda
este script e depois o ``openapi-typescript``). Fora do modo de
desenvolvimento a API não publica o OpenAPI; aqui ele é tirado direto do
app, sem subir servidor::

    python scripts/gerar_openapi.py            # grava
    python scripts/gerar_openapi.py --check    # só confere (CI)

A versão do pacote fica de fora do arquivo: trocar de versão não muda o
contrato.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from wolfz.api.app import create_app
from wolfz.api.security import Settings
from wolfz.core.workspace import Workspace

DESTINO = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "openapi.json"


def openapi() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(workspace=Workspace(Path(tmp)), port=1, dev=True))
        spec = app.openapi()
    spec["info"].pop("version", None)
    return json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="falha se o arquivo estiver desatualizado")
    args = parser.parse_args(argv)
    texto = openapi()
    atual = DESTINO.read_text(encoding="utf-8") if DESTINO.is_file() else None
    if args.check:
        if atual != texto:
            print(f"{DESTINO} desatualizado: rode python scripts/gerar_openapi.py", file=sys.stderr)
            return 1
        return 0
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_bytes(texto.encode("utf-8"))
    print(f"gravado: {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Hook de build do hatch: o wheel só sai com a interface compilada.

A interface (``frontend/``) é compilada para ``src/wolfz/static/`` com
``npm run build``. Esses arquivos ficam fora do Git, e esquecer o build
publicaria um pacote sem interface. A instalação editável (``uv sync``) não
passa por aqui. Para gerar um wheel sem interface de propósito:
``WOLFZ_SEM_INTERFACE=1``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ConfereInterface(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version != "standard" or os.environ.get("WOLFZ_SEM_INTERFACE") == "1":
            return
        if not (Path(self.root) / "src" / "wolfz" / "static" / "index.html").is_file():
            raise RuntimeError(
                "A interface não foi compilada: rode `npm ci && npm run build` em frontend/ "
                "antes de gerar o wheel (ou WOLFZ_SEM_INTERFACE=1 para gerar sem ela)."
            )

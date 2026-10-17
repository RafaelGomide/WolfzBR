"""Monta o GIF do README a partir dos quadros de ``frontend/scripts/capturar_demo.mjs``.

Precisa do Pillow, que não é dependência do projeto::

    uv run --no-project --with pillow python scripts/montar_gif.py <quadros> docs/demo.gif

O GIF fica abaixo de 1 MB (limite do pre-commit para arquivo versionado):
quadros reduzidos e paleta adaptativa de 64 cores.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

LARGURA = 960
DURACAO_MS = 700
CORES = 64


def main(pasta: Path, destino: Path) -> None:
    arquivos = sorted(pasta.glob("*.png"))
    if not arquivos:
        raise SystemExit(f"nenhum quadro em {pasta}")
    quadros = []
    for arq in arquivos:
        img = Image.open(arq).convert("RGB")
        altura = round(img.height * LARGURA / img.width)
        img = img.resize((LARGURA, altura), Image.Resampling.LANCZOS)
        quadros.append(img.quantize(colors=CORES, method=Image.Quantize.MEDIANCUT))
    destino.parent.mkdir(parents=True, exist_ok=True)
    quadros[0].save(
        destino,
        save_all=True,
        append_images=quadros[1:],
        duration=DURACAO_MS,
        loop=0,
        optimize=True,
    )
    print(f"{destino}: {len(quadros)} quadros, {destino.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

"""Confere o wheel e o sdist antes de publicar (FH.E3).

O wheel precisa levar a interface compilada (``wolfz/static/``), a lista de
municípios do IBGE, os templates do PBIP, as licenças e o comando ``wolfz``,
e não pode levar teste, corpus, frontend nem nada de ``dev/``. O sdist tem as
mesmas regras, com os caminhos em ``src/``. Roda no workflow de release, logo
depois do ``uv build``::

    uv run python scripts/conferir_pacote.py dist/ --versao 1.0.0rc1

Sai com código 1 e a lista do que está errado.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import tarfile
import zipfile
from pathlib import Path

MB = 1024 * 1024
MAX_WHEEL = 20 * MB

# Padrões fnmatch sobre o caminho dentro do pacote.
OBRIGATORIOS_WHEEL = {
    "interface compilada": "wolfz/static/index.html",
    "JavaScript da interface": "wolfz/static/assets/*.js",
    "municípios do IBGE": "wolfz/br/data/municipios.parquet",
    "templates do PBIP": "wolfz/export/pbip/templates/model.tmdl",
    "LICENSE": "*.dist-info/licenses/LICENSE",
    "NOTICE": "*.dist-info/licenses/NOTICE",
}
OBRIGATORIOS_SDIST = {
    "interface compilada": "*/src/wolfz/static/index.html",
    "JavaScript da interface": "*/src/wolfz/static/assets/*.js",
    "municípios do IBGE": "*/src/wolfz/br/data/municipios.parquet",
    "templates do PBIP": "*/src/wolfz/export/pbip/templates/model.tmdl",
    "pyproject.toml": "*/pyproject.toml",
    "hook de build": "*/hatch_build.py",
    "README": "*/README.md",
    "LICENSE": "*/LICENSE",
    "NOTICE": "*/NOTICE",
}
# Nada disso vai para quem instala: dado de teste, código da interface,
# planejamento pessoal, cache do Python.
PROIBIDOS = [
    "tests/*",
    "*/tests/*",
    "*corpus*",
    "frontend/*",
    "*/frontend/*",
    "dev/*",
    "*/dev/*",
    "*/__pycache__/*",
    "*.pyc",
    "*.wolfz/*",
]


def _faltando(nomes: list[str], obrigatorios: dict[str, str]) -> list[str]:
    return [
        f"falta {rotulo} ({padrao})"
        for rotulo, padrao in obrigatorios.items()
        if not any(fnmatch.fnmatch(n, padrao) for n in nomes)
    ]


def _proibidos(nomes: list[str]) -> list[str]:
    achados = sorted({n for n in nomes for p in PROIBIDOS if fnmatch.fnmatch(n, p)})
    return [f"não devia estar no pacote: {n}" for n in achados[:20]] + (
        [f"… e mais {len(achados) - 20}"] if len(achados) > 20 else []
    )


def conferir_wheel(caminho: Path, versao: str | None = None) -> list[str]:
    with zipfile.ZipFile(caminho) as zf:
        nomes = zf.namelist()
        metadados = next((n for n in nomes if n.endswith(".dist-info/METADATA")), None)
        pontos = next((n for n in nomes if n.endswith(".dist-info/entry_points.txt")), None)
        texto_meta = zf.read(metadados).decode("utf-8") if metadados else ""
        texto_pontos = zf.read(pontos).decode("utf-8") if pontos else ""
    erros = _faltando(nomes, OBRIGATORIOS_WHEEL) + _proibidos(nomes)
    if "wolfz = wolfz.cli:app" not in texto_pontos:
        erros.append("falta o comando wolfz em entry_points.txt")
    if versao is not None and f"\nVersion: {versao}\n" not in texto_meta:
        erros.append(f"a versão no METADATA não é {versao}")
    if caminho.stat().st_size > MAX_WHEEL:
        erros.append(f"wheel com {caminho.stat().st_size / MB:.1f} MB (máximo {MAX_WHEEL // MB} MB)")
    return erros


def conferir_sdist(caminho: Path) -> list[str]:
    with tarfile.open(caminho) as tf:
        nomes = tf.getnames()
    # No sdist, o caminho começa pela pasta wolfzbr-<versão>/.
    return _faltando(nomes, OBRIGATORIOS_SDIST) + _proibidos([n.split("/", 1)[-1] for n in nomes])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pasta", type=Path, help="Pasta com o .whl e o .tar.gz (dist/).")
    parser.add_argument("--versao", help="Versão esperada (a da tag, sem o v).")
    args = parser.parse_args(argv)

    wheels = sorted(args.pasta.glob("wolfzbr-*.whl"))
    sdists = sorted(args.pasta.glob("wolfzbr-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"esperado um wheel e um sdist em {args.pasta}; achados {len(wheels)} e {len(sdists)}")
        return 1
    if args.versao and not wheels[0].name.startswith(f"wolfzbr-{args.versao}-"):
        print(f"o wheel {wheels[0].name} não é da versão {args.versao}")
        return 1

    resultados = [
        (wheels[0], conferir_wheel(wheels[0], args.versao)),
        (sdists[0], conferir_sdist(sdists[0])),
    ]
    falhas = 0
    for caminho, erros in resultados:
        tamanho = caminho.stat().st_size / MB
        if erros:
            falhas += 1
            print(f"{caminho.name} ({tamanho:.1f} MB): PROBLEMAS")
            for erro in erros:
                print(f"  - {erro}")
        else:
            print(f"{caminho.name} ({tamanho:.1f} MB): ok")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

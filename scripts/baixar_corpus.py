"""Baixa os arquivos do corpus grandes demais para o Git (F1.B2).

Arquivo público acima de 1 MB não é versionado. A pasta dele em
``tests/corpus/`` vai para o Git com tudo menos o original, e um
``externo.json`` diz de onde baixar:

    {
      "url": "https://exemplo.gov.br/dados/arquivo.zip",
      "sha256": "…hash do arquivo final (depois de extrair do zip, se for o caso)…",
      "arquivo": "original.csv",
      "membro_zip": "202501_CEIS.csv"
    }

``membro_zip`` é opcional: quando a fonte publica um ``.zip``, é o arquivo de
dentro dele que vira o original. O hash protege contra a fonte ter mudado o
arquivo; se mudou, o script para e avisa, em vez de rodar os testes contra
outro conteúdo.

A pasta tem também um ``.gitignore`` com ``original.*``, para o original
baixado nunca ir para o Git (o teste do corpus confere). Os testes pulam a
pasta enquanto o original não foi baixado.

Uso::

    python scripts/baixar_corpus.py            # baixa o que falta
    python scripts/baixar_corpus.py --forcar   # baixa tudo de novo
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "tests" / "corpus"
TIMEOUT = 120


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def baixar(url: str) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": "WolfzBR-corpus/1.0"})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
        return resposta.read()


def externos(corpus: Path = CORPUS) -> list[tuple[Path, dict]]:
    arquivos = sorted(corpus.rglob("externo.json"))
    return [(p.parent, json.loads(p.read_text(encoding="utf-8"))) for p in arquivos]


def obter(pasta: Path, meta: dict, forcar: bool = False) -> str:
    destino = pasta / meta["arquivo"]
    if destino.exists() and not forcar:
        return "já existe"
    dados = baixar(meta["url"])
    if membro := meta.get("membro_zip"):
        with zipfile.ZipFile(io.BytesIO(dados)) as zf:
            dados = zf.read(membro)
    obtido = sha256(dados)
    if obtido != meta["sha256"]:
        raise ValueError(f"hash diferente do esperado ({obtido}); a fonte mudou o arquivo?")
    tmp = destino.with_name(f".{destino.name}.tmp")
    tmp.write_bytes(dados)
    tmp.replace(destino)
    return f"baixado ({len(dados) / 1_048_576:.1f} MB)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forcar", action="store_true", help="Baixa de novo mesmo se já existir.")
    args = parser.parse_args(argv)
    itens = externos()
    if not itens:
        print("Nenhum arquivo externo no corpus (tests/corpus/**/externo.json).")
        return 0
    falhas = 0
    for pasta, meta in itens:
        try:
            status = obter(pasta, meta, args.forcar)
        except Exception as exc:
            status = f"FALHOU: {exc}"
            falhas += 1
        print(f"{pasta.relative_to(CORPUS)}: {status}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

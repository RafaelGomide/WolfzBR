"""Atualiza a lista de municípios do IBGE (F2.C1).

Baixa a lista oficial da API de localidades do IBGE e grava
``src/wolfz/br/data/municipios.parquet``, com:

- ``codigo_ibge``: código de 7 dígitos (com o dígito verificador);
- ``codigo_ibge_6``: os 6 primeiros, como o DATASUS usa;
- ``nome``: nome oficial;
- ``nome_normalizado``: sem acento, minúsculo, sem pontuação (``chave_municipio``);
- ``uf``: sigla da UF.

Atualiza também a data da extração no ``NOTICE``. Rode quando o IBGE criar
ou renomear município (acontece poucas vezes por década)::

    python scripts/atualizar_municipios.py
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import polars as pl

from wolfz.br.constants import UFS
from wolfz.br.municipios import chave_municipio

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "src" / "wolfz" / "br" / "data" / "municipios.parquet"
NOTICE = RAIZ / "NOTICE"
URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
MINIMO = 5500  # o Brasil tem 5.570 municípios (5.571 com Boa Esperança do Norte)


def baixar(url: str = URL) -> list[dict]:
    pedido = urllib.request.Request(url, headers={"User-Agent": "WolfzBR (scripts/atualizar_municipios.py)"})
    with urllib.request.urlopen(pedido, timeout=60) as resposta:
        corpo = resposta.read()
    # A API do IBGE responde em gzip mesmo sem Accept-Encoding.
    if corpo[:2] == b"\x1f\x8b":
        corpo = gzip.decompress(corpo)
    return json.loads(corpo)


def montar(itens: list[dict]) -> pl.DataFrame:
    linhas = []
    for item in itens:
        codigo, nome, uf = str(item["municipio-id"]), item["municipio-nome"], item["UF-sigla"]
        if not re.fullmatch(r"\d{7}", codigo) or uf not in UFS:
            raise ValueError(f"registro inesperado da API do IBGE: {item}")
        linhas.append((codigo, codigo[:6], nome, chave_municipio(nome), uf))
    df = pl.DataFrame(
        linhas,
        schema={k: pl.String for k in ("codigo_ibge", "codigo_ibge_6", "nome", "nome_normalizado", "uf")},
        orient="row",
    ).sort("codigo_ibge")
    if df.height < MINIMO or df["codigo_ibge"].n_unique() != df.height:
        raise ValueError(
            f"a API devolveu {df.height} municípios; esperado pelo menos {MINIMO}, sem repetição"
        )
    return df


def atualizar_notice(hoje: date, total: int) -> None:
    texto = NOTICE.read_text(encoding="utf-8")
    padrao = r"Extraído em \d{4}-\d{2}-\d{2} \(\d+ municípios\)"
    novo = re.sub(padrao, f"Extraído em {hoje} ({total} municípios)", texto)
    NOTICE.write_text(novo, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    df = montar(baixar())
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(DESTINO, compression="zstd", statistics=False)
    atualizar_notice(date.today(), df.height)
    print(f"{df.height} municípios gravados em {DESTINO.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

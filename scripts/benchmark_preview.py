"""Benchmark do preview (F1.F5): latência depois de editar o último passo.

Gera uma grade sintética (500 mil linhas por padrão) no formato do
``raw.parquet``, aplica uma receita de 8 passos e mede:

- **abertura**: o primeiro preview, que grava os checkpoints completos;
- **edição do último passo**: troca o filtro do fim da receita e pede a
  primeira página (o caso do SLO, §12.4: p50 ≤ 300 ms, p95 ≤ 1 s);
- **rolagem**: páginas em posições aleatórias da mesma receita.

Uso::

    python scripts/benchmark_preview.py
    python scripts/benchmark_preview.py --linhas 100000 --repeticoes 20 --json

Sai com código 1 se o caso do SLO estourar o limite.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import polars as pl

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.engine.cache import Checkpoints
from wolfz.core.engine.preview import preview
from wolfz.core.recipe import recipe_from_dict

SLO_P50, SLO_P95 = 0.300, 1.0
UFS = ["ES", "SP", "RJ", "MG", "BA", "PR", "SC", "RS", "GO", "PE"]
MUNICIPIOS = ["Vitória", "Serra", "Vila Velha", "Cariacica", "Linhares", "Colatina", "Guarapari", "Aracruz"]


def grade(linhas: int, semente: int = 0) -> pl.DataFrame:
    """Grade crua como a ingestão grava: tudo texto, cabeçalho na linha 1."""
    rng = random.Random(semente)
    datas = [
        f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(2015, 2025)}" for _ in range(linhas)
    ]
    valores = [
        f"{rng.randint(0, 999_999):,}".replace(",", ".") + f",{rng.randint(0, 99):02d}" for _ in range(linhas)
    ]
    return pl.DataFrame(
        {
            "A": ["Data", *datas],
            "B": ["UF", *(rng.choice(UFS).lower() for _ in range(linhas))],
            "C": ["Município", *(f"  {rng.choice(MUNICIPIOS)} " for _ in range(linhas))],
            "D": ["Valor", *valores],
            "E": ["Descrição", *(f"Item {rng.randint(1, 5000)}" for _ in range(linhas))],
        }
    )


def receita(ultimo: dict) -> object:
    passos = [
        {"op": "select_range", "start": "A1"},
        {"op": "header_rows", "n": 1},
        {"op": "trim", "cols": ["Município", "Descrição"]},
        {"op": "parse_date_br", "cols": ["Data"]},
        {"op": "parse_decimal_br", "cols": ["Valor"]},
        {"op": "normalize_uf", "cols": ["UF"]},
        {"op": "sort", "by": ["Valor"], "descending": True},
        ultimo,
    ]
    return recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "benchmark",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


def _filtro(i: int) -> dict:
    """Último passo editado: alterna o tipo de condição e o valor."""
    uf = UFS[i % len(UFS)]
    if i % 3 == 0:
        return {"op": "filter", "col": "UF", "match": "equals", "value": uf}
    if i % 3 == 1:
        return {"op": "filter", "col": "Valor", "match": "gt", "value": 1000 * (i + 1)}
    return {"op": "filter", "col": "UF", "match": "in", "value": [uf, UFS[(i + 1) % len(UFS)]]}


def _cronometra(fn) -> float:
    inicio = time.perf_counter()
    fn()
    return time.perf_counter() - inicio


def _percentil(amostra: list[float], p: float) -> float:
    ordenada = sorted(amostra)
    return ordenada[min(len(ordenada) - 1, round(p * (len(ordenada) - 1)))]


def medir(linhas: int, repeticoes: int, pasta: Path, usar_cache: bool = True) -> dict:
    raw = pasta / "raw.parquet"
    grade(linhas).write_parquet(raw)
    cache = Checkpoints(pasta / "checkpoints") if usar_cache else None

    abertura = _cronometra(lambda: preview(raw, "bench", receita(_filtro(0)), None, 0, 200, cache))

    edicoes = []
    for i in range(1, repeticoes + 1):
        edicoes.append(
            _cronometra(lambda i=i: preview(raw, "bench", receita(_filtro(i)), None, 0, 200, cache))
        )

    rng = random.Random(1)
    fixa = receita(_filtro(1))
    rolagem = []
    for _ in range(repeticoes):
        offset = rng.randint(0, max(0, linhas // 2))
        rolagem.append(_cronometra(lambda o=offset: preview(raw, "bench", fixa, None, o, 200, cache)))

    def resumo(amostra: list[float]) -> dict:
        return {
            "p50_ms": round(statistics.median(amostra) * 1000, 1),
            "p95_ms": round(_percentil(amostra, 0.95) * 1000, 1),
            "max_ms": round(max(amostra) * 1000, 1),
        }

    resultado = {
        "linhas": linhas,
        "repeticoes": repeticoes,
        "cache": usar_cache,
        "abertura_ms": round(abertura * 1000, 1),
        "edicao_ultimo_passo": resumo(edicoes),
        "rolagem": resumo(rolagem),
    }
    edicao = resultado["edicao_ultimo_passo"]
    resultado["dentro_do_slo"] = edicao["p50_ms"] <= SLO_P50 * 1000 and edicao["p95_ms"] <= SLO_P95 * 1000
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--linhas", type=int, default=500_000)
    parser.add_argument("--repeticoes", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="Saída em JSON.")
    parser.add_argument("--sem-cache", action="store_true", help="Mede sem checkpoints (comparação).")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="wolfz-bench-") as pasta:
        r = medir(args.linhas, args.repeticoes, Path(pasta), usar_cache=not args.sem_cache)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        linhas = f"{r['linhas']:,}".replace(",", ".")
        print(f"{linhas} linhas, {r['repeticoes']} repetições" + ("" if r["cache"] else ", sem cache"))
        print(f"abertura: {r['abertura_ms']:.0f} ms")
        for rotulo, chave in [
            ("editar o último passo", "edicao_ultimo_passo"),
            ("rolagem (página nova)", "rolagem"),
        ]:
            m = r[chave]
            print(f"{rotulo}: p50 {m['p50_ms']:.0f} ms · p95 {m['p95_ms']:.0f} ms · máx {m['max_ms']:.0f} ms")
        veredito = "dentro" if r["dentro_do_slo"] else "FORA"
        print(f"SLO (p50 ≤ 300 ms, p95 ≤ 1 s): {veredito}")
    return 0 if r["dentro_do_slo"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Prepara a validação manual do M no Power BI Desktop (F2.A7).

Para cada arquivo do subconjunto fixo do corpus, grava a consulta
(``<nome>.pq``) e o parâmetro (``<nome>.CaminhoArquivo.pq``, já com o
caminho absoluto do original) e imprime, em Markdown, o que o Power BI tem
de mostrar depois do refresh: contagem de linhas e três valores tirados da
saída do Polars (``wolfz.run``). O roteiro está em ``dev/validacao_m.md``::

    python scripts/validacao_m.py                  # grava em saida/validacao_m/
    python scripts/validacao_m.py --saida C:/temp/m
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

import wolfz
from wolfz.core.recipe import load_recipe
from wolfz.export.m import PARAMETRO, parameter_to_m, recipe_to_m, source_from_file

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "tests" / "corpus"

# Subconjunto fixo: não troque sem anotar no dev/validacao_m.md. Cobre
# .xlsx, .xls, CSV cp1252 e CSV UTF-8 com BOM, grade e cabeçalho, e as
# conversões BR mais usadas.
SUBCONJUNTO = (
    "receita_municipal",
    "erp_totvs_razao",
    "ibge_ipca_serie_historica",
    "convenios_estaduais",
    "anp_glp_2024_s2",
)


def _valor(v: object) -> str:
    return "null" if v is None else str(v).replace("|", "\\|")


def amostras(df: pl.DataFrame) -> list[tuple[int, str, object]]:
    """Três células (linha 1-based, coluna, valor): primeira linha e primeira
    coluna, linha do meio e coluna do meio, última linha e última coluna."""
    if df.is_empty():
        return []
    pontos = [(0, 0), (df.height // 2, df.width // 2), (df.height - 1, df.width - 1)]
    return [(i + 1, df.columns[j], df[i, j]) for i, j in pontos]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=RAIZ / "saida" / "validacao_m")
    args = parser.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"WolfzBR {wolfz.__version__} · arquivos em {args.saida}\n")
    print("| Arquivo | Linhas | Linha | Coluna | Valor no Polars |")
    print("|---|---:|---:|---|---|")
    for nome in SUBCONJUNTO:
        pasta = CORPUS / nome
        receita = load_recipe(pasta / "receita_esperada.wolfz.json")
        original = next(pasta.glob("original.*"))
        (args.saida / f"{nome}.pq").write_text(
            recipe_to_m(receita, source_from_file(receita, original)), encoding="utf-8"
        )
        (args.saida / f"{nome}.{PARAMETRO}.pq").write_text(
            parameter_to_m(str(original.resolve()), receita.name), encoding="utf-8"
        )
        df = wolfz.run(receita, original)
        for k, (linha, coluna, valor) in enumerate(amostras(df)):
            primeira = k == 0
            arquivo = f"`{nome}` ({original.suffix})" if primeira else ""
            linhas = str(df.height) if primeira else ""
            print(f"| {arquivo} | {linhas} | {linha} | {_valor(coluna)} | {_valor(valor)} |")


if __name__ == "__main__":
    main()

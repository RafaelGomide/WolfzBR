"""Prepara a validação manual do PBIP no Power BI Desktop (F3.B7).

Para cada arquivo do subconjunto, grava um projeto PBIP completo
(``<nome>.pbip`` com o modelo e o relatório, o parâmetro ``CaminhoArquivo``
já com o caminho absoluto do original) e imprime, em Markdown, o que o Power
BI tem de mostrar depois do refresh: linhas, a soma de uma métrica e o
intervalo de datas. O roteiro está em ``dev/validacao_pbip.md``::

    python scripts/validacao_pbip.py                 # grava em saida/validacao_pbip/
    python scripts/validacao_pbip.py --saida C:/temp/pbip

O último caso é o "mês seguinte": o projeto é gerado com o arquivo do
``anp_glp`` e o roteiro troca o ``CaminhoArquivo`` pelo do
``anp_glp_2024_s2``, que tem outras linhas com a mesma receita.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

import wolfz
from wolfz.core.engine import read_input
from wolfz.core.recipe import load_recipe
from wolfz.export.dados import gravar_juntos
from wolfz.export.depara import ARQUIVO_DEPARA, depara_municipios, gravar_depara
from wolfz.export.m import source_from_file
from wolfz.export.pbip import (
    OpcoesPbip,
    colunas,
    escrever_arquivo,
    escrever_pasta,
    parametros_pbip,
    projeto_pbip,
)
from wolfz.ops.municipio import PARAMETRO_DEPARA

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "tests" / "corpus"

# (nome, receita, original, calendário), relativos a tests/corpus. Não
# troque sem anotar no dev/validacao_pbip.md.
SUBCONJUNTO = (
    (
        "receita_municipal",
        "receita_municipal/receita_esperada.wolfz.json",
        "receita_municipal/original.xlsx",
        False,
    ),
    ("erp_totvs_razao", "erp_totvs_razao/receita_esperada.wolfz.json", "erp_totvs_razao/original.xlsx", True),
    (
        "convenios_estaduais",
        "convenios_estaduais/receita_esperada.wolfz.json",
        "convenios_estaduais/original.csv",
        True,
    ),
    (
        "municipios_digitados",
        "_fixtures/municipios_digitados.wolfz.json",
        "_fixtures/municipios_digitados.csv",
        False,
    ),
    ("anp_glp", "anp_glp/receita_esperada.wolfz.json", "anp_glp/original.csv", False),
)
# O arquivo do "mês seguinte" para o anp_glp.
MES_SEGUINTE = CORPUS / "anp_glp_2024_s2" / "original.csv"


def _valor(v: object) -> str:
    return "null" if v is None else str(v).replace("|", "\\|")


def resumo(df: pl.DataFrame, receita) -> list[str]:
    """Linhas, soma da primeira métrica e intervalo da primeira data."""
    itens = [f"{df.height} linhas"]
    metrica = next((c.nome for c in colunas(df.schema, receita) if c.metrica), None)
    if metrica:
        itens.append(f"Total {metrica} = {df[metrica].sum():.2f}")
    data = next((n for n, t in df.schema.items() if t == pl.Date), None)
    if data:
        itens.append(f"{data} de {df[data].min()} a {df[data].max()}")
    return itens


def preparar(nome: str, receita_path: Path, original: Path, calendario: bool, saida: Path) -> pl.DataFrame:
    receita = load_recipe(receita_path)
    df = wolfz.run(receita, original)
    extras = {}
    escritas = {}
    depara = depara_municipios(receita, read_input(receita, original).lazy())
    if depara is not None:
        caminho = saida / f"{nome}.{ARQUIVO_DEPARA}"
        extras[PARAMETRO_DEPARA] = str(caminho.resolve())
        escritas[caminho] = lambda p: gravar_depara(depara, p)
    arquivos = projeto_pbip(
        nome,
        receita,
        df.schema,
        source_from_file(receita, original),
        parametros_pbip(receita, str(original.resolve()), extras),
        OpcoesPbip(calendario=calendario),
    )
    escritas[saida / f"{nome}.pbip"] = lambda p: escrever_arquivo(arquivos[f"{nome}.pbip"], p)
    for pasta in (f"{nome}.SemanticModel", f"{nome}.Report"):
        escritas[saida / pasta] = lambda p, pasta=pasta: escrever_pasta(arquivos, pasta, p)
    gravar_juntos(escritas)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=RAIZ / "saida" / "validacao_pbip")
    args = parser.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"WolfzBR {wolfz.__version__} · projetos em {args.saida}\n")
    print("| Projeto | Calendário | O Power BI tem de mostrar |")
    print("|---|---|---|")
    for nome, receita, original, calendario in SUBCONJUNTO:
        df = preparar(nome, CORPUS / receita, CORPUS / original, calendario, args.saida)
        esperado = "; ".join(resumo(df, load_recipe(CORPUS / receita)))
        print(f"| `{nome}.pbip` | {'sim' if calendario else 'não'} | {_valor(esperado)} |")
    receita = load_recipe(CORPUS / "anp_glp" / "receita_esperada.wolfz.json")
    seguinte = wolfz.run(receita, MES_SEGUINTE)
    print(
        f"| `anp_glp.pbip` com `CaminhoArquivo` = `{MES_SEGUINTE.resolve()}` | não | "
        f"{_valor('; '.join(resumo(seguinte, receita)))} |"
    )


if __name__ == "__main__":
    main()

"""Prepara a validação manual do M no Power BI Desktop (F2.A7).

Para cada arquivo do subconjunto fixo do corpus, grava a consulta
(``<nome>.pq``) e o parâmetro (``<nome>.CaminhoArquivo.pq``, já com o
caminho absoluto do original) e imprime, em Markdown, o que o Power BI tem
de mostrar depois do refresh: contagem de linhas e três valores tirados da
saída do Polars (``wolfz.run``). O roteiro está em ``dev/validacao_m.md``::

    python scripts/validacao_m.py                  # grava em saida/validacao_m/
    python scripts/validacao_m.py --saida C:/temp/m

Além do subconjunto fixo, o complementar cobre as traduções para M que
entraram depois dele (sinais do IBGE, mojibake, CPF ou CNPJ e o de-para de
municípios). Receita com ``normalize_municipio`` leva também o
``depara_municipios.csv`` e o parâmetro ``CaminhoDeparaMunicipios``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

import wolfz
from wolfz.core.engine import read_input
from wolfz.core.recipe import load_recipe
from wolfz.export.depara import ARQUIVO_DEPARA, depara_municipios, gravar_depara
from wolfz.export.m import PARAMETRO, parameter_to_m, recipe_to_m, source_from_file
from wolfz.ops.municipio import PARAMETRO_DEPARA

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

# Complementar (0.6.0): as traduções para M das operações novas.
# (nome, receita, original), relativos a tests/corpus.
COMPLEMENTAR = (
    (
        "sidra_pam_area",
        "sidra_pam_area/receita_esperada.wolfz.json",
        "sidra_pam_area/original.xlsx",
        ("area_plantada_2022", "quantidade_produzida_2022", "area_plantada_2023"),
    ),
    (
        "cadastro_mojibake",
        "cadastro_mojibake/receita_esperada.wolfz.json",
        "cadastro_mojibake/original.csv",
        ("nome", "municipio", "bairro"),
    ),
    (
        "ceis_sancoes",
        "ceis_sancoes/receita_esperada.wolfz.json",
        "ceis_sancoes/original.csv",
        ("cpf_cnpj", "cpf_cnpj", "cpf_cnpj"),
    ),
    (
        "municipios_digitados",
        "_fixtures/municipios_digitados.wolfz.json",
        "_fixtures/municipios_digitados.csv",
        ("municipio_codigo_ibge", "municipio_nome_ibge", "municipio_status"),
    ),
)


def _valor(v: object) -> str:
    return "null" if v is None else str(v).replace("|", "\\|")


def amostras(df: pl.DataFrame, colunas: tuple[str, ...] = ()) -> list[tuple[int, str, object]]:
    """Três células (linha 1-based, coluna, valor): primeira linha, linha do
    meio e última linha. As colunas são a primeira, a do meio e a última,
    ou as ``colunas`` pedidas (as que a operação nova produz)."""
    if df.is_empty():
        return []
    linhas = (0, df.height // 2, df.height - 1)
    nomes = colunas or (df.columns[0], df.columns[df.width // 2], df.columns[-1])
    return [(i + 1, c, df[i, c]) for i, c in zip(linhas, nomes, strict=True)]


def casos() -> list[tuple[str, Path, Path, tuple[str, ...]]]:
    fixos = [
        (nome, CORPUS / nome / "receita_esperada.wolfz.json", next((CORPUS / nome).glob("original.*")), ())
        for nome in SUBCONJUNTO
    ]
    return fixos + [(n, CORPUS / r, CORPUS / o, c) for n, r, o, c in COMPLEMENTAR]


def preparar(nome: str, receita_path: Path, original: Path, saida: Path) -> pl.DataFrame:
    """Grava a consulta, os parâmetros e o de-para (se houver) e devolve a
    saída do Polars."""
    receita = load_recipe(receita_path)
    (saida / f"{nome}.pq").write_text(
        recipe_to_m(receita, source_from_file(receita, original)), encoding="utf-8"
    )
    (saida / f"{nome}.{PARAMETRO}.pq").write_text(
        parameter_to_m(str(original.resolve()), receita.name), encoding="utf-8"
    )
    depara = depara_municipios(receita, read_input(receita, original).lazy())
    if depara is not None:
        caminho = saida / f"{nome}.{ARQUIVO_DEPARA}"
        gravar_depara(depara, caminho)
        (saida / f"{nome}.{PARAMETRO_DEPARA}.pq").write_text(
            parameter_to_m(str(caminho.resolve()), receita.name, PARAMETRO_DEPARA), encoding="utf-8"
        )
    return wolfz.run(receita, original)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=RAIZ / "saida" / "validacao_m")
    args = parser.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"WolfzBR {wolfz.__version__} · arquivos em {args.saida}\n")
    print("| Arquivo | Linhas | Linha | Coluna | Valor no Polars |")
    print("|---|---:|---:|---|---|")
    for nome, receita, original, colunas in casos():
        if nome == COMPLEMENTAR[0][0]:
            print("| **Complementar** | | | | |")
        df = preparar(nome, receita, original, args.saida)
        for k, (linha, coluna, valor) in enumerate(amostras(df, colunas)):
            primeira = k == 0
            arquivo = f"`{nome}` ({original.suffix})" if primeira else ""
            linhas = str(df.height) if primeira else ""
            print(f"| {arquivo} | {linhas} | {linha} | {_valor(coluna)} | {_valor(valor)} |")


if __name__ == "__main__":
    main()

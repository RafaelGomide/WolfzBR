"""Métricas por linha (F1.C1): quanto da linha está preenchido, quanto é
número e quanto é texto, se tem negrito e se tem célula mesclada.

As classes de valor são calculadas de forma vetorizada no Polars, para
caber em planilhas de centenas de milhares de linhas. Onde o arquivo diz o
tipo da célula (``structure.json``, nas linhas amostradas), ele só promove
a célula a valor (número ou data gravados como tal). Texto gravado como
texto não rebaixa nada: exportação de ERP grava tudo como texto, e o .xls
do IBGE grava códigos e sinais ('-', 'X') como texto.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from wolfz.core.ingest.cells import CellType, column_index
from wolfz.core.ingest.structure import SheetStructure

VAZIO, VALOR, TEXTO = 0, 1, 2

# "Valor" é tudo que ocupa o lugar de um número numa tabela: número em
# qualquer formato brasileiro, moeda, percentual, data, os sinais do IBGE e
# os erros do Excel. O resto é texto.
_VALOR = "|".join(
    [
        r"^[-+(]?\s*(R\$\s*)?-?\d+([.,]\d+)?([eE][-+]?\d+)?\s*%?\)?-?\s*[DCdc]?$",  # 12 / 1,5 / 1e+20 / 10%
        r"^[-+(]?\s*(R\$\s*)?-?\d{1,3}([. ]\d{3})+(,\d+)?\)?-?\s*[DCdc]?$",  # 1.234,56 / 95 626 753
        r"^R\$\s*-?$",  # 'R$ -' (zero no formato contábil)
        r"^\d{1,2}[/.]\d{1,2}[/.]\d{2,4}$",  # 31/12/2024, 31.12.2024
        r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$",  # ISO
        r"^\d{6,8}$",  # AAAAMMDD, DDMMAAAA
        r"^(-|--|\.\.|\.\.\.|[Xx])$",  # sinais do IBGE
        r"^#(N/[AD]|DIV/0!|VALUE!|VALOR!|REF!|NAME\?|NOME\?|NUM!|NÚM!|NULL!|NULO!)$",
    ]
)

_TIPO_ARQUIVO = {
    CellType.NUMBER: VALOR,
    CellType.DATE: VALOR,
    CellType.BOOL: VALOR,
    CellType.ERROR: VALOR,
}


@dataclass(frozen=True)
class RowMetrics:
    """Métricas de uma linha da grade (posição 0-based)."""

    row: int
    filled: int
    values: int  # células com número, data, sinal etc.
    texts: int
    bold: bool
    merged: bool
    first_col: int | None  # posição absoluta da primeira célula preenchida
    last_col: int | None

    @property
    def filled_pct(self) -> float:
        return 0.0 if self.width == 0 else self.filled / self.width

    @property
    def value_pct(self) -> float:
        return self.values / self.filled if self.filled else 0.0

    @property
    def text_pct(self) -> float:
        return self.texts / self.filled if self.filled else 0.0

    width: int = 0


def classify(df: pl.DataFrame, structure: SheetStructure | None = None) -> pl.DataFrame:
    """Grade do mesmo formato do ``raw``, com 0 (vazio), 1 (valor) ou 2
    (texto) em cada célula."""
    if df.width == 0:
        return df
    exprs = []
    for c in df.columns:
        s = pl.col(c).str.strip_chars()
        exprs.append(
            pl.when(s.is_null() | (s == ""))
            .then(pl.lit(VAZIO))
            .when(s.str.contains(_VALOR))
            .then(pl.lit(VALOR))
            .otherwise(pl.lit(TEXTO))
            .cast(pl.Int8)
            .alias(c)
        )
    kinds = df.select(exprs)
    if structure is not None and structure.types:
        offset = column_index(df.columns[0])
        updates: dict[str, dict[int, int]] = {}
        for (r, c), t in structure.types.items():
            j = c - offset
            if 0 <= j < df.width and r < df.height and (k := _TIPO_ARQUIVO.get(t)) is not None:
                updates.setdefault(df.columns[j], {})[r] = k
        for col, por_linha in updates.items():
            serie = kinds[col].to_list()
            for r, k in por_linha.items():
                if serie[r] != VAZIO:
                    serie[r] = k
            kinds = kinds.with_columns(pl.Series(col, serie, dtype=pl.Int8))
    return kinds


def row_metrics(df: pl.DataFrame, structure: SheetStructure | None = None) -> list[RowMetrics]:
    """Métricas de cada linha da grade."""
    if df.width == 0 or df.height == 0:
        return []
    kinds = classify(df, structure)
    offset = column_index(df.columns[0])
    cols = kinds.columns
    resumo = kinds.select(
        pl.sum_horizontal(pl.col(c) != VAZIO for c in cols).alias("filled"),
        pl.sum_horizontal(pl.col(c) == VALOR for c in cols).alias("values"),
        pl.sum_horizontal(pl.col(c) == TEXTO for c in cols).alias("texts"),
        pl.concat_list([pl.when(pl.col(c) != VAZIO).then(pl.lit(j)) for j, c in enumerate(cols)])
        .list.drop_nulls()
        .alias("posicoes"),
    )
    bold = {r for r, _ in structure.bold} if structure else set()
    merged = set()
    if structure:
        for m in structure.merged:
            merged.update(range(m.first_row, m.last_row + 1))
    linhas = []
    for r, (filled, values, texts, posicoes) in enumerate(resumo.iter_rows()):
        linhas.append(
            RowMetrics(
                row=r,
                filled=filled,
                values=values,
                texts=texts,
                bold=r in bold,
                merged=r in merged,
                first_col=offset + posicoes[0] if posicoes else None,
                last_col=offset + posicoes[-1] if posicoes else None,
                width=df.width,
            )
        )
    return linhas

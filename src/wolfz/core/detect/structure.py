"""Detecção de estrutura v1 (F1.C2–F1.C7).

1. **Região** (C2): linhas "densas" são as que têm pelo menos metade das
   colunas típicas da tabela preenchidas. A região é o maior bloco de linhas
   densas consecutivas. Até duas linhas esparsas não vazias (seção, saldo
   anterior) e uma linha vazia isolada (separando grupos) não quebram o
   bloco.
2. **Cabeçalho** (C3): colunas em que a maioria das células é valor
   (número, data, sinal) são colunas "de valor". As primeiras linhas do
   bloco que têm texto nessas colunas são cabeçalho; vale a última delas
   (cabeçalho de uma linha; multinível fica para a F2.D). Se o bloco começa
   direto nos dados, o cabeçalho é a linha imediatamente acima, se ela for
   majoritariamente texto. Tabela só de texto: a primeira linha do bloco.
3. **Totais** (C4): linha cujo rótulo começa com "total", "subtotal" ou
   "soma", ou termina em "- total"; ou linha em negrito numa região em que
   o negrito é raro.
4. **Título e notas** (C5): linhas de uma célula só acima do cabeçalho e
   abaixo da região viram metadados.
5. **Mesclagem vertical** (C6): coluna com células mescladas na vertical
   dentro dos dados sugere ``fill_down``.
6. **Passos** (C7): ``Detection.to_steps()`` devolve ``select_range``,
   ``header_rows``, ``drop_rows_where`` e ``fill_down`` para a receita
   inicial. A detecção não transforma nada.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from wolfz.core.detect.metrics import TEXTO, VALOR, RowMetrics, classify, row_metrics
from wolfz.core.ingest.cells import column_index, column_letter, to_a1
from wolfz.core.ingest.structure import SheetStructure

TOTAL = r"(?i)^\s*(sub-?\s*)?total(\b|$)|^\s*soma\b|-\s*total\s*$"
MAX_SECAO = 2  # linhas de seção seguidas que não quebram a região
DOMINANCIA = 0.6  # fração de valores para a coluna ser "de valor"
ANO = re.compile(r"(19|20)\d{2}")
NEGRITO_RARO = 0.4  # negrito em até 40% das linhas de dados marca total


@dataclass
class Detection:
    """Estrutura detectada. Linhas e colunas 0-based e absolutas (coluna 0
    é a A); ``to_dict`` converte para a numeração do Excel."""

    first_row: int  # primeira linha de dados
    last_row: int  # última linha da região (inclui totais no fim)
    first_col: int
    last_col: int
    header_row: int | None = None
    totals: list[int] = field(default_factory=list)
    fill_down: list[int] = field(default_factory=list)
    title: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict)  # coluna -> rótulo do cabeçalho
    total_cells: dict[int, tuple[int, str]] = field(default_factory=dict)  # linha -> (coluna, rótulo)

    @property
    def top_row(self) -> int:
        return self.header_row if self.header_row is not None else self.first_row

    def label(self, col: int) -> str:
        return self.labels.get(col) or column_letter(col)

    def to_dict(self) -> dict[str, Any]:
        """Formato do ``estrutura_esperada.json`` do corpus (linhas do Excel)."""
        cab = None if self.header_row is None else [self.header_row + 1, self.header_row + 1]
        return {
            "cabecalho": cab,
            "dados": [self.first_row + 1, self.last_row + 1],
            "colunas": [column_letter(self.first_col), column_letter(self.last_col)],
            "totais": [r + 1 for r in self.totals],
            "fill_down": [column_letter(c) for c in self.fill_down],
            "titulo": self.title,
            "notas": self.notes,
        }

    def to_steps(self) -> list[dict[str, Any]]:
        """Passos da receita inicial, sem ``id`` (quem monta a receita numera)."""
        steps: list[dict[str, Any]] = [
            {
                "op": "select_range",
                "start": to_a1(self.top_row, self.first_col),
                "end": to_a1(self.last_row, self.last_col),
            }
        ]
        if self.header_row is not None:
            steps.append({"op": "header_rows", "n": 1})
        por_coluna: dict[int, list[str]] = {}
        for r in self.totals:
            col, valor = self.total_cells[r]
            por_coluna.setdefault(col, [])
            if valor not in por_coluna[col]:
                por_coluna[col].append(valor)
        for col, valores in por_coluna.items():
            steps.append({"op": "drop_rows_where", "col": self.label(col), "match": "in", "value": valores})
        if self.fill_down:
            steps.append({"op": "fill_down", "cols": [self.label(c) for c in self.fill_down]})
        return steps


def _largura_tipica(metrics: list[RowMetrics]) -> int:
    contagem = Counter(m.filled for m in metrics if m.filled >= 2)
    if not contagem:
        return 1
    return max(contagem, key=lambda n: (contagem[n], n))


def _blocos(densa: list[bool], metrics: list[RowMetrics]) -> list[tuple[int, int]]:
    """Blocos de linhas densas. Não separam dois blocos: até ``MAX_SECAO``
    linhas esparsas não vazias (seção, saldo anterior) ou uma única linha
    vazia (separando grupos)."""
    blocos: list[tuple[int, int]] = []
    r, n = 0, len(densa)
    while r < n:
        if not densa[r]:
            r += 1
            continue
        inicio = r
        while r < n and densa[r]:
            r += 1
        blocos.append((inicio, r - 1))
    unidos: list[tuple[int, int]] = []
    for bloco in blocos:
        if unidos:
            a, b = unidos[-1]
            vao = range(b + 1, bloco[0])
            secao = len(vao) <= MAX_SECAO and all(metrics[i].filled >= 1 for i in vao)
            uma_vazia = len(vao) == 1 and metrics[vao[0]].filled == 0
            if secao or uma_vazia:
                unidos[-1] = (a, bloco[1])
                continue
        unidos.append(bloco)
    return unidos


def _colunas_de_valor(kinds: pl.DataFrame, a: int, b: int) -> set[str]:
    trecho = kinds.slice(a, b - a + 1)
    colunas = set()
    for c in trecho.columns:
        s = trecho[c]
        preenchidas = (s != 0).sum()
        if preenchidas >= 2 and (s == VALOR).sum() / preenchidas >= DOMINANCIA:
            colunas.add(c)
    return colunas


def _ano(v: object) -> bool:
    return v is not None and bool(ANO.fullmatch(str(v).strip()))


def _parece_cabecalho(df: pl.DataFrame, kinds: pl.DataFrame, r: int, de_valor: set[str]) -> bool:
    """Maioria de texto nas colunas de valor. Ano ('2019') conta como
    rótulo quando a célula de baixo não é ano: é o cabeçalho de série
    histórica (TabNet, SIDRA), não um dado."""
    linha = kinds.row(r, named=True)
    valores = df.row(r, named=True)
    abaixo = df.row(r + 1, named=True) if r + 1 < df.height else {}
    marcadas = [c for c in de_valor if linha[c] != 0]
    rotulos = sum(linha[c] == TEXTO or (_ano(valores[c]) and not _ano(abaixo.get(c))) for c in marcadas)
    return bool(marcadas) and rotulos / len(marcadas) > 0.5


def detect_structure(df: pl.DataFrame, structure: SheetStructure | None = None) -> Detection | None:
    """Detecta a tabela principal de uma aba (grade do ``raw``: colunas com
    nome de letra, linha i = linha i + 1 da planilha). ``None`` se a aba não
    tem nenhuma linha preenchida."""
    metrics = row_metrics(df, structure)
    if not any(m.filled for m in metrics):
        return None
    kinds = classify(df, structure)
    offset = column_index(df.columns[0])

    largura = _largura_tipica(metrics)
    limiar = max(2, math.ceil(largura / 2)) if largura >= 2 else 1
    densa = [m.filled >= limiar for m in metrics]
    blocos = _blocos(densa, metrics)
    if not blocos:
        return None
    a, b = max(blocos, key=lambda bl: (bl[1] - bl[0], -bl[0]))

    # Cabeçalho
    de_valor = _colunas_de_valor(kinds, a, b)
    header: int | None
    inicio = a
    if not de_valor:
        header, inicio = (a, a + 1) if b > a else (None, a)
    else:
        r = a
        while r <= b and _parece_cabecalho(df, kinds, r, de_valor):
            r += 1
        if r > a:
            header, inicio = r - 1, r
        elif a > 0 and metrics[a - 1].filled and metrics[a - 1].text_pct > 0.5:
            header = a - 1
        else:
            header = None
    if inicio > b:  # o bloco era todo cabeçalho
        inicio = b

    topo = header if header is not None else inicio
    regiao = metrics[topo : b + 1]
    first_col = min(m.first_col for m in regiao if m.first_col is not None)
    last_col = max(m.last_col for m in regiao if m.last_col is not None)
    det = Detection(inicio, b, first_col, last_col, header)

    if header is not None:
        valores = df.row(header)
        for j, v in enumerate(valores):
            if v is not None and str(v).strip():
                det.labels[offset + j] = " ".join(str(v).split())

    _totais(det, df, metrics, structure, offset)
    _metadados(det, df, metrics)
    if structure is not None:
        cols = sorted(
            {
                m.first_col
                for m in structure.merged
                if m.first_col == m.last_col
                and m.last_row > m.first_row
                and m.first_row >= det.first_row
                and m.first_row <= det.last_row
                and det.first_col <= m.first_col <= det.last_col
            }
        )
        det.fill_down = cols
    return det


def _primeiro_texto(df: pl.DataFrame, r: int, det: Detection, offset: int) -> tuple[int, str] | None:
    linha = df.row(r)
    for col in range(det.first_col, det.last_col + 1):
        v = linha[col - offset]
        if v is not None and str(v).strip():
            return col, str(v).strip()
    return None


def _totais(
    det: Detection, df: pl.DataFrame, metrics: list[RowMetrics], structure: SheetStructure | None, offset: int
) -> None:
    # Palavra-chave nas três primeiras colunas da região. A célula que casou
    # é a que o passo drop_rows_where usa.
    celulas: dict[int, tuple[int, str]] = {}
    rotulos = [column_letter(c) for c in range(det.first_col, min(det.first_col + 3, det.last_col + 1))]
    rotulos = [c for c in rotulos if c in df.columns]
    if rotulos:
        trecho = df.slice(det.first_row, det.last_row - det.first_row + 1).select(rotulos)
        for c in rotulos:
            casa = trecho[c].str.contains(TOTAL).fill_null(False)
            for i in casa.arg_true().to_list():
                celulas.setdefault(det.first_row + i, (column_index(c), str(trecho[c][i]).strip()))

    # Negrito: só conta se for raro nas linhas de dados que a estrutura leu.
    if structure is not None and structure.formatting:
        amostradas = set(structure.sampled_row_numbers(df.height))
        dados = [r for r in range(det.first_row, det.last_row + 1) if r in amostradas]
        negrito = [r for r in dados if metrics[r].bold]
        if dados and len(negrito) / len(dados) <= NEGRITO_RARO:
            for r in negrito:
                if r not in celulas and (celula := _primeiro_texto(df, r, det, offset)) is not None:
                    celulas[r] = celula

    det.totals = sorted(celulas)
    det.total_cells = {r: celulas[r] for r in det.totals}


def _metadados(det: Detection, df: pl.DataFrame, metrics: list[RowMetrics]) -> None:
    def texto(r: int) -> str | None:
        valores = [v for v in df.row(r) if v is not None and str(v).strip()]
        return " ".join(str(valores[0]).split()) if len(valores) == 1 else None

    for r in range(0, det.top_row):
        if (t := texto(r)) is not None:
            det.title.append(t)
    for r in range(det.last_row + 1, len(metrics)):
        if metrics[r].filled >= 2:
            break
        if (t := texto(r)) is not None:
            det.notes.append(t)

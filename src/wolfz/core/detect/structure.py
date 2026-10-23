"""Detecção de estrutura (v1: F1.C2–F1.C7; v2: F2.D1–F2.D3).

1. **Região** (C2): linhas "densas" são as que têm pelo menos metade das
   colunas típicas da tabela preenchidas. A região é o maior bloco de linhas
   densas consecutivas. Até duas linhas esparsas não vazias (seção, saldo
   anterior) e uma linha vazia isolada (separando grupos) não quebram o
   bloco.
2. **Cabeçalho** (C3): colunas em que a maioria das células é valor
   (número, data, sinal) são colunas "de valor". As primeiras linhas do
   bloco que têm texto nessas colunas são cabeçalho. Se o bloco começa
   direto nos dados, o cabeçalho é a linha imediatamente acima, se ela for
   majoritariamente texto. Tabela só de texto: a primeira linha do bloco.
3. **Cabeçalho multinível** (D1): acima do cabeçalho, sobe enquanto a
   linha tiver dois ou mais rótulos e algum deles estiver sobre uma célula
   vazia que tem rótulo embaixo ('Janeiro' mesclado sobre 'Masculino' e
   'Feminino'). O passo proposto é ``header_rows`` com ``n`` níveis e
   ``separator="_"``: preenche para a direita e junta ('Janeiro_Masculino').
4. **Totais** (C4 e D2): linha cujo rótulo começa com "total", "subtotal"
   ou "soma", ou termina em "- total"; linha em negrito numa região em que o
   negrito é raro; ou linha cujo valor é a soma das linhas de baixo até o
   próximo subtotal (como o IBGE publica: 'Região Norte' antes dos estados)
   ou das de cima desde o subtotal anterior. O total geral é a soma dos
   subtotais ('Brasil' = soma das regiões).
5. **Título e notas** (C5): linhas de uma célula só acima do cabeçalho e
   abaixo da região viram metadados.
6. **Mesclagem vertical** (C6): coluna com células mescladas na vertical
   dentro dos dados sugere ``fill_down``.
7. **Várias tabelas** (D3, ``detect_tables``): a aba é dividida em zonas
   separadas por duas ou mais linhas vazias, ou por uma coluna vazia quando
   os dois lados têm pelo menos duas colunas (tabelas lado a lado), e cada
   zona é detectada à parte. ``detect_structure`` devolve a principal: a de
   mais linhas de dados, a primeira em caso de empate.
8. **Passos** (C7): ``Detection.to_steps()`` devolve ``select_range``,
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

from wolfz.br.numeros import decimal_provavel, parse_number_br
from wolfz.core.detect.metrics import TEXTO, VALOR, RowMetrics, classify, row_metrics
from wolfz.core.ingest.cells import column_index, column_letter, to_a1
from wolfz.core.ingest.structure import SheetStructure
from wolfz.core.text import strip_footnote_marks

TOTAL = r"(?i)^\s*(sub-?\s*)?total(\b|$)|^\s*soma\b|-\s*total\s*$"
MAX_SECAO = 2  # linhas de seção seguidas que não quebram a região
DOMINANCIA = 0.6  # fração de valores para a coluna ser "de valor"
ANO = re.compile(r"(19|20)\d{2}")
DATA_ISO = re.compile(r"(19|20)\d{2}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?")
NEGRITO_RARO = 0.4  # negrito em até 40% das linhas de dados marca total
MAX_NIVEIS = 4  # níveis de cabeçalho
JUNTAR_NIVEIS = "_"
VAZIAS_ENTRE_TABELAS = 2  # linhas vazias que separam duas tabelas empilhadas
MIN_COLUNAS_LADO = 2  # colunas de cada lado para separar tabelas lado a lado


@dataclass
class Detection:
    """Estrutura detectada. Linhas e colunas 0-based e absolutas (coluna 0
    é a A); ``to_dict`` converte para a numeração do Excel."""

    first_row: int  # primeira linha de dados
    last_row: int  # última linha da região (inclui totais no fim)
    first_col: int
    last_col: int
    header_row: int | None = None  # última linha do cabeçalho
    header_top: int | None = None  # primeira linha do cabeçalho (multinível)
    totals: list[int] = field(default_factory=list)
    fill_down: list[int] = field(default_factory=list)
    title: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict)  # coluna -> nome depois do header_rows
    total_cells: dict[int, tuple[int, str]] = field(default_factory=dict)  # linha -> (coluna, rótulo)

    @property
    def top_row(self) -> int:
        if self.header_top is not None:
            return self.header_top
        return self.header_row if self.header_row is not None else self.first_row

    @property
    def header_levels(self) -> int:
        if self.header_row is None:
            return 0
        return self.header_row - (self.header_top if self.header_top is not None else self.header_row) + 1

    def label(self, col: int) -> str:
        return self.labels.get(col) or column_letter(col)

    def to_dict(self) -> dict[str, Any]:
        """Formato do ``estrutura_esperada.json`` do corpus (linhas do Excel)."""
        cab = None if self.header_row is None else [self.top_row + 1, self.header_row + 1]
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
        if self.header_levels == 1:
            steps.append({"op": "header_rows", "n": 1})
        elif self.header_levels > 1:
            steps.append({"op": "header_rows", "n": self.header_levels, "separator": JUNTAR_NIVEIS})
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


def _periodo(v: object) -> bool:
    """Ano ('2019') ou data ISO, com ou sem hora ('1997-01-01 00:00:00',
    que é como uma célula de data do Excel chega à grade)."""
    return v is not None and (_ano(v) or bool(DATA_ISO.fullmatch(str(v).strip())))


def _parece_cabecalho(df: pl.DataFrame, kinds: pl.DataFrame, r: int, de_valor: set[str]) -> bool:
    """Maioria de texto nas colunas de valor. Período (ano ou data) conta
    como rótulo quando a célula de baixo não é período: é o cabeçalho de
    série histórica com anos ou meses nas colunas (TabNet, SIDRA, séries
    do Tesouro), não um dado."""
    linha = kinds.row(r, named=True)
    valores = df.row(r, named=True)
    abaixo = df.row(r + 1, named=True) if r + 1 < df.height else {}
    marcadas = [c for c in de_valor if linha[c] != 0]
    rotulos = sum(
        linha[c] == TEXTO or (_periodo(valores[c]) and not _periodo(abaixo.get(c))) for c in marcadas
    )
    return bool(marcadas) and rotulos / len(marcadas) > 0.5


def _preenchida(v: object) -> bool:
    return v is not None and bool(str(v).strip())


def _nivel_de_cabecalho(df: pl.DataFrame, metrics: list[RowMetrics], r: int, abaixo: int) -> bool:
    """A linha ``r`` é um nível de cabeçalho acima de ``abaixo``: dois ou
    mais rótulos, a maioria texto, e algum deles "cobre" uma célula vazia
    que tem rótulo na linha de baixo (o pai mesclado sobre os filhos)."""
    m = metrics[r]
    if m.filled < 2 or m.text_pct <= 0.5:
        return False
    cima, baixo = df.row(r), df.row(abaixo)
    # 'ESTAÇÃO:' / 'DATA DE FUNDAÇÃO:' é metadado em chave e valor, não cabeçalho.
    if any(_preenchida(c) and str(c).strip().endswith(":") for c in cima):
        return False
    return any(not _preenchida(c) and _preenchida(b) for c, b in zip(cima, baixo, strict=True))


def _niveis(df: pl.DataFrame, metrics: list[RowMetrics], header: int) -> int:
    """Primeira linha do cabeçalho multinível que termina em ``header``."""
    topo = header
    while topo > 0 and header - topo + 1 < MAX_NIVEIS and _nivel_de_cabecalho(df, metrics, topo - 1, topo):
        topo -= 1
    return topo


def _texto_cabecalho(v: object) -> str | None:
    return None if v is None else " ".join(str(v).split()) or None


def _rotulos(df: pl.DataFrame, det: Detection, offset: int) -> dict[int, str]:
    """Nome de cada coluna depois do ``header_rows`` proposto: a mesma regra
    da operação (preenche os níveis de cima para a direita, junta as partes
    diferentes, célula vazia fica com a letra, repetidos ganham _2)."""
    if det.header_row is None:
        return {}
    cols = list(range(det.first_col, det.last_col + 1))
    linhas = []
    for r in range(det.top_row, det.header_row + 1):
        linha = df.row(r)
        linhas.append(
            [_texto_cabecalho(linha[c - offset]) if 0 <= c - offset < len(linha) else None for c in cols]
        )
    for linha in linhas[:-1]:
        anterior = None
        for j, v in enumerate(linha):
            if v is None:
                linha[j] = anterior
            else:
                anterior = v
    juntar = JUNTAR_NIVEIS if len(linhas) > 1 else " "
    nomes = []
    for j, c in enumerate(cols):
        partes: list[str] = []
        for linha in linhas:
            if linha[j] is not None and (not partes or partes[-1] != linha[j]):
                partes.append(linha[j])
        nomes.append(juntar.join(partes) or column_letter(c))
    vistos: dict[str, int] = {}
    tomados = set(nomes)
    unicos = []
    for nome in nomes:
        vistos[nome] = vistos.get(nome, 0) + 1
        if vistos[nome] == 1:
            unicos.append(nome)
            continue
        n = vistos[nome]
        while f"{nome}_{n}" in tomados:
            n += 1
        tomados.add(f"{nome}_{n}")
        unicos.append(f"{nome}_{n}")
    return dict(zip(cols, unicos, strict=True))


def detect_structure(df: pl.DataFrame, structure: SheetStructure | None = None) -> Detection | None:
    """Detecta a tabela principal de uma aba (grade do ``raw``: colunas com
    nome de letra, linha i = linha i + 1 da planilha). ``None`` se a aba não
    tem nenhuma linha preenchida. Com mais de uma tabela na aba, a de mais
    linhas de dados (ver ``detect_tables``)."""
    return main_table(detect_tables(df, structure))


def main_table(tabelas: list[Detection]) -> Detection | None:
    """A tabela principal: a de mais linhas de dados, a primeira no empate."""
    if not tabelas:
        return None
    return max(tabelas, key=lambda t: (t.last_row - t.first_row, -tabelas.index(t)))


def detect_tables(df: pl.DataFrame, structure: SheetStructure | None = None) -> list[Detection]:
    """Todas as tabelas da aba, na ordem de leitura (de cima para baixo, da
    esquerda para a direita)."""
    if df.width == 0 or df.height == 0:
        return []
    kinds = classify(df, structure)
    tabelas = []
    for linhas, colunas in _zonas(kinds):
        zona = _recorte(df, linhas, colunas)
        det = _detecta(zona, structure)
        if det is not None and det.last_row >= det.first_row:
            tabelas.append(det)
    if len(tabelas) > 1:
        # Zona que não tem dados de verdade (uma nota solta, um título) não
        # conta como tabela.
        tabelas = [t for t in tabelas if t.last_row - t.first_row >= 1] or tabelas
    return sorted(tabelas, key=lambda t: (t.top_row, t.first_col))


def _zonas(kinds: pl.DataFrame) -> list[tuple[tuple[int, int], list[str]]]:
    """Faixas de linhas separadas por ``VAZIAS_ENTRE_TABELAS`` linhas vazias
    e, dentro de cada faixa, grupos de colunas separados por coluna vazia
    quando cada grupo tem ``MIN_COLUNAS_LADO`` colunas ou mais."""
    cheias = kinds.select(pl.any_horizontal(pl.col(c) != 0 for c in kinds.columns)).to_series().to_list()
    faixas: list[tuple[int, int]] = []
    inicio, vazias = None, 0
    for r, cheia in enumerate(cheias):
        if cheia:
            if inicio is None:
                inicio = r
            elif vazias >= VAZIAS_ENTRE_TABELAS:
                faixas.append((inicio, r - vazias - 1))
                inicio = r
            vazias = 0
        else:
            vazias += 1
    if inicio is not None:
        faixas.append((inicio, len(cheias) - vazias - 1))

    zonas = []
    for a, b in faixas:
        trecho = kinds.slice(a, b - a + 1)
        usadas = [c for c in trecho.columns if (trecho[c] != 0).any()]
        grupos: list[list[str]] = [[]]
        for c in trecho.columns:
            if c in usadas:
                grupos[-1].append(c)
            elif grupos[-1]:
                grupos.append([])
        grupos = [g for g in grupos if g]
        if len(grupos) > 1 and all(len(g) >= MIN_COLUNAS_LADO for g in grupos):
            zonas += [((a, b), g) for g in grupos]
        else:
            zonas.append(((a, b), list(trecho.columns)))
    return zonas


def _recorte(df: pl.DataFrame, linhas: tuple[int, int], colunas: list[str]) -> pl.DataFrame:
    """A grade só com a zona: as outras linhas ficam vazias (os números das
    linhas continuam os da planilha) e só as colunas da zona."""
    a, b = linhas
    if a == 0 and b == df.height - 1 and colunas == df.columns:
        return df
    dentro = pl.int_range(pl.len()).is_between(a, b)
    return df.select(pl.when(dentro).then(pl.col(c)).alias(c) for c in _contiguas(df, colunas))


def _contiguas(df: pl.DataFrame, colunas: list[str]) -> list[str]:
    """Colunas da zona, contínuas (inclui coluna vazia no meio)."""
    i, j = df.columns.index(colunas[0]), df.columns.index(colunas[-1])
    return df.columns[i : j + 1]


def _detecta(df: pl.DataFrame, structure: SheetStructure | None) -> Detection | None:
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
    topo_cabecalho = _niveis(df, metrics, header) if header is not None else None

    topo = topo_cabecalho if topo_cabecalho is not None else inicio
    regiao = metrics[topo : b + 1]
    first_col = min(m.first_col for m in regiao if m.first_col is not None)
    last_col = max(m.last_col for m in regiao if m.last_col is not None)
    det = Detection(inicio, b, first_col, last_col, header)
    if topo_cabecalho is not None and topo_cabecalho < (header or 0):
        det.header_top = topo_cabecalho
    det.labels = _rotulos(df, det, offset)

    _totais(det, df, metrics, structure, offset, de_valor)
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


def _numeros(valores: list[Any]) -> list[float | None]:
    """Valores de uma coluna como número (marca de nota tirada: '3.289.290(1)')."""
    textos = [None if v is None else strip_footnote_marks(str(v).strip()) for v in valores]
    decimal = decimal_provavel(textos)
    return [None if t is None else parse_number_br(t, decimal=decimal) for t in textos]


def _igual(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6 * abs(a), 1e-9)


def _trechos(valores: list[float | None]) -> list[list[int]]:
    """Sequências de posições com número; linha sem número (seção, sinal)
    separa os trechos."""
    trechos: list[list[int]] = [[]]
    for i, v in enumerate(valores):
        if v is None:
            if trechos[-1]:
                trechos.append([])
        else:
            trechos[-1].append(i)
    return [t for t in trechos if t]


def _grupos(valores: list[float | None], trecho: list[int]) -> set[int] | None:
    """Subtotais de um trecho lido na ordem dada: cada linha que é a soma das
    anteriores desde o último subtotal (pelo menos duas, valor diferente de
    zero) fecha um grupo. Só vale se os grupos cobrem o trecho inteiro:
    sobra no máximo uma linha, no fim, e ela é o total geral (a soma dos
    subtotais). Uma soma que fecha por acaso deixa linhas soltas e não conta."""
    marcadas: list[int] = []
    soma, partes, soltas = 0.0, 0, []
    for i in trecho:
        v = valores[i]
        assert v is not None
        if partes >= 2 and v != 0 and _igual(v, soma):
            marcadas.append(i)
            soma, partes, soltas = 0.0, 0, []
        else:
            soma, partes = soma + v, partes + 1
            soltas.append(i)
    if not marcadas:
        return None
    if not soltas:
        return set(marcadas)
    if len(soltas) == 1 and len(marcadas) >= 2:
        geral = valores[soltas[0]]
        if geral and _igual(geral, sum(valores[i] for i in marcadas)):  # type: ignore[misc]
            return {*marcadas, soltas[0]}
    return None


def _somas(valores: list[float | None]) -> set[int]:
    """Posições que são subtotal ou total pela soma (D2): o valor é a soma
    das linhas de baixo até o próximo subtotal (subtotal antes dos
    componentes, como o IBGE publica: 'Região Norte' e depois os estados)
    ou das de cima desde o subtotal anterior (total no fim do grupo)."""
    marcadas: set[int] = set()
    for trecho in _trechos(valores):
        for ordem in (trecho[::-1], trecho):
            if (grupo := _grupos(valores, ordem)) is not None:
                marcadas |= grupo
                break
    # Uma soma só na coluna ('3' depois de '1' e '2') é pouca evidência: o
    # total único costuma ter a palavra "Total", que a regra de rótulo pega.
    return marcadas if len(marcadas) >= 2 else set()


def _totais(
    det: Detection,
    df: pl.DataFrame,
    metrics: list[RowMetrics],
    structure: SheetStructure | None,
    offset: int,
    de_valor: set[str],
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

    # Soma (D2): o valor fecha com as linhas do grupo.
    if not celulas and det.last_row > det.first_row:
        dados = df.slice(det.first_row, det.last_row - det.first_row + 1)
        colunas = [
            c
            for c in sorted(de_valor)
            if c in dados.columns and det.first_col <= column_index(c) <= det.last_col
        ]
        achadas = {det.first_row + i for c in colunas for i in _somas(_numeros(dados[c].to_list()))}
        rotulos = {r: _primeiro_texto(df, r, det, offset) for r in range(det.first_row, det.last_row + 1)}
        repetidos = Counter(c[1] for c in rotulos.values() if c is not None)
        for r in sorted(achadas):
            # Subtotal tem nome próprio ('Grande porte', 'Região Norte'). Rótulo
            # que se repete nas outras linhas ('Vitória' em janeiro, fevereiro e
            # março) é linha de dado, e a soma fechou por acaso ('3' = '1' + '2').
            if (celula := rotulos[r]) is not None and repetidos[celula[1]] == 1 and r not in celulas:
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

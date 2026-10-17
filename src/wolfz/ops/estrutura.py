"""Operações de estrutura: recortar a área da tabela, promover o cabeçalho,
tirar linhas e colunas vazias, preencher para baixo e despivotar.

``select_range`` e ``header_rows`` trabalham sobre a grade crua da planilha
(colunas com nome de letra, ``A``, ``B``, …; linha i = linha i + 1 do
Excel), que é como a ingestão entrega a aba e como a consulta M recebe a
fonte (``Fonte as table``).

As operações que dependem dos dados para saber o resultado (os nomes do
cabeçalho, quais colunas estão vazias) usam uma função auxiliar que vai
igual para o script Python exportado: o motor e o script rodam o mesmo
código.
"""

from __future__ import annotations

import re
from typing import Literal

import polars as pl
from pydantic import Field, field_validator, model_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_list, m_text

_A1 = re.compile(r"([A-Za-z]{1,3})([1-9]\d*)")


# ---------------------------------------------------------------------------
# Funções auxiliares (copiadas para o script Python exportado)
# ---------------------------------------------------------------------------


def coluna_indice(letra: str) -> int:
    """'A' -> 0, 'AA' -> 26. Nome que não é letra de coluna -> -1."""
    if not letra.isascii() or not letra.isalpha() or len(letra) > 3:
        return -1
    n = 0
    for ch in letra.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def celula_vazia(col: str) -> pl.Expr:
    """Nula ou só com espaços."""
    return pl.col(col).is_null() | (pl.col(col).cast(pl.String).str.strip_chars() == "")


def select_range_lf(
    lf: pl.LazyFrame, linha0: int, col0: int, linha1: int | None, col1: int | None, auto: bool
) -> pl.LazyFrame:
    """Recorta a grade: linhas ``linha0..linha1`` e colunas ``col0..col1``
    (0-based, inclusivo). Sem ``linha1`` e com ``auto``, para na primeira
    linha inteiramente vazia; sem ``col1``, vai até a última coluna."""
    nomes = lf.collect_schema().names()
    colunas = [c for c in nomes if col0 <= coluna_indice(c) and (col1 is None or coluna_indice(c) <= col1)]
    if not colunas:
        raise ValueError(f"nenhuma coluna da grade está no intervalo pedido (colunas: {', '.join(nomes)})")
    lf = lf.select(colunas).with_row_index("__linha__").filter(pl.col("__linha__") >= linha0)
    if linha1 is not None:
        lf = lf.filter(pl.col("__linha__") <= linha1)
    elif auto:
        vazia = pl.all_horizontal(celula_vazia(c) for c in colunas)
        lf = lf.filter(vazia.cast(pl.Int32).cum_sum() == 0)
    return lf.drop("__linha__")


def nomes_unicos(nomes: list[str]) -> list[str]:
    """['valor', 'valor', 'data'] -> ['valor', 'valor_2', 'data']."""
    vistos: dict[str, int] = {}
    tomados = set(nomes)
    saida = []
    for nome in nomes:
        vistos[nome] = vistos.get(nome, 0) + 1
        if vistos[nome] == 1:
            saida.append(nome)
            continue
        n = vistos[nome]
        while f"{nome}_{n}" in tomados:
            n += 1
        tomados.add(f"{nome}_{n}")
        saida.append(f"{nome}_{n}")
    return saida


def header_rows_lf(lf: pl.LazyFrame, n: int, joiner: str, names: list[str] | None) -> pl.LazyFrame:
    """As ``n`` primeiras linhas viram o nome das colunas. Com mais de uma
    linha, as de cima são preenchidas para a direita (célula mesclada na
    horizontal) e as partes são unidas com ``joiner``. Célula vazia mantém o
    nome atual da coluna; nome repetido ganha sufixo (_2, _3…). ``names``
    substitui os nomes, na ordem das colunas."""
    atuais = lf.collect_schema().names()
    if names is not None:
        if len(names) != len(atuais):
            raise ValueError(f"names tem {len(names)} nomes, mas a tabela tem {len(atuais)} colunas")
        return lf.slice(n).rename(dict(zip(atuais, names, strict=True)))
    linhas = [
        [None if v is None else " ".join(str(v).split()) or None for v in r]
        for r in lf.head(n).collect().rows()
    ]
    for linha in linhas[:-1]:
        anterior = None
        for j, v in enumerate(linha):
            if v is None:
                linha[j] = anterior
            else:
                anterior = v
    novos = []
    for j, atual in enumerate(atuais):
        partes: list[str] = []
        for linha in linhas:
            if linha[j] is not None and (not partes or partes[-1] != linha[j]):
                partes.append(linha[j])
        novos.append(joiner.join(partes) or atual)
    return lf.slice(n).rename(dict(zip(atuais, nomes_unicos(novos), strict=True)))


def drop_empty_cols_lf(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Tira as colunas sem nenhuma célula preenchida."""
    nomes = lf.collect_schema().names()
    vazias = lf.select(celula_vazia(c).all().alias(c) for c in nomes).collect().row(0)
    return lf.select([c for c, vazia in zip(nomes, vazias, strict=True) if not vazia])


def unpivot_lf(lf: pl.LazyFrame, index: list[str], variable_name: str, value_name: str) -> pl.LazyFrame:
    """Despivota as colunas que não estão em ``index``, linha a linha (todas
    as colunas da 1ª linha, depois da 2ª…), sem os valores nulos — a mesma
    ordem e a mesma regra do ``Table.UnpivotOtherColumns`` do M."""
    nomes = lf.collect_schema().names()
    on = [c for c in nomes if c not in index]
    ordem = pl.DataFrame({variable_name: on, "__coluna__": list(range(len(on)))}).lazy()
    return (
        lf.with_row_index("__linha__")
        .unpivot(on=on, index=["__linha__", *index], variable_name=variable_name, value_name=value_name)
        .filter(pl.col(value_name).is_not_null())
        .join(ordem, on=variable_name, how="left")
        .sort("__linha__", "__coluna__")
        .drop("__linha__", "__coluna__")
    )


# ---------------------------------------------------------------------------
# Funções M auxiliares
# ---------------------------------------------------------------------------

_M_COLUNA_INDICE = """
(nome as text) as number =>
    if Text.Length(nome) = 0 or Text.Length(nome) > 3
        or Text.Length(Text.Select(nome, {"A".."Z", "a".."z"})) <> Text.Length(nome)
    then -1
    else List.Accumulate(Text.ToList(Text.Upper(nome)), 0, (n, c) => n * 26 + Character.ToNumber(c) - 64) - 1
"""

_M_VAZIA = """
(v as any) as logical => v = null or Text.Trim(Text.From(v)) = ""
"""

_M_NOMES_UNICOS = """
(nomes as list) as list =>
    List.Accumulate(
        nomes,
        [saida = {}, contagem = [], tomados = nomes],
        (estado, nome) =>
            let
                vezes = estado[contagem],
                n = (if Record.HasFields(vezes, nome) then Record.Field(vezes, nome) else 0) + 1,
                contagem = Record.AddField(
                    Record.RemoveFields(vezes, nome, MissingField.Ignore), nome, n
                ),
                proximo = List.First(
                    List.Select(
                        List.Transform({n..n + List.Count(nomes) + 1}, each nome & "_" & Text.From(_)),
                        each not List.Contains(estado[tomados], _)
                    )
                ),
                novo = if n = 1 then nome else proximo
            in
                [
                    saida = estado[saida] & {novo},
                    contagem = contagem,
                    tomados = if n = 1 then estado[tomados] else estado[tomados] & {novo}
                ]
    )[saida]
"""

_M_CABECALHO = """
(tabela as table, n as number, juntar as text) as table =>
    let
        atuais = Table.ColumnNames(tabela),
        limpa = (v) => if v = null then null else
            let partes = Text.SplitAny(Text.From(v), " #(tab)#(cr)#(lf)"),
                t = Text.Combine(List.Select(partes, each _ <> ""), " ")
            in if t = "" then null else t,
        linhas = List.Transform(Table.ToRows(Table.FirstN(tabela, n)), each List.Transform(_, limpa)),
        paraDireita = (linha as list) as list => List.Skip(List.Accumulate(
            linha, {null}, (acc, v) => acc & {if v = null then List.Last(acc) else v}
        ), 1),
        preenchidas = List.Transform(List.FirstN(linhas, n - 1), paraDireita) & List.LastN(linhas, 1),
        partes = (j as number) as list => List.Accumulate(
            List.Transform(preenchidas, each _{j}),
            {},
            (acc, v) => if v = null or (List.Count(acc) > 0 and List.Last(acc) = v) then acc else acc & {v}
        ),
        novos = List.Transform(
            List.Positions(atuais),
            (j) => let p = partes(j) in if List.IsEmpty(p) then atuais{j} else Text.Combine(p, juntar)
        )
    in
        Table.RenameColumns(Table.Skip(tabela, n), List.Zip({atuais, WolfzNomesUnicos(novos)}))
"""


# ---------------------------------------------------------------------------
# Operações
# ---------------------------------------------------------------------------


def _a1(ref: str) -> tuple[int, int]:
    m = _A1.fullmatch(ref.strip())
    if not m:
        raise ValueError(f"{ref!r} não é uma célula em notação A1 (ex.: 'B4')")
    return int(m[2]) - 1, coluna_indice(m[1])


@register_op
class SelectRange(Op):
    """Recorta a área da tabela na grade da planilha.

    ``start`` é a célula do canto superior esquerdo, em notação A1 (a linha
    do cabeçalho, se houver). O fim pode ser ``end`` (canto inferior
    direito) ou ``end_detect: "auto"``, que vai até a primeira linha
    inteiramente vazia e até a última coluna."""

    op: Literal["select_range"]
    start: str
    end: str | None = None
    end_detect: Literal["auto"] | None = None

    python_helpers = (select_range_lf,)
    m_helpers = {"WolfzColunaIndice": _M_COLUNA_INDICE, "WolfzVazia": _M_VAZIA}  # noqa: RUF012
    examples = (
        {
            "step": {"start": "B2", "end": "C3"},
            "input": {
                "A": ["x", None, None, None],
                "B": ["t", "Nome", "Ana", "Bia"],
                "C": [None, "Valor", "1", "2"],
            },
            "expected": {"B": ["Nome", "Ana"], "C": ["Valor", "1"]},
        },
        {
            "step": {"start": "A2", "end_detect": "auto"},
            "input": {
                "A": ["Título", "Nome", "Ana", " ", "Fonte: X"],
                "B": [None, "Valor", "1", None, None],
            },
            "expected": {"A": ["Nome", "Ana"], "B": ["Valor", "1"]},
        },
        {
            "step": {"start": "B1"},
            "input": {"A": ["1", "2"], "B": ["3", "4"], "C": ["5", None]},
            "expected": {"B": ["3", "4"], "C": ["5", None]},
        },
    )

    @field_validator("start", "end")
    @classmethod
    def _celula(cls, ref: str | None) -> str | None:
        if ref is not None:
            _a1(ref)
            return ref.strip().upper()
        return ref

    @model_validator(mode="after")
    def _fim(self) -> SelectRange:
        if self.end is not None and self.end_detect is not None:
            raise ValueError("use end ou end_detect, não os dois")
        if self.end is not None:
            (l0, c0), (l1, c1) = _a1(self.start), _a1(self.end)
            if l1 < l0 or c1 < c0:
                raise ValueError(f"end ({self.end}) fica antes de start ({self.start})")
        return self

    def _args(self) -> tuple[int, int, int | None, int | None, bool]:
        linha0, col0 = _a1(self.start)
        linha1, col1 = _a1(self.end) if self.end else (None, None)
        return linha0, col0, linha1, col1, self.end_detect == "auto"

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return select_range_lf(lf, *self._args())

    def to_python(self) -> str:
        return f"lf = select_range_lf(lf, {', '.join(map(repr, self._args()))})"

    def to_m(self, prev: str, name: str) -> str:
        linha0, col0, linha1, col1, auto = self._args()
        limite = f" and WolfzColunaIndice(_) <= {col1}" if col1 is not None else ""
        colunas = f"List.Select(Table.ColumnNames({prev}), each WolfzColunaIndice(_) >= {col0}{limite})"
        linhas = f"Table.Skip(Table.SelectColumns({prev}, {colunas}), {linha0})"
        if linha1 is not None:
            corpo = f"Table.FirstN({linhas}, {linha1 - linha0 + 1})"
        elif auto:
            preenchida = "each not List.AllTrue(List.Transform(Record.FieldValues(_), WolfzVazia))"
            corpo = f"Table.FirstN({linhas}, {preenchida})"
        else:
            corpo = linhas
        return f"{name} = {corpo}"


@register_op
class HeaderRows(Op):
    """Promove as ``n`` primeiras linhas a cabeçalho.

    Com ``n`` maior que 1 (cabeçalho em várias linhas), as linhas de cima
    são preenchidas para a direita, como célula mesclada, e as partes são
    unidas com ``joiner``: 'Área (ha)' sobre '2022' vira 'Área (ha) 2022'.
    Célula de cabeçalho vazia mantém o nome atual; nome repetido ganha
    sufixo (_2, _3…). Com ``names``, as ``n`` linhas são descartadas e as
    colunas recebem esses nomes, na ordem (arquivo sem cabeçalho: ``n=0``)."""

    op: Literal["header_rows"]
    n: int = Field(default=1, ge=0, le=10)
    joiner: str = " "
    names: list[str] | None = None

    python_helpers = (header_rows_lf,)
    m_helpers = {"WolfzNomesUnicos": _M_NOMES_UNICOS, "WolfzCabecalho": _M_CABECALHO}  # noqa: RUF012
    examples = (
        {
            "step": {"n": 1},
            "input": {
                "A": ["Nome", "Ana"],
                "B": [None, "1"],
                "C": ["Nome", "x"],
                "D": ["  Valor  (R$) ", "2"],
            },
            "expected": {"Nome": ["Ana"], "B": ["1"], "Nome_2": ["x"], "Valor (R$)": ["2"]},
        },
        {
            "step": {"n": 2, "joiner": " "},
            "input": {
                "A": ["Município", None, "Vitória"],
                "B": ["Área", "2022", "10"],
                "C": [None, "2023", "11"],
            },
            "expected": {"Município": ["Vitória"], "Área 2022": ["10"], "Área 2023": ["11"]},
        },
        {
            "step": {"n": 0, "names": ["cnpj", "nome"]},
            "input": {"A": ["001", "002"], "B": ["X", "Y"]},
            "expected": {"cnpj": ["001", "002"], "nome": ["X", "Y"]},
        },
    )

    @model_validator(mode="after")
    def _n_ou_nomes(self) -> HeaderRows:
        if self.n == 0 and self.names is None:
            raise ValueError("com n=0, informe names")
        if self.names is not None and any(not nome.strip() for nome in self.names):
            raise ValueError("nome de coluna não pode ser vazio")
        if self.names is not None and len(set(self.names)) != len(self.names):
            raise ValueError("names tem nomes repetidos")
        return self

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return header_rows_lf(lf, self.n, self.joiner, self.names)

    def to_python(self) -> str:
        return f"lf = header_rows_lf(lf, {self.n!r}, {self.joiner!r}, {self.names!r})"

    def to_m(self, prev: str, name: str) -> str:
        if self.names is not None:
            pares = f"List.Zip({{Table.ColumnNames({prev}), {m_list(self.names)}}})"
            return f"{name} = Table.RenameColumns(Table.Skip({prev}, {self.n}), {pares})"
        return f"{name} = WolfzCabecalho({prev}, {self.n}, {m_text(self.joiner)})"


@register_op
class DropEmptyRows(Op):
    """Tira as linhas em que todas as células estão vazias (nulas ou só
    com espaços)."""

    op: Literal["drop_empty_rows"]

    python_helpers = (celula_vazia,)
    m_helpers = {"WolfzVazia": _M_VAZIA}  # noqa: RUF012
    examples = (
        {
            "step": {},
            "input": {"a": ["1", None, " ", "4"], "b": ["x", None, None, None]},
            "expected": {"a": ["1", "4"], "b": ["x", None]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        nomes = lf.collect_schema().names()
        return lf.filter(~pl.all_horizontal(celula_vazia(c) for c in nomes))

    def to_python(self) -> str:
        return "lf = lf.filter(~pl.all_horizontal(celula_vazia(c) for c in lf.collect_schema().names()))"

    def to_m(self, prev: str, name: str) -> str:
        cond = "not List.AllTrue(List.Transform(Record.FieldValues(_), WolfzVazia))"
        return f"{name} = Table.SelectRows({prev}, each {cond})"


@register_op
class DropEmptyCols(Op):
    """Tira as colunas sem nenhuma célula preenchida (colunas de espaçamento
    de relatório, 'Valor de Compra' que nunca é preenchido)."""

    op: Literal["drop_empty_cols"]

    python_helpers = (drop_empty_cols_lf,)
    m_helpers = {"WolfzVazia": _M_VAZIA}  # noqa: RUF012
    examples = (
        {
            "step": {},
            "input": {"a": ["1", None], "b": [None, " "], "c": [None, "x"]},
            "expected": {"a": ["1", None], "c": [None, "x"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return drop_empty_cols_lf(lf)

    def to_python(self) -> str:
        return "lf = drop_empty_cols_lf(lf)"

    def to_m(self, prev: str, name: str) -> str:
        cheias = (
            f"List.Select(Table.ColumnNames({prev}), "
            f"(c) => not List.AllTrue(List.Transform(Table.Column({prev}, c), WolfzVazia)))"
        )
        return f"{name} = Table.SelectColumns({prev}, {cheias})"


@register_op
class FillDown(Op):
    """Preenche para baixo as células vazias das colunas (categoria mesclada
    na vertical, relatório que só escreve o grupo na primeira linha)."""

    op: Literal["fill_down"]
    cols: list[str] = Field(min_length=1)

    python_helpers = (celula_vazia,)
    m_helpers = {"WolfzVazia": _M_VAZIA}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["regiao"]},
            "input": {"regiao": [None, "Sul", None, " ", "Norte", None], "v": ["0", "1", "2", "3", "4", "5"]},
            "expected": {
                "regiao": [None, "Sul", "Sul", "Sul", "Norte", "Norte"],
                "v": ["0", "1", "2", "3", "4", "5"],
            },
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.with_columns(
            pl.when(celula_vazia(c)).then(None).otherwise(pl.col(c)).forward_fill().alias(c)
            for c in self.cols
        )

    def to_python(self) -> str:
        return (
            "lf = lf.with_columns(pl.when(celula_vazia(c)).then(None).otherwise(pl.col(c))"
            f".forward_fill().alias(c) for c in {self.cols!r})"
        )

    def to_m(self, prev: str, name: str) -> str:
        transforms = ", ".join(f"{{{m_text(c)}, each if WolfzVazia(_) then null else _}}" for c in self.cols)
        return (
            f"{name} = Table.FillDown(Table.TransformColumns({prev}, {{{transforms}}}), {m_list(self.cols)})"
        )


@register_op
class Unpivot(Op):
    """Despivota: as colunas fora de ``index`` (meses lado a lado, anos)
    viram duas colunas, nome e valor. A saída vai linha a linha e sem os
    valores nulos, como o ``Table.UnpivotOtherColumns`` do Power Query."""

    op: Literal["unpivot"]
    full_checkpoint = True  # junta a tabela inteira e reordena
    index: list[str] = Field(min_length=1)
    variable_name: str = Field(default="variavel", min_length=1)
    value_name: str = Field(default="valor", min_length=1)

    python_helpers = (unpivot_lf,)
    examples = (
        {
            "step": {"index": ["uf"], "variable_name": "mes", "value_name": "valor"},
            "input": {"uf": ["ES", "RJ"], "jan": ["1", "3"], "fev": ["2", None]},
            "expected": {"uf": ["ES", "ES", "RJ"], "mes": ["jan", "fev", "jan"], "valor": ["1", "2", "3"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return unpivot_lf(lf, self.index, self.variable_name, self.value_name)

    def to_python(self) -> str:
        return f"lf = unpivot_lf(lf, {self.index!r}, {self.variable_name!r}, {self.value_name!r})"

    def to_m(self, prev: str, name: str) -> str:
        args = f"{m_list(self.index)}, {m_text(self.variable_name)}, {m_text(self.value_name)}"
        return f"{name} = Table.UnpivotOtherColumns({prev}, {args})"


__all__ = [
    "DropEmptyCols",
    "DropEmptyRows",
    "FillDown",
    "HeaderRows",
    "SelectRange",
    "Unpivot",
]

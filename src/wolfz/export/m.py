"""Exportação da receita como Power Query M (F2.A).

``recipe_to_m`` monta uma consulta ``let ... in`` completa: lê o arquivo
de origem (``Excel.Workbook`` ou ``Csv.Document``) a partir do parâmetro
``CaminhoArquivo``, refaz a grade crua que o motor recebe (colunas ``A``,
``B``, …, tudo texto) e aplica os passos ativos, cada um com um nome
legível e único e um comentário ``// s3 drop_rows_where`` antes.
``parameter_to_m`` gera o parâmetro ``CaminhoArquivo``, exportado num
arquivo separado.

Nomes de coluna, textos e nomes de passo nunca são concatenados direto no
código: passam por ``m_text``, ``m_identifier`` e ``m_value``, que escapam
aspas e caracteres de controle (§11.5 do design).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl

from wolfz.core.ingest.cells import column_index
from wolfz.core.recipe import Op, Recipe

PARAMETRO = "CaminhoArquivo"

_ESCAPES = {"\r": "#(cr)", "\n": "#(lf)", "\t": "#(tab)"}
_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PALAVRAS_RESERVADAS = frozenset(
    {
        *("and", "as", "each", "else", "error", "false", "if", "in", "is", "let", "meta"),
        *("not", "null", "or", "otherwise", "section", "shared", "then", "true", "try", "type"),
    }
)
# Passos que trabalham sobre a grade crua: se a receita começa por um deles,
# o CSV é lido sem cabeçalho (a mesma regra de ``wolfz.run``).
_PASSOS_DE_GRADE = {"select_range", "header_rows"}
# Encoding detectado na importação -> página de código do Csv.Document.
_CODEPAGES = {"utf-8": 65001, "utf-8-sig": 65001, "cp1252": 1252, "latin-1": 28591, "utf-16": 1200}


# ---------------------------------------------------------------------------
# Escapes
# ---------------------------------------------------------------------------


def _text_body(value: str) -> str:
    out = []
    for i, ch in enumerate(value):
        if ch == '"':
            out.append('""')
        elif ch == "#" and value[i + 1 : i + 2] == "(":
            out.append("#(#)")
        elif ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 32 or 127 <= ord(ch) < 160 or ch in "\u2028\u2029":
            out.append(f"#({ord(ch):04X})")
        else:
            out.append(ch)
    return "".join(out)


def m_text(value: str) -> str:
    """Literal de texto M: '"Valor"' com aspas dobradas e controles
    escapados. '#(' também é escapado, porque abre uma sequência de escape."""
    return '"' + _text_body(value) + '"'


def m_identifier(name: str) -> str:
    """Identificador M: o nome como está, se for um identificador simples
    que não é palavra reservada; senão, a forma entre aspas ``#"nome"``."""
    if _IDENTIFICADOR.fullmatch(name) and name not in _PALAVRAS_RESERVADAS:
        return name
    return '#"' + _text_body(name) + '"'


def m_value(value: Any) -> str:
    """Literal M de um valor da receita: nulo, lógico, número, texto ou lista."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isnan(value):
        return "#nan"
    if isinstance(value, float) and math.isinf(value):
        return "#infinity" if value > 0 else "-#infinity"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return m_text(value)
    if isinstance(value, list | tuple):
        return m_list(value)
    raise TypeError(f"valor sem literal M: {type(value).__name__}")


def m_list(items: Iterable[Any]) -> str:
    """Lista M: {"a", "b"}, {1, null}."""
    return "{" + ", ".join(m_value(i) for i in items) + "}"


def m_field(column: str, row: str = "_") -> str:
    """Valor da coluna na linha. ``Record.Field`` aceita qualquer nome de
    coluna sem precisar escapar identificador."""
    return f"Record.Field({row}, {m_text(column)})"


def _comment(text: str) -> str:
    """Texto seguro para um comentário de linha: sem quebra de linha."""
    return " ".join("".join(" " if ord(c) < 32 or c in "\u2028\u2029\x85" else c for c in text).split())


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FonteM:
    """Como a consulta lê o arquivo de origem.

    ``linha0`` e ``coluna0`` são a posição (0-based) da primeira linha e da
    primeira coluna preenchidas da aba: o ``Excel.Workbook`` começa a tabela
    na área usada, e a consulta devolve as linhas vazias de cima e as
    letras certas às colunas. ``colunas`` é a largura do CSV
    (``Columns`` do ``Csv.Document``)."""

    tipo: Literal["excel", "csv", "ods"]
    aba: str | None = None
    encoding: str | None = None
    separador: str | None = None
    colunas: int | None = None
    linha0: int = 0
    coluna0: int = 0
    caminho: str | None = None


def source_from_project(source: dict[str, Any], grade: pl.LazyFrame) -> FonteM:
    """``FonteM`` a partir do ``source`` do ``project.json`` e da grade crua
    (``raw.parquet``) do projeto."""
    fmt = source.get("format")
    tipo: Literal["excel", "csv", "ods"] = "csv" if fmt == "csv" else "ods" if fmt == "ods" else "excel"
    nomes = grade.collect_schema().names()
    if tipo == "csv":
        return FonteM(
            tipo,
            encoding=source.get("encoding"),
            separador=source.get("separator"),
            colunas=len(nomes) or None,
            caminho=source.get("path"),
        )
    linha0 = coluna0 = 0
    if nomes:
        cheias = grade.select(pl.col(c).is_not_null().any() for c in nomes).collect().row(0)
        primeira = next((c for c, cheia in zip(nomes, cheias, strict=True) if cheia), None)
        if primeira is not None:
            coluna0 = column_index(primeira)
            alguma = pl.any_horizontal(pl.col(c).is_not_null() for c in nomes)
            linha0 = grade.select(alguma.arg_true().first()).collect().item() or 0
    return FonteM(tipo, aba=source.get("sheet"), linha0=linha0, coluna0=coluna0, caminho=source.get("path"))


def source_from_file(recipe: Recipe, path: str | Path) -> FonteM:
    """``FonteM`` lendo o arquivo como ``wolfz.run`` leria (encoding e
    separador do CSV, área usada da aba)."""
    # Import tardio: o motor importa o catálogo, que importa este módulo.
    from wolfz.core.engine import read_input
    from wolfz.core.ingest import open_file
    from wolfz.core.ingest.csv import sniff_csv

    path, fmt, _ = open_file(path)
    source: dict[str, Any] = {"format": fmt, "path": str(path), "sheet": recipe.source.sheet}
    if fmt == "csv":
        source["encoding"], source["separator"] = sniff_csv(path)
    return source_from_project(source, read_input(recipe, path).lazy())


_M_TEXTO = """
(v as any) as nullable text =>
    if v = null or v = "" then null
    else if v is logical then (if v then "true" else "false")
    else if v is number then
        (if Number.Round(v) = v and Number.Abs(v) < 1e21
        then Number.ToText(v, "F0", "en-US")
        else Number.ToText(v, "R", "en-US"))
    else if v is datetime then DateTime.ToText(v, [Format = "yyyy-MM-dd HH:mm:ss", Culture = "en-US"])
    else if v is date then Date.ToText(v, [Format = "yyyy-MM-dd", Culture = "en-US"]) & " 00:00:00"
    else if v is time then Time.ToText(v, [Format = "HH:mm:ss", Culture = "en-US"])
    else Text.From(v, "en-US")
"""

_M_LETRA = """
(i as number) as text =>
    (if i >= 26 then @WolfzLetra(Number.IntegerDivide(i, 26) - 1) else "")
        & Character.FromNumber(65 + Number.Mod(i, 26))
"""

_M_GRADE = """
(dados as table, linha0 as number, coluna0 as number) as table =>
    let
        nomes = Table.ColumnNames(dados),
        semErros = Table.ReplaceErrorValues(dados, List.Transform(nomes, each {_, null})),
        texto = Table.TransformColumns(
            semErros, List.Transform(nomes, each {_, WolfzTexto, type nullable text})
        ),
        vazia = (linha as record) as logical => List.NonNullCount(Record.FieldValues(linha)) = 0,
        linhas = Table.RemoveLastN(Table.Skip(texto, vazia), vazia),
        cheias = List.Transform(nomes, (c) => List.NonNullCount(Table.Column(linhas, c)) > 0),
        primeira = List.PositionOf(cheias, true),
        usadas = if primeira < 0 then {} else List.Skip(nomes, primeira),
        letras = List.Transform(List.Positions(usadas), each WolfzLetra(coluna0 + _)),
        grade = Table.RenameColumns(Table.SelectColumns(linhas, usadas), List.Zip({usadas, letras})),
        acima = #table(letras, List.Repeat({List.Repeat({null}, List.Count(letras))}, linha0))
    in
        acima & grade
"""

_M_GRADE_CSV = """
(dados as table) as table =>
    let
        nomes = Table.ColumnNames(dados),
        letras = List.Transform(List.Positions(nomes), each WolfzLetra(_)),
        texto = Table.TransformColumns(
            dados, List.Transform(nomes, each {_, WolfzVazioNulo, type nullable text})
        )
    in
        Table.RenameColumns(texto, List.Zip({nomes, letras}))
"""

_M_VAZIO_NULO = """
(v as nullable text) as nullable text => if v = "" then null else v
"""


def _source_steps(fonte: FonteM, grade: bool) -> tuple[dict[str, str], list[str]]:
    """Funções auxiliares e passos que leem o arquivo e terminam em
    ``Fonte``. Cada passo é ``nome = expressão``, com comentários antes."""
    arquivo = f"File.Contents({PARAMETRO})"
    if fonte.tipo == "csv":
        separador = fonte.separador or ";"
        encoding = fonte.encoding or "utf-8"
        opcoes = [f"Delimiter = {m_text(separador)}"]
        if fonte.colunas:
            opcoes.append(f"Columns = {fonte.colunas}")
        opcoes.append(f"Encoding = {_CODEPAGES.get(encoding, 65001)}")
        opcoes.append("QuoteStyle = QuoteStyle.Csv")
        descricao = _comment(f"CSV {encoding}, separador {separador!r}")
        passos = [f"// Fonte: {descricao}\nArquivo = Csv.Document({arquivo}, [{', '.join(opcoes)}])"]
        if grade:
            passos.append("Fonte = WolfzGradeCsv(Arquivo)")
            ajudantes = {
                "WolfzLetra": _M_LETRA,
                "WolfzVazioNulo": _M_VAZIO_NULO,
                "WolfzGradeCsv": _M_GRADE_CSV,
            }
        else:
            cabecalho = "Table.PromoteHeaders(Arquivo, [PromoteAllScalars = true])"
            transforma = (
                "List.Transform(Table.ColumnNames(Cabecalho), each {_, WolfzVazioNulo, type nullable text})"
            )
            passos += [f"Cabecalho = {cabecalho}", f"Fonte = Table.TransformColumns(Cabecalho, {transforma})"]
            ajudantes = {"WolfzVazioNulo": _M_VAZIO_NULO}
        return ajudantes, passos

    if fonte.aba is None:
        aba = 'Table.SelectRows(Arquivo, each [Kind] = "Sheet" and not [Hidden]){0}[Data]'
        descricao = "primeira aba visível"
    else:
        aba = f'Arquivo{{[Item = {m_text(fonte.aba)}, Kind = "Sheet"]}}[Data]'
        descricao = f"aba {fonte.aba}"
    aviso = ""
    if fonte.tipo == "ods":
        aviso = f"// O Power Query não lê .ods: salve o arquivo como .xlsx e aponte {PARAMETRO} para ele.\n"
    passos = [
        f"// Fonte: {_comment(descricao)}\n{aviso}Arquivo = Excel.Workbook({arquivo}, null, true)",
        f"Aba = {aba}",
        f"Fonte = WolfzGrade(Aba, {fonte.linha0}, {fonte.coluna0})",
    ]
    return {"WolfzTexto": _M_TEXTO, "WolfzLetra": _M_LETRA, "WolfzGrade": _M_GRADE}, passos


# ---------------------------------------------------------------------------
# Montador
# ---------------------------------------------------------------------------


def step_names(steps: Iterable[Op], reserved: Iterable[str] = ()) -> dict[str, str]:
    """Nome legível e único de cada passo (id -> identificador M): o rótulo
    da operação (``m_label``), com 2, 3… quando o rótulo se repete."""
    tomados = set(reserved)
    nomes = {}
    for step in steps:
        base = step.m_label or step.op
        nome, n = base, 1
        while nome in tomados:
            n += 1
            nome = f"{base} {n}"
        tomados.add(nome)
        nomes[step.id] = m_identifier(nome)
    return nomes


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(f"{prefix}{line}" if line else "" for line in text.splitlines())


def recipe_to_m(recipe: Recipe, fonte: FonteM | None = None) -> str:
    """Consulta M completa: lê o arquivo de ``CaminhoArquivo`` e aplica os
    passos ativos da receita. Sem ``fonte``, usa o tipo e a aba da receita."""
    if fonte is None:
        fonte = FonteM(recipe.source.type, aba=recipe.source.sheet)
    steps = recipe.active_steps
    grade = bool(steps) and steps[0].op in _PASSOS_DE_GRADE
    helpers, fonte_passos = _source_steps(fonte, grade or fonte.tipo != "csv")
    for step in steps:
        for name, definition in step.m_helpers.items():
            if helpers.setdefault(name, definition) != definition:
                raise ValueError(f"duas definições diferentes para a função M {name!r}")

    extras = list(dict.fromkeys(p for step in steps for p in step.m_parameters))
    reservados = {*helpers, PARAMETRO, *extras, "Arquivo", "Aba", "Cabecalho", "Fonte"}
    nomes = step_names(steps, reservados)
    blocos = [f"{name} = {definition.strip()}" for name, definition in helpers.items()]
    blocos += fonte_passos
    prev = "Fonte"
    for step in steps:
        nome = nomes[step.id]
        blocos.append(f"// {_comment(f'{step.id} {step.op}')}\n" + step.to_m(prev, nome))
        prev = nome
    corpo = ",\n".join(blocos)

    cabecalho = [
        f'// Consulta gerada pelo WolfzBR a partir da receita "{_comment(recipe.name)}".',
        f"// Precisa do parâmetro {PARAMETRO} (texto com o caminho completo do arquivo de origem):",
        "// Power BI Desktop > Transformar dados > Gerenciar Parâmetros > Novo Parâmetro,",
        f"// Nome: {PARAMETRO}, Tipo: Texto. O arquivo .{PARAMETRO}.pq exportado junto tem o valor.",
        *(
            f"// Precisa também do parâmetro {p}: crie do mesmo jeito, com o arquivo .{p}.pq exportado junto."
            for p in extras
        ),
        "// Para colar esta consulta: Nova Fonte > Consulta Nula > Editor Avançado.",
    ]
    return "\n".join(cabecalho) + f"\nlet\n{_indent(corpo)}\nin\n    {prev}\n"


def parameter_to_m(caminho: str | None, recipe_name: str = "", nome: str = PARAMETRO) -> str:
    """Parâmetro de caminho (``CaminhoArquivo`` ou outro, como o do de-para),
    para colar como uma consulta nula com esse nome (ou criar pela tela de
    parâmetros com o mesmo valor)."""
    valor = m_text(caminho or "C:\\caminho\\do\\arquivo")
    receita = f' da receita "{_comment(recipe_name)}"' if recipe_name else ""
    dica = (
        "// Para aplicar a receita a outro arquivo, troque só este valor.\n"
        if nome == PARAMETRO
        else "// Aponte para o arquivo exportado junto com a consulta.\n"
    )
    return (
        f"// Parâmetro {nome}{receita}, gerado pelo WolfzBR.\n"
        "// Power BI Desktop > Transformar dados > Gerenciar Parâmetros > Novo Parâmetro:\n"
        f"// Nome {nome}, Tipo Texto, Valor atual = o caminho abaixo. Ou: Nova Fonte >\n"
        f"// Consulta Nula, renomeie para {nome} e cole este texto no Editor Avançado.\n"
        f"{dica}"
        f'{valor} meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
    )

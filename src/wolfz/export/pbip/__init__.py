"""Exportação para o Power BI como projeto PBIP (F3.B).

O projeto tem três partes, lado a lado na pasta de saída::

    <nome>.pbip                  atalho que o Power BI Desktop abre
    <nome>.SemanticModel/        modelo semântico em TMDL
    <nome>.Report/               relatório em PBIR, com uma página vazia

- O modelo tem uma tabela com as colunas e os tipos da tabela limpa. A
  partição é o M da receita (``recipe_to_m``) com um último passo que fixa
  os tipos, e lê o arquivo pelo parâmetro ``CaminhoArquivo``
  (``expressions.tmdl``): para o mês seguinte, troca-se só o parâmetro e dá
  refresh.
- Colunas de reais (``parse_brl``) saem com ``R$``; de percentual, com ``%``;
  datas em ``dd/MM/yyyy``. Cada coluna de métrica ganha a medida
  ``Total <coluna>``, e a tabela, ``Contagem de linhas``.
- Com ``calendario``, entra uma tabela calendário (DAX) com os nomes dos
  meses em português, ligada à primeira coluna de data.
- Os arquivos que mudam de formato entre versões do Power BI ficam em
  ``templates/``. Os identificadores (``lineageTag``, ``logicalId``, nome
  da página) são derivados do nome da receita: exportar duas vezes a mesma
  receita gera os mesmos arquivos.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from string import Template

import polars as pl

from wolfz.core.recipe import Recipe
from wolfz.export.dados import ExportError
from wolfz.export.m import PARAMETRO, FonteM, m_text, parameter_to_m, recipe_to_m
from wolfz.export.tableau import Formato, formatos_colunas

TEMPLATES = Path(__file__).parent / "templates"
CALENDARIO = "Calendário"
CONTAGEM = "Contagem de linhas"

# Formatos do Power BI (formatString). Moeda como o próprio Desktop grava
# para "R$" em português.
FORMATO_BRL = '"R$"\\ #,0.00;-"R$"\\ #,0.00;"R$"\\ #,0.00'
_DICA_REAIS = '{"currencyCulture":"pt-BR"}'
FORMATO_PERCENTUAL = "0.00%"
FORMATO_DATA = "dd/MM/yyyy"
FORMATO_DATA_HORA = "dd/MM/yyyy HH:mm:ss"
FORMATO_HORA = "HH:mm:ss"
FORMATO_INTEIRO = "0"
FORMATO_DECIMAL = "#,0.00"

# Coluna numérica que é código, ano ou documento: não vira medida nem soma.
_NAO_METRICA = re.compile(
    r"(^|[\W_])(ano|m[eê]s|dia|c[oó]d(igo)?|id|cep|cpf|cnpj|ibge|uf|n[uú]mero|n[º°o]|seq|ordem)([\W_]|$)",
    re.IGNORECASE,
)
_SIMPLES = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NAMESPACE = uuid.UUID("5b0f2d6e-6c1e-4f53-9a51-77a8f0a1c0de")


@dataclass(frozen=True)
class OpcoesPbip:
    calendario: bool = False


# ---------------------------------------------------------------------------
# Nomes
# ---------------------------------------------------------------------------


def tmdl_nome(nome: str) -> str:
    """Nome de objeto no TMDL: entre aspas simples (dobradas por dentro)
    quando não é um identificador simples."""
    if _SIMPLES.fullmatch(nome):
        return nome
    return "'" + nome.replace("'", "''") + "'"


def dax_tabela(nome: str) -> str:
    return "'" + nome.replace("'", "''") + "'"


def dax_coluna(tabela: str, coluna: str) -> str:
    return dax_tabela(tabela) + "[" + coluna.replace("]", "]]") + "]"


def _arquivo(nome: str) -> str:
    """Nome de arquivo para a tabela (``tables/<nome>.tmdl``)."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .") or "tabela"


def _guid(*partes: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "\x1f".join(partes)))


class _Modelo(Template):
    """Só ``${nome}`` é substituído: ``$schema`` dos JSONs fica como está."""

    pattern = r"\$(?:(?P<escaped>\$)|\{(?P<braced>[_a-z][_a-z0-9]*)\}|(?P<named>(?!))|(?P<invalid>(?!)))"


def _template(arquivo: str, **valores: str) -> str:
    return _Modelo((TEMPLATES / arquivo).read_text(encoding="utf-8")).substitute(valores)


# ---------------------------------------------------------------------------
# Tipos e medidas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Coluna:
    nome: str
    tipo_tmdl: str  # dataType
    tipo_m: str  # para Table.TransformColumnTypes
    formato: str | None
    subtipo_data: str | None  # annotation UnderlyingDateTimeDataType
    metrica: bool


def _coluna(nome: str, dtype: pl.DataType, formato: Formato | None) -> _Coluna:
    metrica = dtype.is_numeric() and not _NAO_METRICA.search(nome)
    if dtype == pl.Date:
        return _Coluna(nome, "dateTime", "type date", FORMATO_DATA, "Date", False)
    if isinstance(dtype, pl.Datetime):
        return _Coluna(nome, "dateTime", "type datetime", FORMATO_DATA_HORA, None, False)
    if dtype == pl.Time:
        return _Coluna(nome, "dateTime", "type time", FORMATO_HORA, "Time", False)
    if dtype == pl.Boolean:
        return _Coluna(nome, "boolean", "type logical", None, None, False)
    if dtype.is_integer():
        return _Coluna(nome, "int64", "Int64.Type", FORMATO_INTEIRO, None, metrica)
    if dtype.is_float() or isinstance(dtype, pl.Decimal):
        fmt = {"brl": FORMATO_BRL, "percent": FORMATO_PERCENTUAL}.get(formato or "", FORMATO_DECIMAL)
        return _Coluna(nome, "double", "type number", fmt, None, metrica)
    return _Coluna(nome, "string", "type text", None, None, False)


def colunas(schema: pl.Schema, recipe: Recipe) -> list[_Coluna]:
    formatos = formatos_colunas(recipe)
    return [_coluna(n, t, formatos.get(n)) for n, t in schema.items()]


def _medidas(tabela: str, cols: list[_Coluna]) -> list[tuple[str, str, str]]:
    """(nome, DAX, formatString) de cada medida."""
    nomes_colunas = {c.nome for c in cols}
    medidas = []
    for c in cols:
        if c.metrica and (nome := f"Total {c.nome}") not in nomes_colunas:
            medidas.append((nome, f"SUM({dax_coluna(tabela, c.nome)})", c.formato or FORMATO_DECIMAL))
    if CONTAGEM not in nomes_colunas:
        medidas.append((CONTAGEM, f"COUNTROWS({dax_tabela(tabela)})", "#,0"))
    return medidas


# ---------------------------------------------------------------------------
# TMDL
# ---------------------------------------------------------------------------


def _expressao(texto: str, nivel: int) -> str:
    """Expressão de várias linhas no TMDL: cada linha com ``nivel`` tabs."""
    prefixo = "\t" * nivel
    return "\n".join(prefixo + linha if linha.strip() else "" for linha in texto.rstrip().splitlines())


def particao_m(recipe: Recipe, fonte: FonteM, cols: list[_Coluna]) -> str:
    """O M da receita com um último passo que fixa os tipos das colunas."""
    receita = recipe_to_m(recipe, fonte).rstrip()
    tipos = ", ".join(f"{{{m_text(c.nome)}, {c.tipo_m}}}" for c in cols)
    corpo = "\n".join("        " + linha if linha.strip() else "" for linha in receita.splitlines())
    return (
        "let\n"
        "    Receita =\n"
        f"{corpo},\n"
        f"    Tipos = Table.TransformColumnTypes(Receita, {{{tipos}}})\n"
        "in\n"
        "    Tipos"
    )


def tabela_tmdl(tabela: str, cols: list[_Coluna], m: str) -> str:
    linhas = [f"table {tmdl_nome(tabela)}", f"\tlineageTag: {_guid('tabela', tabela)}", ""]
    for nome, dax, formato in _medidas(tabela, cols):
        linhas += [
            f"\tmeasure {tmdl_nome(nome)} = {dax}",
            f"\t\tformatString: {formato}",
            f"\t\tlineageTag: {_guid('medida', tabela, nome)}",
            "",
        ]
        if formato == FORMATO_BRL:
            linhas += [f"\t\tannotation PBI_FormatHint = {_DICA_REAIS}", ""]
    for c in cols:
        linhas += [f"\tcolumn {tmdl_nome(c.nome)}", f"\t\tdataType: {c.tipo_tmdl}"]
        if c.formato:
            linhas.append(f"\t\tformatString: {c.formato}")
        linhas += [
            f"\t\tlineageTag: {_guid('coluna', tabela, c.nome)}",
            f"\t\tsummarizeBy: {'sum' if c.metrica else 'none'}",
            f"\t\tsourceColumn: {c.nome}",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
        ]
        if c.subtipo_data:
            linhas += [f"\t\tannotation UnderlyingDateTimeDataType = {c.subtipo_data}", ""]
        if c.formato == FORMATO_BRL:
            linhas += [f"\t\tannotation PBI_FormatHint = {_DICA_REAIS}", ""]
    linhas += [
        f"\tpartition {tmdl_nome(tabela)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        _expressao(m, 4),
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(linhas)


def parametro_tmdl(nome: str, valor: str) -> str:
    """Parâmetro de texto (``CaminhoArquivo``) como expressão do modelo."""
    meta = '[IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]'
    return "\n".join(
        [
            f"expression {tmdl_nome(nome)} = {m_text(valor)} meta {meta}",
            f"\tlineageTag: {_guid('parametro', nome)}",
            "",
            "\tannotation PBI_ResultType = Text",
            "",
        ]
    )


# ---------------------------------------------------------------------------
# Projeto
# ---------------------------------------------------------------------------


def projeto_pbip(
    nome: str,
    recipe: Recipe,
    schema: pl.Schema,
    fonte: FonteM,
    parametros: dict[str, str],
    opcoes: OpcoesPbip | None = None,
) -> dict[str, str]:
    """Os arquivos do projeto, como ``{caminho relativo: conteúdo}``.

    ``nome`` é o nome dos arquivos (``<nome>.pbip``); a tabela tem o nome da
    receita. ``parametros`` traz o valor de ``CaminhoArquivo`` e dos outros
    parâmetros que a receita usa (o caminho do de-para de municípios)."""
    opcoes = opcoes or OpcoesPbip()
    tabela = recipe.name.strip() or "Tabela"
    cols = colunas(schema, recipe)
    modelo = f"{nome}.SemanticModel"
    relatorio = f"{nome}.Report"
    pagina = _guid("pagina", nome).replace("-", "")[:20]

    tabelas = [tabela]
    arquivos: dict[str, str] = {
        f"{nome}.pbip": _template("projeto.pbip", nome=nome),
        f"{modelo}/.platform": _template(
            "platform.json",
            tipo="SemanticModel",
            nome_json=json.dumps(nome),
            logical_id=_guid("modelo", nome),
        ),
        f"{modelo}/definition.pbism": _template("definition.pbism"),
        f"{modelo}/definition/database.tmdl": _template("database.tmdl"),
        f"{modelo}/definition/tables/{_arquivo(tabela)}.tmdl": tabela_tmdl(
            tabela, cols, particao_m(recipe, fonte, cols)
        ),
        f"{modelo}/definition/expressions.tmdl": "\n".join(
            parametro_tmdl(n, v) for n, v in parametros.items()
        ),
        f"{relatorio}/.platform": _template(
            "platform.json", tipo="Report", nome_json=json.dumps(nome), logical_id=_guid("relatorio", nome)
        ),
        f"{relatorio}/definition.pbir": _template("definition.pbir", modelo_json=json.dumps(f"../{modelo}")),
        f"{relatorio}/definition/version.json": _template("version.json"),
        f"{relatorio}/definition/report.json": _template("report.json"),
        f"{relatorio}/definition/pages/pages.json": _template("pages.json", pagina=pagina),
        f"{relatorio}/definition/pages/{pagina}/page.json": _template("page.json", pagina=pagina),
    }

    if opcoes.calendario:
        data = next((c.nome for c in cols if c.tipo_tmdl == "dateTime" and c.subtipo_data == "Date"), None)
        if data is None:
            raise ExportError("A tabela calendário precisa de uma coluna de data, e esta tabela não tem.")
        if tabela == CALENDARIO:
            raise ExportError(
                f"A tabela já se chama {CALENDARIO!r}; renomeie a receita para exportar o calendário."
            )
        tags = {
            f"tag_{t}": _guid("calendario", nome, t)
            for t in ("tabela", "data", "ano", "mes", "nome_mes", "mes_abreviado", "trimestre", "ano_mes")
        }
        arquivos[f"{modelo}/definition/tables/{_arquivo(CALENDARIO)}.tmdl"] = _template(
            "calendario.tmdl", calendario=tmdl_nome(CALENDARIO), coluna_data=dax_coluna(tabela, data), **tags
        )
        arquivos[f"{modelo}/definition/relationships.tmdl"] = _template(
            "relationships.tmdl",
            tag_relacao=_guid("relacao", nome),
            de=f"{tmdl_nome(tabela)}.{tmdl_nome(data)}",
            para=f"{tmdl_nome(CALENDARIO)}.Data",
        )
        tabelas.append(CALENDARIO)

    arquivos[f"{modelo}/definition/model.tmdl"] = _template(
        "model.tmdl",
        ordem_consultas=json.dumps([*parametros, tabela], ensure_ascii=False, separators=(",", ":")),
        refs="\n".join(f"ref table {tmdl_nome(t)}" for t in tabelas),
    )
    return arquivos


def parametros_pbip(recipe: Recipe, caminho: str, extras: dict[str, str] | None = None) -> dict[str, str]:
    """``CaminhoArquivo`` e os outros parâmetros que os passos usam."""
    extras = extras or {}
    nomes = dict.fromkeys(p for s in recipe.active_steps for p in s.m_parameters)
    return {PARAMETRO: caminho, **{n: extras.get(n, "") for n in nomes}}


def escrever_pasta(arquivos: dict[str, str], prefixo: str, destino: Path) -> None:
    """Grava em ``destino`` os arquivos de ``arquivos`` que ficam sob
    ``prefixo`` (``<nome>.SemanticModel`` ou ``<nome>.Report``)."""
    if destino.exists():
        shutil.rmtree(destino)
    for caminho, texto in arquivos.items():
        if caminho.startswith(prefixo + "/"):
            alvo = destino / caminho[len(prefixo) + 1 :]
            alvo.parent.mkdir(parents=True, exist_ok=True)
            # UTF-8 sem BOM e CRLF, como o Power BI Desktop grava.
            alvo.write_text(texto, encoding="utf-8", newline="\r\n")


def escrever_arquivo(texto: str, destino: Path) -> None:
    destino.write_text(texto, encoding="utf-8", newline="\r\n")


__all__ = [
    "CALENDARIO",
    "OpcoesPbip",
    "colunas",
    "escrever_arquivo",
    "escrever_pasta",
    "parameter_to_m",
    "parametros_pbip",
    "projeto_pbip",
    "tmdl_nome",
]

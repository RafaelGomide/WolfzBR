"""Exportação para o Tableau: extrato ``.hyper`` e fonte de dados ``.tds`` (F3.A).

- O ``.hyper`` é gravado pela Hyper API oficial (``tableauhyperapi``), que
  fica no extra ``wolfzbr[tableau]``: é um binário grande e de licença
  proprietária. Sem ele, ``hyper_disponivel()`` é falso e a interface mostra
  a opção desabilitada com ``INSTALAR``.
- Tipos: data vira ``DATE``, data e hora ``TIMESTAMP``, inteiro ``BIG_INT``,
  número ``DOUBLE``, texto ``TEXT``. Coluna de reais (``parse_brl``) vira
  ``NUMERIC(18,2)`` quando nenhum valor tem mais de dois decimais; senão
  fica ``DOUBLE``, para nunca arredondar em silêncio.
- A tabela vai para o Hyper pelo ``Inserter`` da Hyper API (1 milhão de
  linhas em poucos segundos).
- O ``.tds`` aponta para o ``.hyper`` pelo nome (os dois ficam juntos na
  mesma pasta), com nomes amigáveis (``valor_total`` -> ``Valor total``) e
  formatação brasileira: ``R$`` nas colunas de reais, percentual nas de
  ``parse_percent`` e datas em ``dd/mm/aaaa``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import quoteattr

import polars as pl

from wolfz.core.recipe import Recipe

INSTALAR = 'pip install "wolfzbr[tableau]"'
# Nome que o próprio Tableau dá ao esquema e à tabela de um extrato.
ESQUEMA = "Extract"
TABELA = "Extract"

Formato = Literal["brl", "percent"]

# Formatos de número do Tableau (atributo default-format do .tds).
_FORMATO_TDS: dict[str, str] = {
    "brl": 'c"R$ "#,##0.00;-"R$ "#,##0.00',
    "percent": "p0.00%",
    "date": "*dd/MM/yyyy",
    "datetime": "*dd/MM/yyyy HH:mm:ss",
}


def hyper_disponivel() -> bool:
    """A Hyper API está instalada (extra ``wolfzbr[tableau]``)."""
    return importlib.util.find_spec("tableauhyperapi") is not None


def formatos_colunas(recipe: Recipe) -> dict[str, Formato]:
    """Colunas da saída que são reais ou percentual, seguindo os passos:
    ``parse_brl`` marca, ``rename`` leva a marca para o nome novo e um
    passo que converte a coluna de novo tira a marca."""
    formatos: dict[str, Formato] = {}
    for step in recipe.active_steps:
        if step.op == "rename":
            formatos = {step.mapping.get(c, c): f for c, f in formatos.items()}  # type: ignore[attr-defined]
            continue
        cols = getattr(step, "cols", None)
        if not isinstance(cols, list):
            continue
        for c in cols:
            formatos.pop(c, None)
            if step.op == "parse_brl":
                formatos[c] = "brl"
            elif step.op == "parse_percent":
                formatos[c] = "percent"
    return formatos


def nome_amigavel(nome: str) -> str:
    """``valor_total`` -> ``Valor total``. Nome que já tem maiúscula ou
    espaço fica como está: alguém escolheu."""
    if any(ch.isupper() or ch == " " for ch in nome):
        return nome
    texto = " ".join(nome.replace("_", " ").split())
    return texto[:1].upper() + texto[1:] if texto else nome


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------


def _so_centavos(serie: pl.Series) -> bool:
    valores = serie.drop_nulls()
    if valores.is_empty():
        return True
    if not valores.is_finite().all() or valores.abs().max() >= 1e16:
        return False
    return bool(((valores * 100).round() - valores * 100).abs().max() < 1e-6)


def _tipo_hyper(serie: pl.Series, formato: Formato | None) -> Any:
    from tableauhyperapi import SqlType

    dtype = serie.dtype
    if dtype == pl.Date:
        return SqlType.date()
    if isinstance(dtype, pl.Datetime):
        return SqlType.timestamp()
    if dtype == pl.Time:
        return SqlType.time()
    if dtype == pl.Boolean:
        return SqlType.bool()
    if dtype.is_integer():
        return SqlType.big_int()
    if dtype.is_float():
        return SqlType.numeric(18, 2) if formato == "brl" and _so_centavos(serie) else SqlType.double()
    return SqlType.text()


def _texto(serie: pl.Series) -> pl.Series:
    return pl.Series(serie.name, [None if v is None else str(v) for v in serie], dtype=pl.String)


def _para_inserir(df: pl.DataFrame, tipos: dict[str, Any]) -> pl.DataFrame:
    """Valores no tipo que o ``Inserter`` aceita: sem fuso horário (a hora
    local da coluna, como no Excel), número não finito vira nulo, reais em
    ``Decimal`` e o resto vira texto."""
    from tableauhyperapi import TypeTag

    colunas = []
    for nome, dtype in df.schema.items():
        c = pl.col(nome)
        if isinstance(dtype, pl.Datetime):
            colunas.append(c.dt.replace_time_zone(None) if dtype.time_zone else c)
        elif tipos[nome].tag == TypeTag.NUMERIC:
            colunas.append(c.round(2).cast(pl.Decimal(18, 2)))
        elif dtype.is_float():
            colunas.append(pl.when(c.is_finite()).then(c).otherwise(None).alias(nome))
        elif dtype in (pl.Date, pl.Time, pl.Boolean, pl.String) or dtype.is_integer():
            colunas.append(c)
        elif dtype.is_nested():  # lista ou struct: o texto do valor
            colunas.append(c.map_batches(_texto, return_dtype=pl.String))
        else:
            colunas.append(c.cast(pl.String))
    return df.select(colunas)


# ---------------------------------------------------------------------------
# Escritores
# ---------------------------------------------------------------------------


def escrever_hyper(df: pl.DataFrame, path: Path, formatos: dict[str, Formato] | None = None) -> None:
    """Grava ``df`` como extrato do Tableau em ``Extract.Extract``."""
    from tableauhyperapi import (
        Connection,
        CreateMode,
        HyperProcess,
        Inserter,
        TableDefinition,
        TableName,
        Telemetry,
    )

    formatos = formatos or {}
    tipos = {n: _tipo_hyper(df.get_column(n), formatos.get(n)) for n in df.columns}
    definicao = TableDefinition(
        TableName(ESQUEMA, TABELA), [TableDefinition.Column(n, t) for n, t in tipos.items()]
    )
    # log_config vazio: o hyperd não deixa hyperd.log na pasta atual.
    with (
        HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""}) as hyper,
        Connection(hyper.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as conexao,
    ):
        conexao.catalog.create_schema(ESQUEMA)
        conexao.catalog.create_table(definicao)
        if df.width and df.height:
            # Inserter, e não COPY de um Parquet: o external() do Hyper não
            # abre caminho com acento no Windows (C:/Users/João/...).
            with Inserter(conexao, definicao) as inserir:
                inserir.add_rows(_para_inserir(df, tipos).iter_rows())
                inserir.execute()


def _tipo_tds(dtype: pl.DataType) -> tuple[str, str, str]:
    """``datatype``, ``role`` e ``type`` da coluna no ``.tds``."""
    if dtype == pl.Date:
        return "date", "dimension", "ordinal"
    if isinstance(dtype, pl.Datetime):
        return "datetime", "dimension", "ordinal"
    if dtype == pl.Boolean:
        return "boolean", "dimension", "nominal"
    if dtype.is_integer():
        return "integer", "measure", "quantitative"
    if dtype.is_float():
        return "real", "measure", "quantitative"
    return "string", "dimension", "nominal"


def tds(df: pl.DataFrame, arquivo_hyper: str, formatos: dict[str, Formato] | None = None) -> str:
    """Fonte de dados do Tableau apontando para ``arquivo_hyper`` (na mesma
    pasta do ``.tds``), em português do Brasil."""
    formatos = formatos or {}
    colunas = []
    for nome, dtype in df.schema.items():
        datatype, role, tipo = _tipo_tds(dtype)
        formato = formatos.get(nome) if datatype == "real" else datatype
        atributos = [
            f"caption={quoteattr(nome_amigavel(nome))}",
            f"datatype='{datatype}'",
            f"name={quoteattr('[' + nome.replace(']', ']]') + ']')}",
            f"role='{role}'",
            f"type='{tipo}'",
        ]
        if formato in _FORMATO_TDS:
            atributos.insert(1, f"default-format={quoteattr(_FORMATO_TDS[formato])}")
        colunas.append(f"  <column {' '.join(atributos)} />")
    nome = quoteattr(Path(arquivo_hyper).stem)
    return "\n".join(
        [
            "<?xml version='1.0' encoding='utf-8' ?>",
            f"<datasource formatted-name={nome} inline='true' version='18.1'"
            " xmlns:user='http://www.tableausoftware.com/xml/user'>",
            "  <connection class='federated'>",
            "    <named-connections>",
            f"      <named-connection caption={nome} name='hyper.wolfz'>",
            "        <connection authentication='auth-none' author-locale='pt_BR' class='hyper'"
            f" dbname={quoteattr(arquivo_hyper)} default-settings='yes' schema='{ESQUEMA}' sslmode=''"
            f" tablename='{TABELA}' username='tableau_internal_user' />",
            "      </named-connection>",
            "    </named-connections>",
            f"    <relation connection='hyper.wolfz' name='{TABELA}' table='[{ESQUEMA}].[{TABELA}]'"
            " type='table' />",
            "  </connection>",
            "  <aliases enabled='yes' />",
            *colunas,
            "  <semantic-values>",
            "    <semantic-value key='[Country].[Name]' value='&quot;Brasil&quot;' />",
            "  </semantic-values>",
            "</datasource>",
            "",
        ]
    )


def escrever_tds(
    df: pl.DataFrame, path: Path, arquivo_hyper: str, formatos: dict[str, Formato] | None = None
) -> None:
    path.write_text(tds(df, arquivo_hyper, formatos), encoding="utf-8")


__all__ = [
    "INSTALAR",
    "escrever_hyper",
    "escrever_tds",
    "formatos_colunas",
    "hyper_disponivel",
    "nome_amigavel",
    "tds",
]

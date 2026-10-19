"""``normalize_municipio``: nome de município digitado -> município do IBGE.

O casamento (exato, abreviação, fuzzy com ``rapidfuzz``) fica em
``wolfz.br.municipios`` e só existe no motor. O M e o script Python não
refazem o fuzzy: fazem join exato com a tabela de-para
(``depara_municipios.csv``) que o WolfzBR exporta junto (ADR-7). Valor
que não está no de-para (apareceu no arquivo do mês seguinte) fica com
situação ``fora_do_depara``: a linha continua lá, não some.

Saída: três colunas novas ao lado da original, que fica como veio:
``<col>_codigo_ibge`` (7 dígitos), ``<col>_nome_ibge`` (nome oficial) e
``<col>_status`` (exato, abreviacao, fuzzy, manual, revisar,
sem_correspondencia). ``revisar`` e ``sem_correspondencia`` não têm
código: nada é aplicado em silêncio.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import polars as pl
from pydantic import Field, field_validator

from wolfz.br.geo import normalize_uf
from wolfz.br.municipios import LIMIAR_PADRAO, casar_municipio, por_codigo
from wolfz.br.municipios import sugestoes as municipios_parecidos
from wolfz.core.recipe import Op, register_op
from wolfz.core.text import clean_text
from wolfz.export.depara import ARQUIVO_DEPARA
from wolfz.export.m import m_field, m_list, m_text
from wolfz.ops import m_br
from wolfz.ops.br import map_unique

PARAMETRO_DEPARA = "CaminhoDeparaMunicipios"

SAIDAS = ("codigo_ibge", "nome_ibge", "status")
DEPARA_SCHEMA = {
    "passo": pl.String,
    "valor": pl.String,
    "uf": pl.String,
    "codigo_ibge": pl.String,
    "nome_ibge": pl.String,
    "status": pl.String,
    "nota": pl.Float64,
    "sugestao": pl.String,
}


# ---------------------------------------------------------------------------
# Join com o de-para (copiado para o script Python exportado)
# ---------------------------------------------------------------------------


def juntar_depara(lf: pl.LazyFrame, depara: pl.LazyFrame, col: str, uf_col: str | None) -> pl.LazyFrame:
    """Acrescenta ``<col>_codigo_ibge``, ``<col>_nome_ibge`` e
    ``<col>_status`` pelo de-para (colunas valor, uf, codigo_ibge,
    nome_ibge, status). A chave é o valor limpo (``clean_text``) e a UF
    padronizada (vazia sem coluna de UF). Valor fora do de-para fica com
    status ``fora_do_depara``; valor vazio fica sem nada."""
    uf = pl.col(uf_col).cast(pl.String).map_elements(normalize_uf, return_dtype=pl.String) if uf_col else None
    chaves = lf.with_columns(
        pl.col(col).cast(pl.String).map_elements(clean_text, return_dtype=pl.String).alias("__valor"),
        (uf if uf is not None else pl.lit(None, pl.String)).fill_null("").alias("__uf"),
    )
    tabela = depara.select(
        pl.col("valor").alias("__valor"),
        pl.col("uf").fill_null("").alias("__uf"),
        *(pl.col(s).alias(f"{col}_{s}") for s in ("codigo_ibge", "nome_ibge", "status")),
    )
    status = f"{col}_status"
    return (
        chaves.join(tabela, on=["__valor", "__uf"], how="left", maintain_order="left")
        .with_columns(
            pl.when(pl.col("__valor").is_not_null() & pl.col(status).is_null())
            .then(pl.lit("fora_do_depara"))
            .otherwise(pl.col(status))
            .alias(status)
        )
        .drop("__valor", "__uf")
    )


def aplicar_depara_municipios(
    lf: pl.LazyFrame, passo: str, col: str, uf_col: str | None, caminho: str
) -> pl.LazyFrame:
    """Lê o de-para exportado pelo WolfzBR e aplica o do ``passo``."""
    depara = pl.read_csv(caminho, separator=";", infer_schema=False).filter(pl.col("passo") == passo)
    return juntar_depara(lf, depara.lazy(), col, uf_col)


# ---------------------------------------------------------------------------
# M
# ---------------------------------------------------------------------------

# clean_text: espaços normalizados; marcador de ausência vira null.
_M_LIMPO = """
(v as any) as nullable text => if v = null or WolfzNulo(v) then null else WolfzEspacos(Text.From(v, "en-US"))
"""


@register_op
class NormalizeMunicipio(Op):
    """Casa o nome do município com a lista oficial do IBGE e cria
    ``<col>_codigo_ibge``, ``<col>_nome_ibge`` e ``<col>_status``, sem mexer
    na coluna original.

    Casa o nome exato (sem acento, caixa e pontuação), depois expande
    abreviações ('V. Velha', 'Sto.', 'S.') e por fim procura o mais parecido,
    só na UF da linha quando há ``uf_col``. Parecido com nota abaixo de
    ``threshold`` (0 a 100), ou nome que existe em mais de uma UF sem UF
    informada, fica com status ``revisar`` e sem código: confira na
    interface. O que você aceitar ou corrigir lá vai para ``manual``
    ("valor" ou "valor|UF" -> código IBGE; nulo marca que não tem
    correspondência)."""

    op: Literal["normalize_municipio"]
    m_label = "Municípios normalizados"
    full_checkpoint = True
    col: str
    uf_col: str | None = None
    threshold: int = Field(default=LIMIAR_PADRAO, ge=50, le=100)
    manual: dict[str, str | None] = Field(default_factory=dict)

    python_helpers = (aplicar_depara_municipios,)
    python_constants: ClassVar[dict[str, str]] = {
        "DEPARA_MUNICIPIOS": f'Path(__file__).with_name("{ARQUIVO_DEPARA}")',
    }
    m_parameters = (PARAMETRO_DEPARA,)
    m_helpers = {**m_br.BASE, "WolfzUf": m_br.UF, "WolfzLimpo": _M_LIMPO}  # noqa: RUF012
    examples = (
        {
            "step": {"col": "m", "uf_col": "uf"},
            "input": {
                "m": ["Vitória", "V. Velha", "Cachoeiro Itapemirim", "Xyzzz", None, "SERRA", "Vitória"],
                "uf": ["ES", "ES", "ES", "ES", "ES", "espírito santo", "ES"],
            },
            "expected": {
                "m": ["Vitória", "V. Velha", "Cachoeiro Itapemirim", "Xyzzz", None, "SERRA", "Vitória"],
                "uf": ["ES", "ES", "ES", "ES", "ES", "espírito santo", "ES"],
                "m_codigo_ibge": ["3205309", "3205200", "3201209", None, None, "3205002", "3205309"],
                "m_nome_ibge": [
                    "Vitória",
                    "Vila Velha",
                    "Cachoeiro de Itapemirim",
                    None,
                    None,
                    "Serra",
                    "Vitória",
                ],
                "m_status": ["exato", "abreviacao", "fuzzy", "revisar", None, "exato", "exato"],
            },
        },
        {
            "step": {
                "col": "m",
                "threshold": 98,
                "manual": {"Bom Jesus": "2201903", "Cidade X": None},
            },
            "input": {"m": ["Bom Jesus", "Vila Velhaa", "Cidade X", "São Paulo", "S. Mateus"]},
            "expected": {
                "m": ["Bom Jesus", "Vila Velhaa", "Cidade X", "São Paulo", "S. Mateus"],
                "m_codigo_ibge": ["2201903", None, None, "3550308", "3204906"],
                "m_nome_ibge": ["Bom Jesus", None, None, "São Paulo", "São Mateus"],
                "m_status": ["manual", "revisar", "sem_correspondencia", "exato", "abreviacao"],
            },
        },
    )

    @field_validator("manual")
    @classmethod
    def _codigos_existem(cls, manual: dict[str, str | None]) -> dict[str, str | None]:
        for chave, codigo in manual.items():
            if not chave.strip():
                raise ValueError("manual: chave vazia")
            if codigo is not None and por_codigo(codigo) is None:
                raise ValueError(f"manual: {codigo!r} ({chave!r}) não é um código de município do IBGE")
        return manual

    @property
    def saidas(self) -> list[str]:
        return [f"{self.col}_{s}" for s in SAIDAS]

    def _chaves(self) -> tuple[pl.Expr, pl.Expr]:
        """Chave do de-para: valor limpo e UF padronizada ("" sem UF)."""
        valor = pl.col(self.col).cast(pl.String).map_batches(map_unique(clean_text, pl.String), pl.String)
        if self.uf_col is None:
            return valor, pl.lit("")
        uf_norm = map_unique(normalize_uf, pl.String)
        return valor, pl.col(self.uf_col).cast(pl.String).map_batches(uf_norm, pl.String).fill_null("")

    def resolver(self, valor: str, uf: str) -> dict[str, Any]:
        """Linha do de-para de um valor (já limpo) e UF (padronizada ou "")."""
        linha: dict[str, Any] = {"passo": self.id, "valor": valor, "uf": uf}
        chave = f"{valor}|{uf}" if self.uf_col else valor
        if chave in self.manual:
            codigo = self.manual[chave]
            municipio = por_codigo(codigo) if codigo else None
            if municipio is None:
                return {**linha, "status": "sem_correspondencia"}
            return {**linha, "status": "manual", "codigo_ibge": municipio.codigo, "nome_ibge": municipio.nome}
        r = casar_municipio(valor, uf or None, self.threshold)
        if r is None:
            return {**linha, "status": "sem_correspondencia"}
        linha.update(status=r.status, nota=r.nota)
        if r.municipio is not None:
            linha.update(codigo_ibge=r.municipio.codigo, nome_ibge=r.municipio.nome)
        elif r.candidatos:
            m, _ = r.candidatos[0]
            linha["sugestao"] = f"{m.nome} ({m.uf})"
        return linha

    def revisao(self, lf: pl.LazyFrame, sugestoes: int = 5) -> list[dict[str, Any]]:
        """Valores distintos que chegam ao passo, com o casamento atual, a
        quantidade de linhas e as sugestões, para a revisão na interface:
        primeiro os que precisam de revisão, depois os mais frequentes."""
        valor, uf = self._chaves()
        contagem = (
            lf.select(valor.alias("valor"), uf.alias("uf"))
            .drop_nulls("valor")
            .group_by("valor", "uf")
            .agg(pl.len().alias("linhas"))
            .collect()
        )
        ordem = {s: i for i, s in enumerate(("revisar", "sem_correspondencia", "fuzzy", "manual"))}
        itens = []
        for v, u, linhas in contagem.iter_rows():
            linha = self.resolver(v, u)
            itens.append(
                {
                    "valor": v,
                    "uf": u or None,
                    "chave": f"{v}|{u}" if self.uf_col else v,
                    "linhas": linhas,
                    "status": linha["status"],
                    "codigo_ibge": linha.get("codigo_ibge"),
                    "nome_ibge": linha.get("nome_ibge"),
                    "nota": linha.get("nota"),
                    "sugestoes": [
                        {"codigo_ibge": m.codigo, "nome": m.nome, "uf": m.uf, "nota": nota}
                        for m, nota in municipios_parecidos(v, u or None, sugestoes)
                    ],
                }
            )
        return sorted(itens, key=lambda i: (ordem.get(i["status"], len(ordem)), -i["linhas"], i["valor"]))

    def depara(self, lf: pl.LazyFrame) -> pl.DataFrame:
        """De-para dos valores distintos que chegam a este passo."""
        valor, uf = self._chaves()
        chaves = lf.select(valor.alias("valor"), uf.alias("uf")).unique().drop_nulls("valor").collect()
        chaves = chaves.sort("valor", "uf")
        linhas = [self.resolver(v, u) for v, u in chaves.iter_rows()]
        return pl.DataFrame(linhas, schema=DEPARA_SCHEMA)

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        depara = self.depara(lf).lazy()
        valor, uf = self._chaves()
        tabela = depara.select(
            pl.col("valor").alias("__valor"),
            pl.col("uf").alias("__uf"),
            *(pl.col(s).alias(nome) for s, nome in zip(SAIDAS, self.saidas, strict=True)),
        )
        return (
            lf.with_columns(valor.alias("__valor"), uf.alias("__uf"))
            .join(tabela, on=["__valor", "__uf"], how="left", maintain_order="left")
            .drop("__valor", "__uf")
        )

    def to_python(self) -> str:
        args = f"{self.id!r}, {self.col!r}, {self.uf_col!r}, DEPARA_MUNICIPIOS"
        return f"lf = aplicar_depara_municipios(lf, {args})"

    def to_m(self, prev: str, name: str) -> str:
        codigo, nome, status = (m_text(s) for s in self.saidas)
        if self.uf_col is None:
            uf = 'each ""'
        else:
            uf = f'each let u = WolfzUf({m_field(self.uf_col)}) in if u = null then "" else u'
        csv = (
            f"Csv.Document(File.Contents({PARAMETRO_DEPARA}), "
            '[Delimiter = ";", Encoding = 65001, QuoteStyle = QuoteStyle.Csv])'
        )
        vazio = 'each if _ = "" then null else _, type nullable text'
        fora = (
            f"each if [__valor] <> null and Record.Field(_, {status}) = null "
            f'then "fora_do_depara" else Record.Field(_, {status})'
        )
        return f"""{name} = let
        // De-para exportado pelo WolfzBR (ADR-7): join exato, sem fuzzy no M.
        depara = Table.SelectRows(
            Table.PromoteHeaders({csv}, [PromoteAllScalars = true]),
            each [passo] = {m_text(self.id)}
        ),
        ordem = Table.AddIndexColumn({prev}, "__ordem", 0, 1),
        comValor = Table.AddColumn(
            ordem, "__valor", each WolfzLimpo({m_field(self.col)}), type nullable text
        ),
        comChave = Table.AddColumn(comValor, "__uf", {uf}, type text),
        juntas = Table.NestedJoin(
            comChave, {{"__valor", "__uf"}}, depara, {{"valor", "uf"}}, "__depara", JoinKind.LeftOuter
        ),
        abertas = Table.ExpandTableColumn(
            juntas, "__depara", {m_list(SAIDAS)}, {{{codigo}, {nome}, {status}}}
        ),
        semVazio = Table.TransformColumns(abertas, {{{{{codigo}, {vazio}}}, {{{nome}, {vazio}}}}}),
        comStatus = Table.ReplaceValue(
            semVazio, each Record.Field(_, {status}), {fora}, Replacer.ReplaceValue, {{{status}}}
        ),
        ordenadas = Table.Sort(comStatus, {{{{"__ordem", Order.Ascending}}}})
    in
        Table.RemoveColumns(ordenadas, {{"__ordem", "__valor", "__uf"}})"""

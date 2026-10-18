"""Operações de texto: espaços, caixa, acentos e substituição literal."""

from __future__ import annotations

import unicodedata
from typing import Literal

import polars as pl
from pydantic import Field

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_list, m_text

# Invisíveis removidos de qualquer posição: zero-width, joiner, BOM, hífen suave.
INVISIVEIS = "\u200b\u200c\u200d\u2060\ufeff\u00ad"
# Espaços aparados nas pontas: espaço, tab, quebras, não separável e afins.
ESPACOS = " \t\r\n\u00a0\u2007\u202f\u2009\u3000"


def _tabela_acentos() -> dict[str, str]:
    """Letra acentuada -> letra sem acento, de À (U+00C0) a ſ (U+017F).
    A tabela é fixa (e não ``unicodedata`` em tempo de execução) para o M
    usar exatamente a mesma."""
    tabela = {}
    for codigo in range(0xC0, 0x180):
        ch = chr(codigo)
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        if base != ch and base.isascii() and base.isalpha():
            tabela[ch] = base
    return tabela


ACENTOS = _tabela_acentos()


def _texto(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.String)


def _m_texto(expr: str) -> str:
    return f"if _ = null then null else {expr}"


@register_op
class Trim(Op):
    """Apara espaços nas pontas, inclusive o espaço não separável (\\xa0)
    que vem de páginas web e PDFs, e remove caracteres invisíveis
    (zero-width, BOM, hífen suave) de qualquer posição. Com
    ``collapse_spaces``, espaços repetidos no meio viram um só."""

    op: Literal["trim"]
    m_label = "Texto aparado"
    cols: list[str] = Field(min_length=1)
    collapse_spaces: bool = False

    examples = (
        {
            "step": {"cols": ["nome"]},
            "input": {"nome": ["  Ana ", "\u00a0Bia\u200b", "Car  la\t", None, "   "]},
            "expected": {"nome": ["Ana", "Bia", "Car  la", None, ""]},
        },
        {
            "step": {"cols": ["nome"], "collapse_spaces": True},
            "input": {"nome": [" São \u00a0 Paulo ", "a\t\tb"]},
            "expected": {"nome": ["São Paulo", "a b"]},
        },
    )

    def _expr(self) -> str:
        expr = f"pl.col(c).cast(pl.String).str.replace_all({'[' + INVISIVEIS + ']'!r}, '')"
        if self.collapse_spaces:
            expr += f".str.replace_all({'[' + ESPACOS + ']+'!r}, ' ')"
        return expr + f".str.strip_chars({ESPACOS!r})"

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        def expr(c: str) -> pl.Expr:
            e = _texto(c).str.replace_all(f"[{INVISIVEIS}]", "")
            if self.collapse_spaces:
                e = e.str.replace_all(f"[{ESPACOS}]+", " ")
            return e.str.strip_chars(ESPACOS).alias(c)

        return lf.with_columns(expr(c) for c in self.cols)

    def to_python(self) -> str:
        return f"lf = lf.with_columns({self._expr()}.alias(c) for c in {self.cols!r})"

    def to_m(self, prev: str, name: str) -> str:
        sem_invisiveis = f"Text.Remove(Text.From(_), {m_list(INVISIVEIS)})"
        if self.collapse_spaces:
            partes = f"Text.SplitAny({sem_invisiveis}, {m_text(ESPACOS)})"
            corpo = f'Text.Combine(List.Select({partes}, each _ <> ""), " ")'
        else:
            corpo = f"Text.Trim({sem_invisiveis}, {m_list(ESPACOS)})"
        transforms = ", ".join(
            f"{{{m_text(c)}, each {_m_texto(corpo)}, type nullable text}}" for c in self.cols
        )
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"


@register_op
class Case(Op):
    """Maiúsculas (``upper``), minúsculas (``lower``) ou a primeira letra
    de cada palavra em maiúscula (``title``)."""

    op: Literal["case"]
    m_label = "Maiúsculas e minúsculas"
    cols: list[str] = Field(min_length=1)
    mode: Literal["upper", "lower", "title"]

    examples = (
        {
            "step": {"cols": ["a"], "mode": "upper"},
            "input": {"a": ["são paulo", None]},
            "expected": {"a": ["SÃO PAULO", None]},
        },
        {"step": {"cols": ["a"], "mode": "lower"}, "input": {"a": ["ÉRICA"]}, "expected": {"a": ["érica"]}},
        {
            "step": {"cols": ["a"], "mode": "title"},
            "input": {"a": ["JOÃO DA SILVA", "vila velha"]},
            "expected": {"a": ["João Da Silva", "Vila Velha"]},
        },
    )

    _POLARS = {"upper": "to_uppercase", "lower": "to_lowercase", "title": "to_titlecase"}  # noqa: RUF012
    _M = {"upper": "Text.Upper", "lower": "Text.Lower", "title": "Text.Proper"}  # noqa: RUF012

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return lf.with_columns(getattr(_texto(c).str, self._POLARS[self.mode])().alias(c) for c in self.cols)

    def to_python(self) -> str:
        metodo = self._POLARS[self.mode]
        return (
            f"lf = lf.with_columns(pl.col(c).cast(pl.String).str.{metodo}().alias(c) for c in {self.cols!r})"
        )

    def to_m(self, prev: str, name: str) -> str:
        fn = self._M[self.mode]
        corpo = _m_texto(f"{fn}(Text.From(_))")
        transforms = ", ".join(f"{{{m_text(c)}, each {corpo}, type nullable text}}" for c in self.cols)
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"


_M_SEM_ACENTO = """
(t as text) as text =>
    let mapa = Record.FromList({valores}, {chaves})
    in Text.Combine(List.Transform(Text.ToList(t), each Record.FieldOrDefault(mapa, _, _)))
"""


@register_op
class RemoveAccents(Op):
    """Tira acentos e cedilha: 'São José' -> 'Sao Jose'. Mantém caixa e
    pontuação. Usa uma tabela fixa de letras latinas (À a ſ), a mesma no
    Polars e no M, que não tem função nativa para isso."""

    op: Literal["remove_accents"]
    m_label = "Acentos removidos"
    cols: list[str] = Field(min_length=1)

    m_helpers = {  # noqa: RUF012
        "WolfzSemAcento": _M_SEM_ACENTO.replace("{valores}", m_list(ACENTOS.values())).replace(
            "{chaves}", m_list(ACENTOS.keys())
        )
    }
    examples = (
        {
            "step": {"cols": ["m"]},
            "input": {"m": ["São José do Calçado", "ÁGUA DOCE", "Itaú-Ünião", None, "abc"]},
            "expected": {"m": ["Sao Jose do Calcado", "AGUA DOCE", "Itau-Uniao", None, "abc"]},
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        de, para = list(ACENTOS), list(ACENTOS.values())
        return lf.with_columns(
            _texto(c).str.normalize("NFC").str.replace_many(de, para).alias(c) for c in self.cols
        )

    def to_python(self) -> str:
        de, para = list(ACENTOS), list(ACENTOS.values())
        return (
            "lf = lf.with_columns(pl.col(c).cast(pl.String).str.normalize('NFC')"
            f".str.replace_many({de!r}, {para!r}).alias(c) for c in {self.cols!r})"
        )

    def to_m(self, prev: str, name: str) -> str:
        corpo = _m_texto("WolfzSemAcento(Text.From(_))")
        transforms = ", ".join(f"{{{m_text(c)}, each {corpo}, type nullable text}}" for c in self.cols)
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"


@register_op
class Replace(Op):
    """Substitui texto literal (não é regex: o M não tem regex nativa).

    Por padrão troca cada ocorrência de ``old`` dentro da célula. Com
    ``whole`` (ou com ``new`` nulo), troca só a célula inteira igual a
    ``old``: ``{"old": "31.12.9999", "new": null}`` apaga a data sentinela."""

    op: Literal["replace"]
    m_label = "Valor substituído"
    cols: list[str] = Field(min_length=1)
    old: str = Field(min_length=1)
    new: str | None
    whole: bool = False

    examples = (
        {
            "step": {"cols": ["v"], "old": " ", "new": ""},
            "input": {"v": ["95 626 753", "12", None]},
            "expected": {"v": ["95626753", "12", None]},
        },
        {
            "step": {"cols": ["d"], "old": "31.12.9999", "new": None},
            "input": {"d": ["31.12.9999", "01.02.2024", "31.12.99999"]},
            "expected": {"d": [None, "01.02.2024", "31.12.99999"]},
        },
        {
            "step": {"cols": ["s"], "old": "N/I", "new": "não informado", "whole": True},
            "input": {"s": ["N/I", "N/I X", None]},
            "expected": {"s": ["não informado", "N/I X", None]},
        },
    )

    @property
    def _inteira(self) -> bool:
        return self.whole or self.new is None

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        if self._inteira:
            novo = pl.lit(self.new, dtype=pl.String)
            return lf.with_columns(
                pl.when(_texto(c) == self.old).then(novo).otherwise(_texto(c)).alias(c) for c in self.cols
            )
        return lf.with_columns(
            _texto(c).str.replace_all(self.old, self.new, literal=True).alias(c) for c in self.cols
        )

    def to_python(self) -> str:
        texto = "pl.col(c).cast(pl.String)"
        if self._inteira:
            novo = f"pl.lit({self.new!r}, dtype=pl.String)"
            expr = f"pl.when({texto} == {self.old!r}).then({novo}).otherwise({texto})"
        else:
            expr = f"{texto}.str.replace_all({self.old!r}, {self.new!r}, literal=True)"
        return f"lf = lf.with_columns({expr}.alias(c) for c in {self.cols!r})"

    def to_m(self, prev: str, name: str) -> str:
        novo = "null" if self.new is None else m_text(self.new)
        if self._inteira:
            corpo = f"if _ <> null and Text.From(_) = {m_text(self.old)} then {novo} else _"
        else:
            corpo = _m_texto(f"Text.Replace(Text.From(_), {m_text(self.old)}, {novo})")
        transforms = ", ".join(f"{{{m_text(c)}, each {corpo}}}" for c in self.cols)
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"

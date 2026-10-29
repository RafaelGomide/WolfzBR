"""Juntar abas e arquivos numa tabela só (F3 da 1.1, ADR-11 e ADR-12).

A receita roda inteira em cada parte (aba ou arquivo) e as tabelas são
empilhadas no fim, como o "Combinar arquivos" do Power Query. Empilhar segue
regras que nunca juntam nada em silêncio (D4):

- colunas casadas pelo nome **exato** (``pl.concat(how="diagonal")``);
- coluna que falta numa parte fica vazia nas linhas dela, com aviso;
- nome que só difere em espaço ou caixa vira duas colunas, com aviso;
- tipo diferente entre partes é erro, com a coluna e as duas partes;
- a coluna de origem (só o nome da aba ou do arquivo) vem em primeiro, e
  não pode ter o nome de uma coluna da tabela.

``teto_de_juntar`` recusa, antes de ler, um lote que passa do orçamento de
memória (R3).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from wolfz.core.ingest.excel import SheetInfo
from wolfz.core.ingest.limits import DEFAULT_LIMITS, Limits, _fmt_mb
from wolfz.core.text import normalize_key

# R3: o que é juntado fica inteiro na memória antes de gravar.
MAX_PARTES = 1000

__all__ = [
    "MAX_PARTES",
    "Divergencia",
    "ErroAoJuntar",
    "Juncao",
    "abas_a_juntar",
    "casa_inteira",
    "empilhar",
    "teto_de_juntar",
]


class ErroAoJuntar(Exception):
    """As partes não podem ser empilhadas: tipo diferente entre partes,
    coluna de origem repetida, nenhuma aba, teto de memória. A mensagem é
    para o usuário e não tem valor de célula."""

    def __init__(self, titulo: str, mensagem: str):
        super().__init__(mensagem)
        self.titulo = titulo
        self.mensagem = mensagem


@dataclass(frozen=True)
class Divergencia:
    """O que uma parte tem de diferente das outras: colunas que faltam,
    colunas a mais e nomes quase iguais (só espaço ou caixa)."""

    parte: str
    falta: tuple[str, ...] = ()
    a_mais: tuple[str, ...] = ()
    quase_iguais: tuple[tuple[str, str], ...] = ()  # (o nome nesta parte, o nome nas outras)

    def to_dict(self) -> dict[str, object]:
        return {
            "parte": self.parte,
            "falta": list(self.falta),
            "a_mais": list(self.a_mais),
            "quase_iguais": [{"nesta": a, "nas_outras": b} for a, b in self.quase_iguais],
        }


@dataclass(frozen=True)
class Juncao:
    tabela: pl.DataFrame
    divergencias: tuple[Divergencia, ...] = field(default_factory=tuple)


def abas_a_juntar(abas: list[SheetInfo], regex: str | None) -> tuple[list[str], list[str]]:
    """As abas que entram, na ordem do arquivo, e as ocultas que ficaram de
    fora (as que entrariam se fossem visíveis). Aba oculta (``hidden`` ou
    ``very_hidden``) nunca entra (R6, D11). Com ``regex``, só as que casam
    inteiras com ela (``re.fullmatch``)."""

    casam = casa_inteira([a.name for a in abas], regex) if regex is not None else [True] * len(abas)
    entram = [a.name for a, c in zip(abas, casam, strict=True) if c and not a.hidden]
    return entram, [a.name for a, c in zip(abas, casam, strict=True) if c and a.hidden]


def casa_inteira(nomes: list[str], regex: str) -> list[bool]:
    """Quais nomes casam inteiros com ``regex``. Usa o motor de regex do
    Polars (Rust), que não volta atrás: um padrão catastrófico vindo de uma
    receita de terceiro, como ``(a+)+$``, termina em tempo linear (R5)."""
    return pl.Series(nomes, dtype=pl.String).str.contains(f"^(?:{regex})$").fill_null(False).to_list()


def _quase(nome: str) -> str:
    return normalize_key(nome)


def empilhar(partes: list[tuple[str, pl.DataFrame]], origem: str | None) -> Juncao:
    """Empilha as tabelas de cada parte, na ordem dada. ``origem`` é o nome
    da coluna com o nome da parte (``None``: sem a coluna)."""
    if not partes:
        raise ErroAoJuntar("Nada para juntar", "Nenhuma aba ou arquivo para juntar.")
    todas: dict[str, None] = {}
    for _, df in partes:
        todas |= dict.fromkeys(df.columns)
    if origem is not None and origem in todas:
        raise ErroAoJuntar(
            "Coluna de origem repetida",
            f"A coluna de origem se chama {origem!r}, mas a tabela já tem uma coluna com esse nome. "
            "Escolha outro nome (origin_col na receita, --origin-col no wolfz run).",
        )
    # Tipo diferente entre partes: erro, nunca texto em silêncio.
    tipos: dict[str, tuple[pl.DataType, str]] = {}
    for nome, df in partes:
        for col, tipo in df.schema.items():
            if tipo == pl.Null:  # coluna inteira vazia: casa com qualquer tipo
                continue
            if col in tipos and tipos[col][0] != tipo:
                antes, onde = tipos[col]
                raise ErroAoJuntar(
                    "Tipos diferentes entre as partes",
                    f"A coluna {col!r} é {_tipo_br(antes)} em {onde} e {_tipo_br(tipo)} em {nome}. "
                    "Converta a coluna para o mesmo tipo nas duas, ou confira a aba.",
                )
            tipos.setdefault(col, (tipo, nome))
    divergencias = []
    if len(partes) > 1:
        for nome, df in partes:
            outras: dict[str, None] = {}
            for n2, d2 in partes:
                if n2 != nome:
                    outras |= dict.fromkeys(d2.columns)
            falta = [c for c in outras if c not in df.columns]
            a_mais = [c for c in df.columns if c not in outras]
            quase = [(c, o) for c in a_mais for o in falta if _quase(c) == _quase(o)]
            if falta or a_mais:
                divergencias.append(Divergencia(nome, tuple(falta), tuple(a_mais), tuple(quase)))
    frames = []
    for nome, df in partes:
        # Coluna inteira nula de uma parte vira o tipo das outras.
        df = df.with_columns(
            pl.col(c).cast(tipos[c][0]) for c, t in df.schema.items() if t == pl.Null and c in tipos
        )
        if origem is not None:
            df = df.select(pl.lit(nome, dtype=pl.String).alias(origem), pl.all())
        frames.append(df)
    return Juncao(pl.concat(frames, how="diagonal"), tuple(divergencias))


def _tipo_br(tipo: pl.DataType) -> str:
    if tipo == pl.String:
        return "texto"
    if tipo.is_numeric():
        return "número"
    if tipo == pl.Date:
        return "data"
    if isinstance(tipo, pl.Datetime):
        return "data e hora"
    if tipo == pl.Boolean:
        return "sim/não"
    return str(tipo)


def tamanho_declarado(path: Path) -> int:
    """Quanto o arquivo ocupa aberto: no ``.xlsx``/``.ods``, a soma
    descompactada que o índice do zip declara (sem descompactar nada); nos
    outros, o tamanho do arquivo."""
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                return sum(i.file_size for i in zf.infolist())
        except zipfile.BadZipFile:
            return path.stat().st_size
    return path.stat().st_size


def teto_de_juntar(arquivos: list[Path], limits: Limits = DEFAULT_LIMITS) -> None:
    """R3: recusa, antes de ler o primeiro arquivo inteiro, um lote que
    passa de ``MAX_PARTES`` arquivos ou cuja soma declarada passa de
    ``max_uncompressed_bytes`` (o mesmo teto de um arquivo só)."""
    if len(arquivos) > MAX_PARTES:
        raise ErroAoJuntar(
            "Arquivos demais para juntar",
            f"O lote tem {len(arquivos)} arquivos; para juntar numa saída só, o limite é {MAX_PARTES}. "
            "Rode sem --combine (um arquivo de saída por entrada).",
        )
    total = sum(tamanho_declarado(a) for a in arquivos if a.is_file())
    if total > limits.max_uncompressed_bytes:
        raise ErroAoJuntar(
            "Lote grande demais para juntar",
            f"Os arquivos somam {_fmt_mb(total)} abertos, acima do limite de "
            f"{_fmt_mb(limits.max_uncompressed_bytes)} para juntar numa saída só. "
            "Rode sem --combine (um arquivo de saída por entrada).",
        )

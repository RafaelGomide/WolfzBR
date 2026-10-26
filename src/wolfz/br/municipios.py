"""Município: casamento de nomes digitados com a lista oficial do IBGE.

A lista vem em ``wolfz/br/data/municipios.parquet``, gerada por
``scripts/atualizar_municipios.py`` a partir da API de localidades do IBGE
(fonte e data no ``NOTICE``). Funciona sem rede.

O casamento vai do mais seguro para o menos seguro (F2.C3):

1. **exato** — o nome normalizado (sem acento, caixa, pontuação) é o de um
   município, só um, da UF informada;
2. **abreviação** — expandindo abreviações conhecidas ('V. Velha' -> 'vila
   velha', 'Sto.' -> 'santo'), o nome casa com um único município;
3. **fuzzy** — o mais parecido (``rapidfuzz``), restrito à UF quando há UF,
   com nota a partir de ``limiar``.

Abaixo do limiar, ou com mais de um candidato, o valor fica para
**revisão**: nada é aplicado em silêncio. A revisão manual (aceitar ou
corrigir na interface) entra na receita e vale para as próximas execuções.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import polars as pl

from wolfz.br.geo import normalize_uf
from wolfz.core.text import clean_text, normalize_key

STATUS = ("exato", "abreviacao", "fuzzy", "manual", "revisar", "sem_correspondencia")
LIMIAR_PADRAO = 90

# Abreviações comuns em nomes de município. Uma abreviação pode ter mais de
# uma leitura ('S.' é São, Santa ou Santo): vale a que casar com um único
# município.
ABREVIACOES: dict[str, tuple[str, ...]] = {
    "v": ("vila",),
    "vl": ("vila",),
    "s": ("sao", "santa", "santo"),
    "sto": ("santo",),
    "sta": ("santa",),
    "n": ("nova", "nossa"),
    "nsa": ("nossa",),
    "sr": ("senhor",),
    "sra": ("senhora",),
    "pres": ("presidente",),
    "gov": ("governador",),
    "mal": ("marechal",),
    "cel": ("coronel",),
    "dr": ("doutor",),
    "gal": ("general",),
    "gen": ("general",),
    "pe": ("padre",),
    "fco": ("francisco",),
    "jd": ("jardim",),
    "mte": ("monte",),
    "pto": ("porto",),
}
_MAX_LEITURAS = 64


def chave_municipio(nome: object) -> str:
    """Nome para comparação: sem acento, minúsculo, sem apóstrofo e com a
    pontuação virando espaço. "Alta Floresta D'Oeste" -> 'alta floresta doeste'."""
    k = normalize_key(nome)
    k = re.sub("['`\u00b4\u2018\u2019]", "", k)  # apóstrofo e variantes
    return " ".join(re.sub(r"[^a-z0-9]+", " ", k).split())


@dataclass(frozen=True)
class Municipio:
    codigo: str
    nome: str
    uf: str


@dataclass(frozen=True)
class Resultado:
    """Resultado do casamento de um valor."""

    status: str
    municipio: Municipio | None = None
    nota: float | None = None
    candidatos: tuple[tuple[Municipio, float], ...] = ()


@cache
def tabela() -> pl.DataFrame:
    """Lista oficial: codigo_ibge, codigo_ibge_6, nome, nome_normalizado, uf."""
    caminho = files("wolfz.br") / "data" / "municipios.parquet"
    with caminho.open("rb") as f:
        return pl.read_parquet(f)


@cache
def _indice() -> tuple[dict[str, list[Municipio]], dict[str | None, list[tuple[str, Municipio]]]]:
    """Índice por nome normalizado e, para o fuzzy, a lista de nomes por UF
    (chave ``None``: o Brasil todo)."""
    por_nome: dict[str, list[Municipio]] = {}
    por_uf: dict[str | None, list[tuple[str, Municipio]]] = {None: []}
    for codigo, nome, chave, uf in (
        tabela().select("codigo_ibge", "nome", "nome_normalizado", "uf").iter_rows()
    ):
        m = Municipio(codigo, nome, uf)
        por_nome.setdefault(chave, []).append(m)
        por_uf.setdefault(uf, []).append((chave, m))
        por_uf[None].append((chave, m))
    return por_nome, por_uf


def _leituras(valor: str) -> list[str]:
    """Nomes possíveis expandindo as abreviações ('v. velha' -> 'vila velha')."""
    tokens = re.findall(r"[^\s.]+\.?", normalize_key(valor))
    opcoes = []
    for token in tokens:
        base = token.rstrip(".")
        chave = chave_municipio(base)
        opcoes.append((chave, *ABREVIACOES.get(chave, ())) if chave in ABREVIACOES else (chave,))
    leituras = []
    for combinacao in itertools.islice(itertools.product(*opcoes), _MAX_LEITURAS):
        leituras.append(" ".join(p for p in combinacao if p))
    return leituras


def _na_uf(municipios: list[Municipio], uf: str | None) -> list[Municipio]:
    return [m for m in municipios if uf is None or m.uf == uf]


def sugestoes(valor: object, uf: object = None, n: int = 5) -> list[tuple[Municipio, float]]:
    """Os ``n`` municípios mais parecidos (nota de 0 a 100), da UF quando
    informada."""
    from rapidfuzz import fuzz, process

    chave = chave_municipio(valor)
    if not chave:
        return []
    _, por_uf = _indice()
    escolhas = por_uf.get(normalize_uf(uf), []) if normalize_uf(uf) else por_uf[None]
    achados = process.extract(chave, [c for c, _ in escolhas], scorer=fuzz.ratio, limit=n)
    return [(escolhas[i][1], round(nota, 1)) for _, nota, i in achados]


def casar_municipio(valor: object, uf: object = None, limiar: int = LIMIAR_PADRAO) -> Resultado | None:
    """Casa um nome de município com a lista do IBGE. Valor vazio -> ``None``."""
    texto = clean_text(valor)
    if texto is None:
        return None
    sigla = normalize_uf(uf)
    por_nome, _ = _indice()

    exatos = _na_uf(por_nome.get(chave_municipio(texto), []), sigla)
    if len(exatos) == 1:
        return Resultado("exato", exatos[0], 100.0)
    if len(exatos) > 1:  # mesmo nome em várias UFs, e a UF não foi informada
        return Resultado("revisar", candidatos=tuple((m, 100.0) for m in exatos))

    achados = {m for leitura in _leituras(texto) for m in _na_uf(por_nome.get(leitura, []), sigla)}
    if len(achados) == 1:
        return Resultado("abreviacao", achados.pop(), 100.0)
    if len(achados) > 1:
        ordenados = sorted(achados, key=lambda m: (m.uf, m.nome))
        return Resultado("revisar", candidatos=tuple((m, 100.0) for m in ordenados))

    candidatos = sugestoes(texto, sigla)
    if not candidatos:
        return Resultado("sem_correspondencia")
    (melhor, nota), *resto = candidatos
    empate = bool(resto) and resto[0][1] == nota
    # Abreviação que a lista não expande ('A. Jequitibá', 'G. Celso Ramos'):
    # o parecido ignora a palavra abreviada e acha 'Jequitibá', que é outro
    # município. Sem saber a palavra, fica para revisão.
    abreviado = any(t.endswith(".") for t in re.findall(r"[^\s.]+\.?", normalize_key(texto)))
    if nota >= limiar and not empate and not abreviado:
        return Resultado("fuzzy", melhor, nota, tuple(candidatos))
    return Resultado("revisar", nota=nota, candidatos=tuple(candidatos))


def por_codigo(codigo: str) -> Municipio | None:
    """Município pelo código IBGE de 7 dígitos."""
    linha = tabela().filter(pl.col("codigo_ibge") == codigo)
    if linha.is_empty():
        return None
    return Municipio(linha["codigo_ibge"][0], linha["nome"][0], linha["uf"][0])


def buscar(texto: str, uf: str | None = None, n: int = 10) -> list[tuple[Municipio, float]]:
    """Busca para a correção manual: começa com o texto ou é parecido."""
    chave = chave_municipio(texto)
    if not chave:
        return []
    _, por_uf = _indice()
    escolhas = por_uf.get(normalize_uf(uf), []) if normalize_uf(uf) else por_uf[None]
    prefixo = [(m, 100.0) for c, m in escolhas if c.startswith(chave)]
    if len(prefixo) >= n:
        return sorted(prefixo, key=lambda x: x[0].nome)[:n]
    vistos = {m for m, _ in prefixo}
    parecidos = [(m, nota) for m, nota in sugestoes(texto, uf, n) if m not in vistos]
    return (sorted(prefixo, key=lambda x: x[0].nome) + parecidos)[:n]

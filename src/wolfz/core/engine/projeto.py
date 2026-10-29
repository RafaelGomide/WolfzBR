"""Projeto do workspace com uma ou várias abas (F3 da 1.1, ADR-11, D8).

Quem importa com "juntar abas" grava a grade de cada aba visível em
``abas/<i>.parquet`` (``import_file(all_sheets=True)``). A regra de abas da
receita (``source.combine_sheets``) escolhe, a cada pedido, quais delas
entram, a mesma regra que o ``wolfz run`` aplica no arquivo (D8). Cada aba
tem a própria cadeia de checkpoints (a chave do raw entra na chave do
passo), então o cache do preview não muda.

As funções daqui servem à API: com uma aba só, delegam ao que já existia
(``preview_project``, ``contagens_project``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import polars as pl

from wolfz.core.engine import StepError, collect, run
from wolfz.core.engine.cache import LIMITE_CACHE, Checkpoints, recolher
from wolfz.core.engine.juntar import ErroAoJuntar, Juncao, abas_a_juntar, casa_inteira, empilhar
from wolfz.core.engine.preview import (
    LIMITE_PAGINA,
    Page,
    _passos,
    _sub,
    contagens,
    contagens_project,
    preview,
)
from wolfz.core.engine.preview import preview_project as _preview_project
from wolfz.core.engine.reconcilia import PartReport, Reconciliation, juntar_contas
from wolfz.core.ingest.abas import padrao_de_aba
from wolfz.core.ingest.excel import SheetInfo
from wolfz.core.recipe import Recipe
from wolfz.core.workspace import PROJECT_FILE, RAW_FILE

__all__ = [
    "ParteDoProjeto",
    "contagens_do_projeto",
    "partes_do_projeto",
    "preview_do_projeto",
    "regra_das_abas",
    "tabela_do_projeto",
]


@dataclass(frozen=True)
class ParteDoProjeto:
    origem: str | None  # nome da aba; None quando a receita não junta abas
    raw: Path
    raw_key: str


def partes_do_projeto(pasta: Path, recipe: Recipe) -> tuple[list[ParteDoProjeto], tuple[str, ...]]:
    """As abas que a receita junta, na ordem do arquivo, e as ocultas que
    ficaram de fora. Sem ``combine_sheets``, só o ``raw.parquet``."""
    meta = json.loads((pasta / PROJECT_FILE).read_text(encoding="utf-8"))
    combine = recipe.source.combine_sheets
    if combine is None:
        return [ParteDoProjeto(None, pasta / RAW_FILE, meta["source"]["cache_key"])], ()
    gravadas = {a["name"]: a for a in meta.get("abas") or []}
    if not gravadas:
        raise ErroAoJuntar(
            "Projeto com uma aba só",
            "Este projeto foi importado com uma aba só. Para juntar abas, importe o arquivo de novo "
            "escolhendo juntar várias abas.",
        )
    abas = [
        SheetInfo(s["index"], s["name"], s["visibility"], s.get("rows"), s.get("columns"))
        for s in meta.get("sheets") or []
    ]
    nomes, ocultas = abas_a_juntar(abas, combine.sheets_regex)
    nomes = [n for n in nomes if n in gravadas]
    if not nomes:
        todas = ", ".join(a.name for a in abas) or "(nenhuma)"
        raise ErroAoJuntar(
            "Nenhuma aba para juntar", f"Nenhuma aba casa com a regra da receita. Abas do arquivo: {todas}."
        )
    partes = [ParteDoProjeto(n, pasta / gravadas[n]["file"], gravadas[n]["cache_key"]) for n in nomes]
    return partes, tuple(ocultas)


def _na_aba(parte: ParteDoProjeto, exc: StepError) -> StepError:
    if parte.origem is not None:
        exc.message = f"Na aba {parte.origem}: {exc.message}"
        exc.args = (exc.message,)
    return exc


def _origem(recipe: Recipe) -> str | None:
    combine = recipe.source.combine_sheets
    return combine.origin_col if combine is not None else None


def _juncao_dos_esquemas(partes: list[ParteDoProjeto], recipe: Recipe, step: str | None) -> Juncao:
    """Empilha tabelas vazias com o esquema de cada aba depois de ``step``:
    dá a ordem das colunas, as divergências e o erro de tipo sem ler dados."""
    sub = _sub(recipe, _passos(recipe, step))
    vazias = []
    for parte in partes:
        try:
            esquema = run(sub, pl.scan_parquet(parte.raw)).collect_schema()
        except StepError as exc:
            raise _na_aba(parte, exc) from None
        vazias.append((parte.origem or "", pl.DataFrame(schema=esquema)))
    return empilhar(vazias, _origem(recipe))


def preview_do_projeto(
    pasta: Path,
    recipe: Recipe,
    step: str | None = None,
    offset: int = 0,
    limit: int = 200,
    limite_cache: int = LIMITE_CACHE,
) -> Page:
    """``preview`` de um projeto com uma ou várias abas. Com várias, a
    página atravessa as abas na ordem, com a coluna de origem em primeiro,
    e ``total_rows`` é a soma."""
    partes, _ = partes_do_projeto(pasta, recipe)
    if partes[0].origem is None:
        return _preview_project(pasta, recipe, step, offset, limit, limite_cache)
    if offset < 0 or not 1 <= limit <= LIMITE_PAGINA:
        raise ValueError(f"offset deve ser >= 0 e limit entre 1 e {LIMITE_PAGINA}")
    esquema = _juncao_dos_esquemas(partes, recipe, step).tabela.schema
    origem = _origem(recipe)
    cache = Checkpoints(pasta / "checkpoints")
    pedacos, inicio, gravou = [], 0, False
    total = 0
    for parte in partes:
        try:
            primeira = preview(parte.raw, parte.raw_key, recipe, step, 0, 1, cache)
            altura = primeira.total_rows
            gravou = gravou or bool(primeira.checkpoints_gravados)
            de, ate = max(offset, inicio), min(offset + limit, inicio + altura)
            if de < ate:
                pagina = preview(parte.raw, parte.raw_key, recipe, step, de - inicio, ate - de, cache).frame
                if origem is not None:
                    pagina = pagina.select(pl.lit(parte.origem, dtype=pl.String).alias(origem), pl.all())
                pedacos.append(pagina)
        except StepError as exc:
            raise _na_aba(parte, exc) from None
        inicio += altura
        total += altura
    # Uma aba sem uma coluna das outras: a coluna vem vazia nas linhas dela.
    alinhados = [
        p.select(
            pl.col(c).cast(t) if c in p.columns else pl.lit(None, dtype=t).alias(c)
            for c, t in esquema.items()
        )
        for p in pedacos
    ]
    frame = pl.concat(alinhados) if alinhados else pl.DataFrame(schema=esquema)
    if gravou:
        recolher(pasta.parent, limite_cache, protegidos={pasta})
    return Page(frame, total, offset)


def contagens_do_projeto(pasta: Path, recipe: Recipe, limite_cache: int = LIMITE_CACHE) -> Reconciliation:
    """A reconciliação de um projeto com uma ou várias abas: a de cada aba
    em ``parts`` e a soma por passo."""
    partes, ocultas = partes_do_projeto(pasta, recipe)
    if partes[0].origem is None:
        return contagens_project(pasta, recipe, limite_cache)
    cache = Checkpoints(pasta / "checkpoints")
    contas: list[PartReport] = []
    feitas: list[PartReport] = []
    for parte in partes:
        try:
            r = contagens(parte.raw, parte.raw_key, recipe, cache)
        except StepError as exc:
            if exc.contagem_parcial is not None:
                lidas, passos = exc.contagem_parcial
                lidas += sum(c.rows_read for c in feitas)
                exc.contagem_parcial = (lidas, passos)
            raise _na_aba(parte, exc) from None
        fora = tuple(replace(c, part=parte.origem) for c in r.outside_columns)
        conta = PartReport(r.rows_read, r.rows_written, r.steps, fora, r.area_ends, origin=parte.origem or "")
        contas.append(conta)
        feitas.append(conta)
    juncao = _juncao_dos_esquemas(partes, recipe, None)
    recolher(pasta.parent, limite_cache, protegidos={pasta})
    return juntar_contas(contas, sum(c.rows_written for c in contas), juncao.divergencias, ocultas)


def tabela_do_projeto(pasta: Path, recipe: Recipe, step: str | None = None) -> pl.DataFrame:
    """A tabela inteira depois de ``step`` (perfil, sugestões, exportação),
    com as abas empilhadas quando a receita junta abas."""
    partes, _ = partes_do_projeto(pasta, recipe)
    sub = _sub(recipe, _passos(recipe, step))
    tabelas = []
    for parte in partes:
        raw = pl.scan_parquet(parte.raw)
        try:
            try:
                tabela = run(sub, raw).collect()
            except StepError:
                raise
            except Exception:
                collect(sub, raw)  # aponta o passo culpado (StepError)
                raise
        except StepError as exc:
            raise _na_aba(parte, exc) from None
        tabelas.append((parte.origem or "", tabela))
    if partes[0].origem is None:
        return tabelas[0][1]
    return empilhar(tabelas, _origem(recipe)).tabela


def regra_das_abas(
    escolhidas: list[str], visiveis: list[str], aba_da_receita: str | None = None
) -> str | None:
    """A ``sheets_regex`` que escolhe exatamente ``escolhidas`` entre as
    abas ``visiveis`` do arquivo atual (D8: o que se vê na tela é o que o
    ``run`` grava). ``None`` quando são todas as visíveis.

    Prefere o padrão do mês (``padrao_de_aba``), que também aceita as abas
    dos próximos arquivos e vira molde no M, quando ele escolhe exatamente
    as mesmas abas; senão, a lista dos nomes."""
    if not escolhidas:
        raise ValueError("escolha pelo menos uma aba")
    faltam = [n for n in escolhidas if n not in visiveis]
    if faltam:
        raise ValueError(f"abas que não existem ou estão ocultas: {', '.join(faltam)}")
    if set(escolhidas) == set(visiveis):
        return None
    for base in [aba_da_receita, *escolhidas]:
        if base and (padrao := padrao_de_aba(base)):
            casam = {n for n, c in zip(visiveis, casa_inteira(visiveis, padrao), strict=True) if c}
            if casam == set(escolhidas):
                return padrao
    return "|".join(re.escape(n) for n in escolhidas)

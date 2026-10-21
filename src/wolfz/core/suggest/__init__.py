"""Sugestões: regras heurísticas sobre o perfil que viram passos com confiança e motivo.

Cada regra é uma função registrada com ``@rule`` que olha a tabela (uma
amostra da tabela no fim da receita) e devolve zero ou mais ``Suggestion``:
os passos que ela propõe, a confiança (0 a 1) e o motivo em português. A
sugestão nunca altera a receita sozinha: o usuário aceita, edita ou rejeita
(§6.2 do design).

Uma regra que lança exceção é registrada no log e ignorada; as outras
continuam (§10.5 do design). Sugestão é bônus, não pode derrubar o fluxo.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import polars as pl

from wolfz.core.profile import ColumnProfile, profile_column
from wolfz.core.profile.column import sample_rows

log = logging.getLogger("wolfz.suggest")

AMOSTRA = 5_000
CONFIANCA_MINIMA = 0.6

# Ordem de aplicação no "aceitar todas": limpar antes de converter, e mudar
# a forma da tabela (duplicadas, despivotar) por último, quando as colunas
# que as outras sugestões citam já foram tratadas.
LIMPEZA, DOCUMENTO, CONVERSAO, FORMA, VERIFICACAO = 10, 20, 30, 40, 50


@dataclass(frozen=True)
class Suggestion:
    """Passos propostos por uma regra. ``kind="aviso"`` não tem passo: é um
    alerta (código com zero à esquerda que não deve virar número)."""

    rule: str
    steps: tuple[dict[str, Any], ...]
    confidence: float
    reason: str
    cols: tuple[str, ...] = ()
    kind: Literal["passo", "aviso"] = "passo"
    order: int = CONVERSAO

    @property
    def id(self) -> str:
        return f"{self.rule}:{'|'.join(self.cols)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule": self.rule,
            "steps": [dict(s) for s in self.steps],
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "cols": list(self.cols),
            "kind": self.kind,
            "order": self.order,
        }


@dataclass
class Contexto:
    """O que as regras recebem: a amostra da tabela e o perfil de cada
    coluna de texto (calculado uma vez, sob demanda)."""

    df: pl.DataFrame
    total: pl.DataFrame  # a tabela inteira, para o que a amostra não vê (duplicadas)
    passos: list[dict[str, Any]] = field(default_factory=list)  # a receita atual
    _perfis: dict[str, ColumnProfile] = field(default_factory=dict)

    @property
    def texto(self) -> list[str]:
        """Colunas ainda de texto (as já convertidas não interessam às regras)."""
        return [c for c, t in self.df.schema.items() if t == pl.String]

    def perfil(self, col: str) -> ColumnProfile:
        if col not in self._perfis:
            self._perfis[col] = profile_column(self.df[col])
        return self._perfis[col]

    def valores(self, col: str) -> list[str]:
        """Valores preenchidos da coluna, sem espaço nas pontas."""
        return [s for v in self.df[col].to_list() if v is not None and (s := str(v).strip())]


Regra = Callable[[Contexto], Iterable[Suggestion]]
_REGRAS: dict[str, Regra] = {}


def rule(fn: Regra) -> Regra:
    """Registra uma regra de sugestão. O nome da regra é o da função."""
    if fn.__name__ in _REGRAS and _REGRAS[fn.__name__] is not fn:
        raise ValueError(f"regra {fn.__name__!r} já registrada")
    _REGRAS[fn.__name__] = fn
    return fn


def registered_rules() -> dict[str, Regra]:
    return dict(_REGRAS)


def suggest(
    data: pl.DataFrame | pl.LazyFrame,
    rejected: Iterable[tuple[str, str | None]] = (),
    sample: int = AMOSTRA,
    steps: Iterable[dict[str, Any]] = (),
) -> list[Suggestion]:
    """Sugestões para a tabela, na ordem de aplicação e, dentro dela, da
    mais confiante para a menos. ``rejected`` são pares (regra, coluna) que
    o usuário rejeitou; coluna ``None`` rejeita a regra inteira. ``steps``
    são os passos da receita (as regras de verificação não repetem um
    ``assert`` que já está lá)."""
    import wolfz.core.suggest.regras  # noqa: F401  (registra as regras)

    df = data.collect() if isinstance(data, pl.LazyFrame) else data
    ctx = Contexto(sample_rows(df, sample), df, list(steps))
    recusadas = set(rejected)
    saida: list[Suggestion] = []
    for nome, regra in _REGRAS.items():
        try:
            achadas = list(regra(ctx))
        except Exception:
            log.exception("regra de sugestão %s falhou; ignorada", nome)
            continue
        for s in achadas:
            if s.confidence < CONFIANCA_MINIMA or (s.rule, None) in recusadas:
                continue
            if s.cols and all((s.rule, c) in recusadas for c in s.cols):
                continue
            if s.cols and any((s.rule, c) in recusadas for c in s.cols):
                s = _sem_colunas(s, {c for c in s.cols if (s.rule, c) in recusadas})
            saida.append(s)
    return _sem_conflito(sorted(saida, key=lambda s: (s.order, -s.confidence, s.rule, s.cols)))


def etapa(order: int) -> int:
    """Etapa do "aceitar todas" (a interface aplica uma por vez): limpar e
    converter, mudar a forma da tabela, verificar."""
    return 0 if order < FORMA else 1 if order < VERIFICACAO else 2


def _colunas_citadas(passo: dict[str, Any]) -> set[str]:
    citadas = set(passo.get("cols") or []) | set(passo.get("index") or [])
    citadas |= set(passo.get("types") or {}) | set(passo.get("mapping") or {})
    if isinstance(passo.get("col"), str):
        citadas.add(passo["col"])
    return citadas


def _colunas_tiradas(passo: dict[str, Any]) -> set[str]:
    if passo["op"] == "drop_cols" or (passo["op"] == "merge_cols" and not passo.get("keep")):
        return set(passo["cols"])
    if passo["op"] == "split_col":
        return {passo["col"]}
    return set()


def _sem_conflito(sugestoes: list[Suggestion]) -> list[Suggestion]:
    """Na mesma etapa, tira a sugestão que cita uma coluna que outra, antes
    dela, tira da tabela ("aceitar todas" aplicaria uma depois da outra e a
    segunda falharia). Ela volta, recalculada, depois que a primeira entra."""
    saida: list[Suggestion] = []
    tiradas: dict[int, set[str]] = {}
    despivotou: set[int] = set()  # dois despivotar seguidos: o segundo já não acha as colunas
    for s in sugestoes:
        e = etapa(s.order)
        ja = tiradas.setdefault(e, set())
        unpivot = any(p["op"] == "unpivot" for p in s.steps)
        if any(_colunas_citadas(p) & ja for p in s.steps) or (unpivot and e in despivotou):
            continue
        saida.append(s)
        for p in s.steps:
            ja |= _colunas_tiradas(p)
        if unpivot:
            despivotou.add(e)
    return saida


def _sem_colunas(s: Suggestion, tirar: set[str]) -> Suggestion:
    """A mesma sugestão sem as colunas rejeitadas (só para passos com ``cols``)."""
    cols = tuple(c for c in s.cols if c not in tirar)
    passos = tuple(
        {**p, "cols": [c for c in p["cols"] if c not in tirar]} if isinstance(p.get("cols"), list) else p
        for p in s.steps
    )
    return Suggestion(s.rule, passos, s.confidence, s.reason, cols, s.kind, s.order)


__all__ = ["Contexto", "Suggestion", "etapa", "registered_rules", "rule", "suggest"]

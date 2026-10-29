"""Reconciliação de linhas: quantas linhas cada passo tirou ou acrescentou
(ADR-10, F1 da 1.1).

A regra de alerta mora aqui, num lugar só. A CLI, a API e a interface só
mostram ``alert``; nenhuma delas recalcula. Nada aqui guarda valor de
célula: o ``to_dict()`` é o JSON do ``--report`` e pode ir para uma issue ou
para o cliente sem expor dado (R1). O cabeçalho das colunas fora da área
fica só no objeto (``OutsideColumn.header``), para o terminal e a interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import polars as pl

from wolfz.core.engine.juntar import Divergencia
from wolfz.core.recipe import Op

# Passo que tira mais que esta fração da entrada, e pelo menos MINIMO_ALERTA
# linhas, alerta. Ajustar aqui não muda o contrato (D1).
LIMITE_PERDA = 0.01
MINIMO_ALERTA = 10

Motivo = Literal["perda", "fora_da_area", "multiplicacao"]

__all__ = [
    "LIMITE_PERDA",
    "MINIMO_ALERTA",
    "OutsideColumn",
    "PartReport",
    "Reconciliation",
    "RunReport",
    "StepCount",
    "conta_passo",
    "juntar_contas",
    "somar",
]


@dataclass(frozen=True)
class StepCount:
    """Contagem de um passo ativo. ``rows_in - rows_out`` é o que ele tirou;
    ``empty_removed``, ``structure_removed`` e ``outside_area`` dizem quanto
    disso era linha vazia, título ou cabeçalho, e dado fora da área."""

    id: str
    op: str
    rows_in: int
    rows_out: int
    empty_removed: int = 0
    structure_removed: int = 0
    outside_area: int = 0
    factor: float | None = None  # só unpivot
    alert: bool = False
    reason: Motivo | None = None

    @property
    def lost(self) -> int:
        """Linhas de dado tiradas: não conta vazia nem estrutura."""
        return max(0, self.rows_in - self.rows_out - self.empty_removed - self.structure_removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "entrada": self.rows_in,
            "saida": self.rows_out,
            "vazias_removidas": self.empty_removed,
            "estrutura_removidas": self.structure_removed,
            "fora_da_area": self.outside_area,
            "fator": self.factor,
            "alerta": self.alert,
            "motivo": self.reason,
        }


@dataclass(frozen=True)
class OutsideColumn:
    """Coluna da grade fora da área do ``select_range`` com célula
    preenchida. ``header`` não vai para o ``to_dict()`` (D3)."""

    letter: str
    cells: int
    header: str | None
    step: str  # id do select_range
    area: str  # "A:H"
    part: str | None = None  # a aba ou o arquivo, quando a receita junta partes

    def to_dict(self) -> dict[str, Any]:
        return {"letra": self.letter, "celulas": self.cells}


@dataclass(frozen=True)
class Reconciliation:
    """A conta das linhas de uma execução: lidas, gravadas e por passo."""

    rows_read: int
    rows_written: int
    steps: tuple[StepCount, ...]
    outside_columns: tuple[OutsideColumn, ...] = ()
    # Do select_range com dado abaixo da área: última linha da área e última
    # linha preenchida da grade (linhas do Excel), para a mensagem do terminal.
    area_ends: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    # Juntar abas ou arquivos (F3): a conta de cada parte, o que cada parte
    # tem de diferente das outras e as abas ocultas que ficaram de fora.
    parts: tuple[PartReport, ...] = ()
    divergences: tuple[Divergencia, ...] = ()
    hidden_sheets: tuple[str, ...] = ()

    @property
    def lost(self) -> int:
        """Perda que conta para o ``--max-drop``: linhas de dado tiradas
        pelos passos, sem as vazias e sem a estrutura."""
        return sum(s.lost for s in self.steps)

    @property
    def alert(self) -> bool:
        """Algum passo alertou, ou a receita inteira tirou mais que o limite
        das linhas lidas (vários passos pequenos somados)."""
        return any(s.alert for s in self.steps) or _perda_grande(self.lost, self.rows_read)

    def to_dict(self) -> dict[str, Any]:
        """O JSON do ``--report`` e do ``GET /reconciliation``, sem valor de
        célula."""
        saida: dict[str, Any] = {
            "linhas_lidas": self.rows_read,
            "linhas_gravadas": self.rows_written,
            "alerta": self.alert,
            "passos": [s.to_dict() for s in self.steps],
            "colunas_fora_da_area": [c.to_dict() for c in self.outside_columns],
            "partes": [p.to_dict() for p in self.parts],
        }
        if self.divergences:
            saida["divergencias"] = [d.to_dict() for d in self.divergences]
        if self.hidden_sheets:
            saida["abas_ocultas"] = list(self.hidden_sheets)
        return saida


@dataclass(frozen=True)
class PartReport(Reconciliation):
    """A conta de uma aba ou de um arquivo juntado. ``origin`` é só o nome
    da aba ou do arquivo, nunca a pasta (D6)."""

    origin: str = field(kw_only=True)

    def to_dict(self) -> dict[str, Any]:
        return {"origem": self.origin, **super().to_dict()}


@dataclass(frozen=True)
class RunReport(Reconciliation):
    """Resultado de ``wolfz.run_report``: a tabela limpa (a mesma de
    ``wolfz.run``) e a conta das linhas."""

    table: pl.DataFrame = field(kw_only=True)


def juntar_contas(
    partes: list[PartReport],
    rows_written: int,
    divergences: tuple[Divergencia, ...] = (),
    hidden: tuple[str, ...] = (),
) -> Reconciliation:
    """A conta da tabela juntada: as linhas de todas as partes e, por passo,
    a soma das partes. O passo alerta se alertou em alguma parte (o motivo é
    o da primeira); o fator do unpivot é recalculado sobre as somas."""
    passos: dict[str, list[StepCount]] = {}
    for parte in partes:
        for s in parte.steps:
            passos.setdefault(s.id, []).append(s)
    somados = []
    for contas in passos.values():
        rows_in, rows_out = sum(s.rows_in for s in contas), sum(s.rows_out for s in contas)
        motivo = next((s.reason for s in contas if s.alert), None)
        somados.append(
            StepCount(
                id=contas[0].id,
                op=contas[0].op,
                rows_in=rows_in,
                rows_out=rows_out,
                empty_removed=sum(s.empty_removed for s in contas),
                structure_removed=sum(s.structure_removed for s in contas),
                outside_area=sum(s.outside_area for s in contas),
                factor=(rows_out / rows_in if rows_in else None) if contas[0].factor is not None else None,
                alert=motivo is not None,
                reason=motivo,
            )
        )
    return Reconciliation(
        sum(p.rows_read for p in partes),
        rows_written,
        tuple(somados),
        tuple(c for p in partes for c in p.outside_columns),
        {},
        tuple(partes),
        divergences,
        hidden,
    )


def somar(
    partes: list[PartReport],
    table: pl.DataFrame,
    divergences: tuple[Divergencia, ...] = (),
    hidden: tuple[str, ...] = (),
) -> RunReport:
    """``juntar_contas`` com a tabela juntada (``wolfz.run_report``)."""
    r = juntar_contas(partes, table.height, divergences, hidden)
    return RunReport(
        r.rows_read, r.rows_written, r.steps, r.outside_columns, {}, r.parts, divergences, hidden, table=table
    )


def _perda_grande(perda: int, base: int) -> bool:
    return perda >= MINIMO_ALERTA and perda > LIMITE_PERDA * base


def conta_passo(
    step: Op,
    rows_in: int,
    rows_out: int,
    *,
    unpivot_antes: bool = False,
    acima: int = 0,
    vazias_abaixo: int = 0,
    fora: int = 0,
    colunas_fora: int = 0,
) -> StepCount:
    """A contagem de um passo, com o alerta. ``unpivot_antes``: algum
    ``unpivot`` já rodou antes deste passo na receita. ``acima``,
    ``vazias_abaixo``, ``fora`` e ``colunas_fora`` vêm da
    ``contagem_da_area`` do ``select_range``."""
    efeito = step.efeito_linhas
    tirou = max(0, rows_in - rows_out)
    vazias = estrutura = fora_da_area = 0
    fator: float | None = None
    motivo: Motivo | None = None
    if step.op == "drop_empty_rows":
        vazias = tirou
    elif step.op == "select_range":
        estrutura, vazias, fora_da_area = acima, vazias_abaixo, fora
        if fora_da_area or colunas_fora:
            motivo = "fora_da_area"
    elif efeito == "estrutura":
        estrutura = tirou
    elif efeito == "remove" and _perda_grande(tirou, rows_in):
        motivo = "perda"
    if step.op == "unpivot":
        fator = rows_out / rows_in if rows_in else None
        if unpivot_antes:
            motivo = "multiplicacao"
    elif rows_out > rows_in:
        motivo = "multiplicacao"
    return StepCount(
        id=step.id,
        op=step.op,
        rows_in=rows_in,
        rows_out=rows_out,
        empty_removed=vazias,
        structure_removed=estrutura,
        outside_area=fora_da_area,
        factor=fator,
        alert=motivo is not None,
        reason=motivo,
    )

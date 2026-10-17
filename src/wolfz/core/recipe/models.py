"""Modelo da receita: ``Recipe``, ``Source``, ``SourceMatch`` e a base ``Op``.

A lista de passos é uma união discriminada pelo campo ``op``, montada a
partir das operações registradas com ``@register_op``. Como o catálogo só é
conhecido depois que ``wolfz.ops`` é importado, a validação de uma receita
vinda de arquivo passa por ``recipe_validator()``, que monta (e guarda em
cache) uma subclasse de ``Recipe`` com a união atual (§4.2 do design).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from functools import cache
from typing import Annotated, Any, ClassVar, Literal, Union, get_args, get_origin

import polars as pl
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    create_model,
    field_validator,
    model_validator,
)

STEP_ID_PATTERN = r"^s[1-9]\d*$"


class _Model(BaseModel):
    # Campo desconhecido é erro: um erro de digitação na receita nunca pode
    # ser ignorado em silêncio.
    model_config = ConfigDict(extra="forbid")


class Op(_Model, ABC):
    """Base de toda operação do catálogo.

    Cada subclasse declara ``op: Literal["nome"]``, os próprios parâmetros e
    as três traduções. Registre com ``@register_op``."""

    # Funções de wolfz.br que o script Python exportado precisa embutir. As
    # dependências (outras funções e constantes) são resolvidas sozinhas.
    # Passo caro de recalcular a cada página do preview (reordena ou junta a
    # tabela inteira, ou roda uma função Python por valor): o motor grava a
    # tabela inteira depois dele como checkpoint, e os passos seguintes
    # partem dali (§8.4 do design).
    full_checkpoint: ClassVar[bool] = False
    python_helpers: ClassVar[tuple[Callable[..., Any], ...]] = ()
    # Funções M auxiliares, declaradas uma vez no início da consulta: nome -> definição.
    m_helpers: ClassVar[dict[str, str]] = {}
    # Exemplos para o teste de equivalência e para a documentação. Cada um é
    # {"step": parâmetros do passo, "input": colunas de entrada} e, opcional,
    # "expected": colunas esperadas na saída. Toda operação do catálogo
    # precisa de pelo menos um.
    examples: ClassVar[tuple[dict[str, Any], ...]] = ()

    id: str = Field(pattern=STEP_ID_PATTERN, description="Identificador do passo: s1, s2, …")
    op: str

    @abstractmethod
    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        """Aplica o passo a um plano lazy do Polars."""

    @abstractmethod
    def to_m(self, prev: str, name: str) -> str:
        """Passo de Power Query M no formato ``name = expressão``, a partir
        do passo ``prev``."""

    @abstractmethod
    def to_python(self) -> str:
        """Linhas de script Python (Polars) equivalentes ao passo, operando
        sobre a variável ``lf`` (um ``LazyFrame``)."""


class SourceMatch(_Model):
    """Como reencontrar a fonte quando a receita é reaplicada a outro arquivo."""

    sheet_name_regex: str | None = Field(
        default=None, description="Regex para escolher a aba quando o nome muda (ex.: 'Vendas \\d{4}')."
    )

    @field_validator("sheet_name_regex")
    @classmethod
    def _regex_valida(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"regex inválida: {exc}") from None
        return value


class Source(_Model):
    type: Literal["excel", "csv", "ods"]
    sheet: str | None = None
    match: SourceMatch | None = None


class Recipe(_Model):
    """Receita: a fonte de verdade de tudo que é derivado do arquivo original.

    Construída em código, aceita instâncias de qualquer ``Op``. Vinda de
    arquivo ou de dicionário, use ``load_recipe``/``loads_recipe``, que
    validam os passos contra o catálogo registrado."""

    wolfz_version: str
    name: str = Field(min_length=1)
    created_at: datetime
    source: Source
    steps: list[SerializeAsAny[Op]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_unicos(self) -> Recipe:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"id de passo repetido: {step.id!r}")
            seen.add(step.id)
        return self


# ---------------------------------------------------------------------------
# Registro de operações
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[Op]] = {}


def _op_name(cls: type[Op]) -> str:
    annotation = cls.model_fields["op"].annotation
    args = get_args(annotation)
    if get_origin(annotation) is not Literal or len(args) != 1 or not isinstance(args[0], str):
        raise TypeError(f"{cls.__name__}: declare o campo como op: Literal['nome_da_operacao']")
    return args[0]


def register_op(cls: type[Op]) -> type[Op]:
    """Decorator que adiciona a operação ao catálogo.

    A partir daí ela entra na união discriminada dos passos e no JSON
    Schema da receita."""
    if not (isinstance(cls, type) and issubclass(cls, Op)) or cls is Op:
        raise TypeError("@register_op só aceita subclasses de Op")
    if cls.__abstractmethods__:
        missing = ", ".join(sorted(cls.__abstractmethods__))
        raise TypeError(f"{cls.__name__} não implementa: {missing}")
    name = _op_name(cls)
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"operação {name!r} já registrada por {_REGISTRY[name].__name__}")
    _REGISTRY[name] = cls
    recipe_validator.cache_clear()
    return cls


def registered_ops() -> dict[str, type[Op]]:
    """Cópia do catálogo atual: nome da operação -> classe."""
    return dict(_REGISTRY)


def _unknown_step(value: Any) -> Any:
    op = value.get("op") if isinstance(value, dict) else None
    raise ValueError(f"operação desconhecida: {op!r}" if op else "passo sem o campo 'op'")


@cache
def recipe_validator() -> type[Recipe]:
    """Subclasse de ``Recipe`` cujos passos são a união discriminada do
    catálogo registrado. Refeita quando uma operação nova é registrada."""
    ops = tuple(_REGISTRY.values())
    if ops:
        step: Any = Annotated[Union[ops], Field(discriminator="op")]  # noqa: UP007
    else:
        step = Annotated[Any, AfterValidator(_unknown_step)]
    model = create_model(
        "Recipe",
        __base__=Recipe,
        __module__=__name__,
        steps=(list[step], Field(default_factory=list)),
    )
    model.__doc__ = Recipe.__doc__
    return model

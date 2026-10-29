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
    SerializerFunctionWrapHandler,
    create_model,
    field_validator,
    model_serializer,
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
    # O que o passo faz com o número de linhas (ADR-10): ``remove`` (tira
    # linhas de dado), ``estrutura`` (recorta a grade, promove o cabeçalho),
    # ``multiplica`` (despivota) ou ``mantem``. A reconciliação só conta as
    # linhas depois dos passos que não são ``mantem``; um teste confere que
    # nenhum exemplo de uma op ``mantem`` muda o número de linhas.
    efeito_linhas: ClassVar[Literal["mantem", "remove", "estrutura", "multiplica"]] = "mantem"
    # Formato da receita em que a op apareceu (ADR-9). Uma receita com uma op
    # "1.1" é gravada como "1.1"; sem nenhuma, continua "1.0".
    desde: ClassVar[str] = "1.0"
    python_helpers: ClassVar[tuple[Callable[..., Any], ...]] = ()
    # Funções M auxiliares, declaradas uma vez no início da consulta: nome -> definição.
    m_helpers: ClassVar[dict[str, str]] = {}
    # Nome do passo na consulta M, no estilo do Power Query ("Colunas renomeadas").
    # Vazio: usa o nome da operação.
    m_label: ClassVar[str] = ""
    # Parâmetros M (consultas à parte) que o passo usa, além de CaminhoArquivo.
    m_parameters: ClassVar[tuple[str, ...]] = ()
    # Constantes do script Python exportado que o passo usa: nome -> expressão.
    python_constants: ClassVar[dict[str, str]] = {}
    # Exemplos para o teste de equivalência e para a documentação. Cada um é
    # {"step": parâmetros do passo, "input": colunas de entrada} e, opcional,
    # "expected": colunas esperadas na saída. Toda operação do catálogo
    # precisa de pelo menos um.
    examples: ClassVar[tuple[dict[str, Any], ...]] = ()

    id: str = Field(pattern=STEP_ID_PATTERN, description="Identificador do passo: s1, s2, …")
    op: str
    enabled: bool = Field(
        default=True, description="Passo ativo. Desativado, ele continua na receita, mas não roda."
    )

    @model_serializer(mode="wrap")
    def _omite_enabled(self, handler: SerializerFunctionWrapHandler) -> Any:
        # Só o passo desativado grava o campo: receitas que nunca desativaram
        # nada continuam com os mesmos bytes (e as mesmas chaves de cache).
        data = handler(self)
        if self.enabled and isinstance(data, dict):
            data.pop("enabled", None)
        return data

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


def _regex_de_aba(value: str | None) -> str | None:
    """A regex de nome de aba roda no motor do Polars (sem retrocesso, R5):
    precisa valer nele, que não aceita retrorreferência nem lookaround."""
    if value is not None:
        try:
            re.compile(value)
            pl.Series([""], dtype=pl.String).str.contains(f"^(?:{value})$")
        except (re.error, pl.exceptions.PolarsError) as exc:
            primeira = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise ValueError(f"regex inválida: {primeira}") from None
    return value


class SourceCombine(_Model):
    """Juntar abas de um arquivo numa tabela só (F3, ADR-11). A receita roda
    inteira em cada aba e as tabelas são empilhadas no fim, na ordem das
    abas no arquivo. Por isso ``dedupe`` e ``sort`` valem dentro de cada aba.
    Aba oculta nunca entra (R6). A receita escolhe só abas, nunca arquivos
    (R5)."""

    sheets_regex: str | None = Field(
        default=None,
        description="Sem padrão, todas as abas visíveis; com padrão, as que casam inteiras com ele.",
    )
    origin_col: str | None = Field(
        default="aba",
        min_length=1,
        description="Coluna com o nome da aba de cada linha, em primeiro lugar. null: sem a coluna.",
    )

    _regex_valida = field_validator("sheets_regex")(_regex_de_aba)

    @model_serializer(mode="wrap")
    def _grava_origem_nula(self, handler: SerializerFunctionWrapHandler) -> Any:
        # O dumps tira os campos None, mas "origin_col": null (coluna
        # desligada) precisa ficar no arquivo: sem o campo, vale "aba".
        data = handler(self)
        if isinstance(data, dict) and self.origin_col is None:
            data["origin_col"] = None
        return data


class Source(_Model):
    type: Literal["excel", "csv", "ods"]
    sheet: str | None = None
    match: SourceMatch | None = None
    combine_sheets: SourceCombine | None = Field(
        default=None,
        description="Juntar várias abas do arquivo numa tabela só (formato 1.1).",
        json_schema_extra={"desde": "1.1"},
    )

    @model_validator(mode="after")
    def _combine(self) -> Source:
        if self.combine_sheets is not None:
            if self.type == "csv":
                raise ValueError("combine_sheets junta abas de planilha; CSV não tem abas")
            if self.match is not None:
                raise ValueError("use combine_sheets ou match, não os dois")
        return self


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

    @property
    def active_steps(self) -> list[Op]:
        """Passos que rodam: todos, menos os desativados na interface."""
        return [s for s in self.steps if s.enabled]


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

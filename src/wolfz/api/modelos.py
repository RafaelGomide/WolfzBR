"""Modelos das respostas da API. Existem para o OpenAPI: o cliente
TypeScript da interface é gerado a partir dele (F1.H1). Os handlers
continuam devolvendo dicionários; o FastAPI valida contra estes modelos.

A receita fica como objeto livre (``dict``): o formato dela é o JSON
Schema da receita (``wolfz schema``), e os parâmetros de cada passo vêm de
``GET /ops``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Resposta(BaseModel):
    # Campo a mais no dicionário passa adiante: a resposta não perde
    # informação se o núcleo ganhar um campo antes do modelo.
    model_config = ConfigDict(extra="allow")


class Aba(_Resposta):
    index: int
    name: str
    visibility: str
    hidden: bool
    rows: int | None = None
    columns: int | None = None


class Deteccao(_Resposta):
    """Estrutura detectada, em linhas e letras do Excel."""

    cabecalho: list[int] | None = None
    dados: list[int]
    colunas: list[str]
    totais: list[int] = []
    fill_down: list[str] = []
    titulo: list[str] = []
    notas: list[str] = []


class Fonte(_Resposta):
    name: str
    format: str
    size: int
    sheet: str | None = None
    path: str | None = None
    uploaded: bool = False


class Raw(_Resposta):
    rows: int
    columns: list[str]


class Projeto(_Resposta):
    id: str
    name: str
    created_at: str
    source: Fonte
    sheets: list[Aba] = []
    raw: Raw
    recipe: dict[str, Any]
    etag: str


class ProjetoCriado(Projeto):
    reused_raw: bool
    detection: Deteccao | None = None


class ProjetoResumo(_Resposta):
    id: str
    name: str | None = None
    created_at: str | None = None
    format: str | None = None
    sheet: str | None = None
    rows: int | None = None
    open_here: bool
    open_elsewhere: bool


class Estrutura(_Resposta):
    structure: dict[str, Any]
    detection: Deteccao | None = None


class FormaValor(_Resposta):
    shape: str
    count: int


class PerfilColuna(_Resposta):
    name: str
    inferred_type: str
    type_rate: float
    rows: int
    nulls: int
    null_markers: int
    distinct: int
    top_shapes: list[FormaValor]
    examples: list[str]
    minimum: float | str | None = None
    maximum: float | str | None = None
    null_pct: float
    null_marker_pct: float


class Perfil(_Resposta):
    total_rows: int
    sampled_rows: int
    is_sample: bool
    columns: list[PerfilColuna]


class ColunaPreview(_Resposta):
    name: str
    dtype: str


class Pagina(_Resposta):
    columns: list[ColunaPreview]
    rows: list[list[Any]]
    total_rows: int
    offset: int


class ReceitaSalva(_Resposta):
    etag: str
    recipe: dict[str, Any]


class Exportacao(_Resposta):
    files: list[str]
    rows: int | None = None
    # Células de texto que começam com =, +, -, @… (None: só código exportado).
    formula_cells: int | None = None
    neutralized: bool = False


class Municipio(_Resposta):
    codigo_ibge: str
    nome: str
    uf: str
    nota: float | None = None


class ItemRevisaoMunicipio(_Resposta):
    """Valor distinto de uma coluna de município, com o casamento atual."""

    valor: str
    uf: str | None = None
    # Chave do ``manual`` do passo: "valor" ou "valor|UF".
    chave: str
    linhas: int
    status: str
    codigo_ibge: str | None = None
    nome_ibge: str | None = None
    nota: float | None = None
    sugestoes: list[Municipio]


class Operacao(_Resposta):
    op: str
    doc: str
    # "schema" é nome de método antigo do BaseModel; o campo usa alias.
    schema_: dict[str, Any] = Field(alias="schema")
    full_checkpoint: bool
    examples: list[dict[str, Any]]

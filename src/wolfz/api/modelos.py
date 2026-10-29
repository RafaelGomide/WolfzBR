"""Modelos das respostas da API. Existem para o OpenAPI: o cliente
TypeScript da interface é gerado a partir dele (F1.H1). Os handlers
continuam devolvendo dicionários; o FastAPI valida contra estes modelos.

A receita fica como objeto livre (``dict``): o formato dela é o JSON
Schema da receita (``wolfz schema``), e os parâmetros de cada passo vêm de
``GET /ops``."""

from __future__ import annotations

from typing import Any, Literal

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


class TabelaDetectada(_Resposta):
    """Uma das tabelas de uma aba com mais de uma (F2.D3)."""

    cabecalho: list[int] | None = None
    dados: list[int]
    colunas: list[str]
    # Passos da receita inicial para esta tabela (sem ``id``).
    passos: list[dict[str, Any]]


class Deteccao(_Resposta):
    """Estrutura detectada, em linhas e letras do Excel. ``tabelas`` só
    aparece quando a aba tem mais de uma; a receita inicial usa a principal."""

    cabecalho: list[int] | None = None
    dados: list[int]
    colunas: list[str]
    totais: list[int] = []
    fill_down: list[str] = []
    titulo: list[str] = []
    notas: list[str] = []
    tabelas: list[TabelaDetectada] = []


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


class ContagemPasso(_Resposta):
    """Linhas de um passo ativo (F1). ``entrada - saida`` é o que ele tirou;
    ``vazias_removidas``, ``estrutura_removidas`` (título, cabeçalho) e
    ``fora_da_area`` dizem quanto disso era o quê. ``alerta`` e ``motivo``
    vêm prontos: a interface não recalcula a regra."""

    id: str
    op: str
    entrada: int
    saida: int
    vazias_removidas: int
    estrutura_removidas: int
    fora_da_area: int
    fator: float | None = Field(description="Só no unpivot: saida / entrada.")
    alerta: bool
    motivo: Literal["perda", "fora_da_area", "multiplicacao"] | None


class ColunaForaDaArea(_Resposta):
    letra: str
    celulas: int = Field(description="Células preenchidas da coluna nas linhas da área.")
    cabecalho: str | None = Field(
        description="Texto da 1ª linha da área na coluna (só na interface; o --report não grava)."
    )
    passo: str = Field(description="O select_range que deixou a coluna de fora.")
    area: str = Field(description='Colunas da área, ex.: "A:H".')
    parte: str | None = Field(default=None, description="A aba, quando a receita junta abas.")


class Divergencia(_Resposta):
    """Colunas de uma aba que não batem com as das outras (F3)."""

    parte: str
    falta: list[str]
    a_mais: list[str]
    quase_iguais: list[dict[str, str]] = Field(
        description='[{"nesta": "vendedor", "nas_outras": "Vendedor"}]'
    )


class ContagemParte(_Resposta):
    """A reconciliação de uma aba juntada (F3)."""

    origem: str
    linhas_lidas: int
    linhas_gravadas: int | None
    alerta: bool
    passos: list[ContagemPasso]
    colunas_fora_da_area: list[ColunaForaDaArea]


class RegraAbas(_Resposta):
    sheets_regex: str | None = Field(description="Regra para source.combine_sheets.sheets_regex.")
    matches: list[str] = Field(description="Abas que a regra escolhe neste arquivo.")
    all_visible: bool


class Reconciliacao(_Resposta):
    """Reconciliação de linhas da receita da versão ``etag`` (F1). Com um
    passo que falha, ``passo_com_erro`` diz qual e ``passos`` para antes
    dele; ``linhas_gravadas`` fica nulo."""

    etag: str
    linhas_lidas: int
    linhas_gravadas: int | None
    alerta: bool
    passos: list[ContagemPasso]
    colunas_fora_da_area: list[ColunaForaDaArea]
    passo_com_erro: str | None = None
    partes: list[ContagemParte] = Field(default=[], description="Com abas juntas: a conta de cada aba.")
    divergencias: list[Divergencia] = []
    abas_ocultas: list[str] = Field(
        default=[], description="Abas ocultas que casariam com a regra e ficaram de fora."
    )


class ReceitaSalva(_Resposta):
    etag: str
    recipe: dict[str, Any]


class Exportacao(_Resposta):
    files: list[str]
    rows: int | None = None
    # Células de texto que começam com =, +, -, @… (None: só código exportado).
    formula_cells: int | None = None
    neutralized: bool = False
    # O M ou o PBIP saiu com um caminho de exemplo no CaminhoArquivo.
    source_path_missing: bool = False


class FormatoExportacao(_Resposta):
    """Formato de exportação e se ele está disponível nesta instalação."""

    format: str
    available: bool
    # Como habilitar quando falta um extra (``pip install "wolfzbr[tableau]"``).
    install: str | None = None


class Sugestao(_Resposta):
    """Passos propostos por uma regra (F2.E). ``kind="aviso"`` não tem passo."""

    id: str
    rule: str
    # Passos sem ``id``, na ordem; quem aceita numera.
    steps: list[dict[str, Any]]
    confidence: float
    reason: str
    cols: list[str]
    kind: str
    # Ordem de aplicação no "aceitar todas" (limpeza, conversão, forma).
    order: int


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

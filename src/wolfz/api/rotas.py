"""Rotas da API (``/api``). Só transporte: a regra está no núcleo.

Os handlers que leem arquivo ou rodam o motor são funções síncronas (``def``):
o FastAPI os executa em threadpool, e um preview pesado não trava o event
loop que atende o pedido seguinte (§6.4).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile
from pydantic import BaseModel, Field

from wolfz.api import modelos as m
from wolfz.api.problems import Problem
from wolfz.api.projetos import Projetos
from wolfz.api.security import Settings
from wolfz.br.municipios import buscar
from wolfz.core.detect import Detection, detect_tables, main_table
from wolfz.core.engine import collect, run
from wolfz.core.engine.preview import LIMITE_PAGINA, preview_project
from wolfz.core.ingest import SheetStructure, import_file, list_sheets, open_file
from wolfz.core.ingest.abas import padrao_de_aba
from wolfz.core.profile import profile_table
from wolfz.core.recipe import Recipe, dumps_recipe, load_recipe, recipe_from_dict, registered_ops, save_recipe
from wolfz.core.recipe.migrate import CURRENT_VERSION
from wolfz.core.suggest import suggest
from wolfz.core.workspace import PROJECT_FILE, RAW_FILE, STRUCTURE_FILE, write_json_atomic
from wolfz.export.dados import (
    EXTENSOES,
    ExportError,
    OpcoesCsv,
    Separador,
    celulas_formula,
    escritor,
    gravar_juntos,
)
from wolfz.export.depara import ARQUIVO_DEPARA, depara_municipios, gravar_depara
from wolfz.export.m import PARAMETRO, parameter_to_m, recipe_to_m, source_from_project
from wolfz.export.python import recipe_to_python
from wolfz.ops.municipio import PARAMETRO_DEPARA

RECIPE_FILE = "recipe.wolfz.json"
DETECTION_FILE = "detection.json"
# Sugestões rejeitadas no projeto: {"rejected": [{"rule": ..., "col": ... | null}]}.
SUGGESTIONS_FILE = "suggestions.json"
_TIPO_FONTE = {"xlsx": "excel", "xls": "excel", "ods": "ods", "csv": "csv"}


class PedidoRejeicao(BaseModel):
    rule: str = Field(min_length=1, description="Regra da sugestão rejeitada.")
    cols: list[str] = Field(default_factory=list, description="Colunas; vazio rejeita a regra inteira.")


class PedidoExportacao(BaseModel):
    formats: list[Literal["csv", "parquet", "xlsx", "powerquery", "python", "hyper", "pbip"]] = Field(
        min_length=1
    )
    output_dir: str | None = None
    overwrite: bool = False
    csv_separator: Separador = Field(default=",", description="Separador do CSV: ',', ';' ou tabulação.")
    decimal_comma: bool = Field(default=False, description="Número no CSV com vírgula decimal (1234,5).")
    neutralize_formulas: bool = Field(
        default=False,
        description="Prefixa com ' o texto do CSV que começa com =, +, -, @ (injeção de fórmula, F0.A9).",
    )


def _ler_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _etag(recipe: Recipe) -> str:
    return '"' + hashlib.sha256(dumps_recipe(recipe).encode("utf-8")).hexdigest()[:32] + '"'


def _receita_json(recipe: Recipe) -> dict[str, Any]:
    return json.loads(dumps_recipe(recipe))


def _nome_seguro(nome: str, padrao: str = "tabela") -> str:
    """Nome de arquivo sem diretório nem caractere estranho (path traversal)."""
    base = Path(nome.replace("\\", "/")).name
    return re.sub(r"[^\w.-]+", "_", base).strip("._") or padrao


def router(settings: Settings, projetos: Projetos) -> APIRouter:
    api = APIRouter(prefix="/api")
    ws = settings.workspace

    def receita(pasta: Path) -> Recipe:
        return load_recipe(pasta / RECIPE_FILE)

    @contextmanager
    def _upload_temporario(file: UploadFile) -> Iterator[Path]:
        """O upload numa pasta temporária do workspace, apagada no fim."""
        temporaria = Path(tempfile.mkdtemp(prefix="upload-", dir=_pasta_uploads(ws)))
        destino = temporaria / _nome_seguro(file.filename or "arquivo")
        try:
            _copia_com_limite(file, destino, settings.limits.max_file_bytes)
            yield destino
        finally:
            shutil.rmtree(temporaria, ignore_errors=True)

    # -----------------------------------------------------------------------
    # Projetos
    # -----------------------------------------------------------------------

    @api.post("/sheets", response_model=list[m.Aba])
    def listar_abas(file: Annotated[UploadFile, File(description="Planilha.")]) -> list[dict[str, Any]]:
        """Abas da planilha, sem criar projeto: a interface pergunta qual
        importar quando há mais de uma. CSV não tem aba (lista vazia)."""
        with _upload_temporario(file) as caminho:
            _, fmt, _ = open_file(caminho, settings.limits)  # mesmos erros da importação
            if fmt == "csv":
                return []
            return [s.to_dict() for s in list_sheets(caminho, fmt, settings.limits)]

    @api.post("/projects", status_code=201, response_model=m.ProjetoCriado)
    def criar_projeto(
        file: Annotated[UploadFile, File(description="Planilha ou CSV.")],
        sheet: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        """Importa o arquivo, detecta a estrutura e grava a receita inicial."""
        with _upload_temporario(file) as caminho:
            resultado = import_file(caminho, sheet=sheet, workspace=ws, limits=settings.limits)

        pasta = resultado.path
        projeto = resultado.project
        # O arquivo veio por upload: o caminho temporário não vale nada depois.
        projeto["source"]["path"] = None
        projeto["source"]["uploaded"] = True
        write_json_atomic(pasta / PROJECT_FILE, projeto)

        grade = pl.read_parquet(pasta / RAW_FILE)
        tabelas = detect_tables(grade, resultado.structure)
        deteccao = main_table(tabelas)
        detectado = _deteccao_json(deteccao, tabelas)
        write_json_atomic(pasta / DETECTION_FILE, detectado)
        passos = deteccao.to_steps() if deteccao else []
        fonte: dict[str, Any] = {"type": _TIPO_FONTE[projeto["source"]["format"]]}
        if projeto["source"]["sheet"]:
            fonte["sheet"] = projeto["source"]["sheet"]
            # Aba com mês ou ano no nome: aceita a do próximo arquivo (F2.F4).
            if padrao := padrao_de_aba(projeto["source"]["sheet"]):
                fonte["match"] = {"sheet_name_regex": padrao}
        inicial = recipe_from_dict(
            {
                "wolfz_version": CURRENT_VERSION,
                "name": Path(projeto["name"]).stem,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "source": fonte,
                "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
            }
        )
        save_recipe(inicial, pasta / RECIPE_FILE)
        projetos.abrir(resultado.project_id)
        return {
            **projeto,
            "reused_raw": resultado.reused,
            "detection": detectado,
            "recipe": _receita_json(inicial),
            "etag": _etag(inicial),
        }

    @api.get("/projects", response_model=list[m.ProjetoResumo])
    def listar_projetos() -> list[dict[str, Any]]:
        saida = []
        for project_id, meta in ws.projects():
            pasta = ws.project_dir(project_id)
            saida.append(
                {
                    "id": project_id,
                    "name": meta.get("name"),
                    "created_at": meta.get("created_at"),
                    "format": meta.get("source", {}).get("format"),
                    "sheet": meta.get("source", {}).get("sheet"),
                    "rows": meta.get("raw", {}).get("rows"),
                    "open_here": projetos.aberto_aqui(project_id),
                    "open_elsewhere": projetos.aberto_em_outra(project_id, pasta),
                }
            )
        return saida

    @api.get("/projects/{project_id}", response_model=m.Projeto)
    def abrir_projeto(project_id: str, response: Response) -> dict[str, Any]:
        pasta = projetos.abrir(project_id)
        atual = receita(pasta)
        response.headers["ETag"] = _etag(atual)
        return {**_ler_json(pasta / PROJECT_FILE), "recipe": _receita_json(atual), "etag": _etag(atual)}

    @api.delete("/projects/{project_id}", status_code=204)
    def apagar_projeto(project_id: str) -> Response:
        projetos.apagar(project_id)  # 423 se estiver aberto em outra instância
        return Response(status_code=204)

    @api.get("/projects/{project_id}/structure", response_model=m.Estrutura)
    def estrutura(project_id: str) -> dict[str, Any]:
        pasta = projetos.abrir(project_id)
        deteccao = pasta / DETECTION_FILE
        return {
            "structure": SheetStructure.from_dict(_ler_json(pasta / STRUCTURE_FILE)).to_dict(),
            "detection": _ler_json(deteccao) if deteccao.is_file() else None,
        }

    @api.get("/projects/{project_id}/profile", response_model=m.Perfil)
    def perfil(
        project_id: str,
        step: Annotated[
            str | None, Query(description='Passo; omitido = receita inteira; "raw" = antes.')
        ] = None,
        sample: Annotated[int, Query(ge=1, le=100_000)] = 10_000,
    ) -> dict[str, Any]:
        pasta = projetos.abrir(project_id)
        sub = _ate_o_passo(receita(pasta), step)
        raw = pl.scan_parquet(pasta / RAW_FILE)
        plano = run(sub, raw)
        try:
            tabela = plano.collect()
        except Exception:
            collect(sub, raw)  # aponta o passo culpado (StepError)
            raise
        return profile_table(tabela, sample).to_dict()

    # -----------------------------------------------------------------------
    # Receita (ETag / If-Match, §9)
    # -----------------------------------------------------------------------

    @api.get("/projects/{project_id}/recipe")
    def ler_receita(project_id: str, response: Response) -> dict[str, Any]:
        atual = receita(projetos.abrir(project_id))
        response.headers["ETag"] = _etag(atual)
        return _receita_json(atual)

    @api.put("/projects/{project_id}/recipe", response_model=m.ReceitaSalva)
    def salvar_receita(
        project_id: str,
        corpo: dict[str, Any],
        response: Response,
        if_match: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        """Substitui a receita inteira. Salvamento automático: a interface
        chama a cada edição, e a gravação é atômica."""
        pasta = projetos.abrir(project_id)
        if if_match is None:
            raise Problem(428, "Envie o cabeçalho If-Match com a ETag da receita que você editou.")
        atual = receita(pasta)
        if if_match.strip() != _etag(atual):
            raise Problem(
                409,
                "A receita mudou desde que você a abriu (outra aba?). Recarregue antes de salvar.",
                title="Receita desatualizada",
                etag=_etag(atual),
            )
        nova = recipe_from_dict(corpo)  # RecipeError -> 422 com o passo e o campo
        save_recipe(nova, pasta / RECIPE_FILE)
        etag = _etag(nova)
        response.headers["ETag"] = etag
        return {"etag": etag, "recipe": _receita_json(nova)}

    # -----------------------------------------------------------------------
    # Preview
    # -----------------------------------------------------------------------

    @api.get("/projects/{project_id}/preview", response_model=m.Pagina)
    def ver_preview(
        project_id: str,
        step: Annotated[
            str | None, Query(description='Passo; omitido = receita inteira; "raw" = antes.')
        ] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=LIMITE_PAGINA)] = 200,
        columns: Annotated[str | None, Query(description="Colunas, separadas por vírgula.")] = None,
    ) -> dict[str, Any]:
        pasta = projetos.abrir(project_id)
        atual = receita(pasta)
        _ate_o_passo(atual, step)  # 404 se o passo não existe
        with projetos.lock_preview(project_id):
            pagina = preview_project(pasta, atual, step, offset, limit)
        if columns:
            pedidas = [c for c in columns.split(",") if c]
            faltam = [c for c in pedidas if c not in pagina.frame.columns]
            if faltam:
                raise Problem(422, f"Colunas inexistentes neste passo: {', '.join(faltam)}.")
            pagina.frame = pagina.frame.select(pedidas)
        return pagina.to_dict()

    # -----------------------------------------------------------------------
    # Sugestões (F2.E)
    # -----------------------------------------------------------------------

    @api.get("/projects/{project_id}/suggestions", response_model=list[m.Sugestao])
    def sugestoes(project_id: str) -> list[dict[str, Any]]:
        """Sugestões para a tabela no fim da receita, na ordem de aplicação.
        As rejeitadas neste projeto não voltam."""
        pasta = projetos.abrir(project_id)
        atual = receita(pasta)
        with projetos.lock_preview(project_id):
            tabela = collect(atual, pl.scan_parquet(pasta / RAW_FILE))
        passos = [s.model_dump(mode="json") for s in atual.steps]
        return [s.to_dict() for s in suggest(tabela, _rejeitadas(pasta), steps=passos)]

    @api.post("/projects/{project_id}/suggestions/rejections", status_code=204)
    def rejeitar_sugestao(project_id: str, pedido: PedidoRejeicao) -> Response:
        """Rejeita a sugestão para as colunas dela (ou a regra inteira, sem
        colunas). Fica gravado no projeto."""
        pasta = projetos.abrir(project_id)
        atuais = _ler_json(pasta / SUGGESTIONS_FILE) if (pasta / SUGGESTIONS_FILE).is_file() else {}
        rejeitadas = atuais.get("rejected", [])
        novas = [{"rule": pedido.rule, "col": c} for c in pedido.cols] or [{"rule": pedido.rule, "col": None}]
        rejeitadas += [r for r in novas if r not in rejeitadas]
        write_json_atomic(pasta / SUGGESTIONS_FILE, {**atuais, "rejected": rejeitadas})
        return Response(status_code=204)

    # -----------------------------------------------------------------------
    # Revisão de municípios (F2.C4)
    # -----------------------------------------------------------------------

    @api.get(
        "/projects/{project_id}/steps/{step_id}/municipios",
        response_model=list[m.ItemRevisaoMunicipio],
    )
    def revisar_municipios(project_id: str, step_id: str) -> list[dict[str, Any]]:
        """Valores distintos que chegam a um passo ``normalize_municipio``,
        com o casamento atual e sugestões: primeiro os que precisam de
        revisão. Aceitar ou corrigir é editar o ``manual`` do passo
        (``PUT /recipe``)."""
        pasta = projetos.abrir(project_id)
        atual = receita(pasta)
        ids = [s.id for s in atual.steps]
        if step_id not in ids:
            raise Problem(404, f"A receita não tem o passo {step_id!r}.", title="Passo não encontrado")
        passo = atual.steps[ids.index(step_id)]
        if passo.op != "normalize_municipio":
            raise Problem(422, f"O passo {step_id} não é de município ({passo.op}).")
        antes = [s for s in atual.steps[: ids.index(step_id)] if s.enabled]
        with projetos.lock_preview(project_id):
            entrada = collect(atual.model_copy(update={"steps": antes}), pl.scan_parquet(pasta / RAW_FILE))
            return passo.revisao(entrada.lazy())  # type: ignore[attr-defined]

    @api.get("/municipios", response_model=list[m.Municipio])
    def buscar_municipios(
        q: Annotated[str, Query(min_length=1, description="Começo ou parte do nome.")],
        uf: Annotated[str | None, Query(description="Sigla ou nome da UF.")] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> list[dict[str, Any]]:
        """Busca na lista do IBGE, para a correção manual."""
        return [
            {"codigo_ibge": mun.codigo, "nome": mun.nome, "uf": mun.uf, "nota": nota}
            for mun, nota in buscar(q, uf, limit)
        ]

    # -----------------------------------------------------------------------
    # Exportação
    # -----------------------------------------------------------------------

    @api.post("/projects/{project_id}/exports", response_model=m.Exportacao)
    def exportar(project_id: str, pedido: PedidoExportacao) -> dict[str, Any]:
        """Gera os arquivos. Pasta com arquivo do mesmo nome: falha, a não ser
        com ``overwrite`` (F0.A6). Tudo é gerado numa pasta temporária e movido
        no fim (build-then-swap, F1.I4)."""
        pasta = projetos.abrir(project_id)
        indisponiveis = sorted(set(pedido.formats) - set(_EXTENSOES))
        if indisponiveis:
            raise Problem(422, f"Formato ainda não disponível nesta versão: {', '.join(indisponiveis)}.")
        saida = Path(pedido.output_dir).expanduser() if pedido.output_dir else pasta / "exports"
        if not saida.is_absolute():
            raise Problem(422, "output_dir precisa ser um caminho absoluto.")
        saida = saida.resolve()
        atual = receita(pasta)
        projeto = _ler_json(pasta / PROJECT_FILE)
        base = _nome_seguro(Path(projeto["name"]).stem)
        alvos = {fmt: saida / f"{base}{_EXTENSOES[fmt]}" for fmt in dict.fromkeys(pedido.formats)}
        if "powerquery" in alvos:
            # O parâmetro CaminhoArquivo vai num arquivo à parte (F2.A3).
            alvos["powerquery_parametro"] = saida / f"{base}.{PARAMETRO}.pq"
        # Município casado por fuzzy: o M e o script fazem join com o de-para (ADR-7, F2.C5).
        usa_depara = any(s.op == "normalize_municipio" for s in atual.active_steps)
        if usa_depara and {"powerquery", "python"} & set(alvos):
            alvos["depara"] = saida / ARQUIVO_DEPARA
            if "powerquery" in alvos:
                alvos["powerquery_depara"] = saida / f"{base}.{PARAMETRO_DEPARA}.pq"
        existentes = [str(p) for p in alvos.values() if p.exists()]
        if existentes and not pedido.overwrite:
            raise Problem(
                409,
                f"Já existem arquivos com esses nomes: {', '.join(existentes)}. Confirme para sobrescrever.",
                title="Arquivo já existe",
                existing=existentes,
            )

        tabela = None
        formulas = None
        if set(alvos) & set(EXTENSOES):
            tabela = collect(atual, pl.scan_parquet(pasta / RAW_FILE))
            formulas = celulas_formula(tabela)
        opcoes = OpcoesCsv(separator=pedido.csv_separator, decimal_comma=pedido.decimal_comma)
        escritas: dict[Path, Callable[[Path], None]] = {}
        for fmt, alvo in alvos.items():
            if fmt in EXTENSOES:
                escritas[alvo] = escritor(fmt, tabela, opcoes, pedido.neutralize_formulas, aba=atual.name)
            elif fmt == "powerquery":
                fonte = source_from_project(projeto["source"], pl.scan_parquet(pasta / RAW_FILE))
                escritas[alvo] = partial(_escrever_texto, recipe_to_m(atual, fonte))
            elif fmt == "powerquery_parametro":
                # Arquivo enviado por upload não tem caminho: fica o nome, para o usuário completar.
                caminho = projeto["source"].get("path") or rf"C:\caminho\para\{projeto['source']['name']}"
                escritas[alvo] = partial(_escrever_texto, parameter_to_m(caminho, atual.name))
            elif fmt == "powerquery_depara":
                texto = parameter_to_m(str(alvos["depara"]), atual.name, PARAMETRO_DEPARA)
                escritas[alvo] = partial(_escrever_texto, texto)
            elif fmt == "depara":
                depara = depara_municipios(atual, pl.scan_parquet(pasta / RAW_FILE))
                escritas[alvo] = partial(gravar_depara, depara)
            else:
                escritas[alvo] = partial(_escrever_texto, recipe_to_python(atual))
        try:
            gravar_juntos(escritas)
        except ExportError as exc:
            raise Problem(422, str(exc), title="Não cabe neste formato") from None
        return {
            "files": [str(p) for p in alvos.values()],
            "rows": tabela.height if tabela is not None else None,
            "formula_cells": formulas,
            "neutralized": bool(pedido.neutralize_formulas and "csv" in alvos),
        }

    # -----------------------------------------------------------------------
    # Catálogo
    # -----------------------------------------------------------------------

    @api.get("/ops", response_model=list[m.Operacao])
    def catalogo() -> list[dict[str, Any]]:
        """Operações registradas, com o JSON Schema dos parâmetros: a
        interface monta os formulários dos passos a partir disto."""
        return [
            {
                "op": nome,
                "doc": " ".join((cls.__doc__ or "").split()),
                "schema": cls.model_json_schema(),
                "full_checkpoint": cls.full_checkpoint,
                "examples": list(cls.examples),
            }
            for nome, cls in sorted(registered_ops().items())
        ]

    return api


_EXTENSOES = {**EXTENSOES, "powerquery": ".pq", "python": ".py"}


def _escrever_texto(texto: str, path: Path) -> None:
    path.write_text(texto, encoding="utf-8")


def _pasta_uploads(ws) -> Path:
    pasta = ws.root / "uploads"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _copia_com_limite(upload: UploadFile, destino: Path, limite: int) -> None:
    """Copia o upload em blocos e para no limite, mesmo que o
    ``Content-Length`` tenha mentido."""
    total = 0
    with destino.open("wb") as saida:
        while bloco := upload.file.read(1 << 20):
            total += len(bloco)
            if total > limite:
                raise Problem(
                    413, f"O limite de upload é {limite // (1024 * 1024)} MB.", code="file_too_large"
                )
            saida.write(bloco)


def _rejeitadas(pasta: Path) -> list[tuple[str, str | None]]:
    caminho = pasta / SUGGESTIONS_FILE
    if not caminho.is_file():
        return []
    return [(r["rule"], r.get("col")) for r in _ler_json(caminho).get("rejected", [])]


def _deteccao_json(principal: Detection | None, tabelas: list[Detection]) -> dict[str, Any] | None:
    """Detecção gravada no projeto: a tabela principal e, se a aba tem mais
    de uma, todas elas com os passos de cada uma, para a interface trocar
    de tabela (F2.D3)."""
    if principal is None:
        return None
    detectado = principal.to_dict()
    if len(tabelas) > 1:
        detectado["tabelas"] = [{**t.to_dict(), "passos": t.to_steps()} for t in tabelas]
    return detectado


def _ate_o_passo(recipe: Recipe, step: str | None) -> Recipe:
    if step is None:
        return recipe
    if step == "raw":
        return recipe.model_copy(update={"steps": []})
    ids = [s.id for s in recipe.steps]
    if step not in ids:
        raise Problem(404, f"A receita não tem o passo {step!r}.", title="Passo não encontrado")
    return recipe.model_copy(update={"steps": recipe.steps[: ids.index(step) + 1]})


__all__ = ["RECIPE_FILE", "router"]

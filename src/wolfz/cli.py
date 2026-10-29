"""CLI ``wolfz``: argumentos, saída no terminal e códigos de retorno.

Sem regra de negócio; os comandos chamam o núcleo (``wolfz.core``). As
mensagens de erro são as mesmas que a API devolve (``StepError.message``,
``RecipeError.errors``), para que interface e terminal falhem com o mesmo
texto (§5.4).
"""

from __future__ import annotations

import glob
import json
import re
from datetime import date, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import polars as pl
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from wolfz import __version__
from wolfz.core.engine import (
    ErroAoJuntar,
    RunReport,
    StepCount,
    StepError,
    como_parte,
    read_parts,
    reconciliar_partes,
)
from wolfz.core.engine.juntar import empilhar, teto_de_juntar
from wolfz.core.engine.reconcilia import OutsideColumn, somar
from wolfz.core.ingest import IngestError, list_sheets
from wolfz.core.profile import ColumnProfile, LoadedTable, TableProfile, load_table, profile_table
from wolfz.core.profile.column import SAMPLE_SIZE
from wolfz.core.recipe import Recipe, RecipeError, RecipeTooNewError, load_recipe, recipe_json_schema
from wolfz.export.dados import ExportError, OpcoesCsv, celulas_formula, escritor, gravar_juntos
from wolfz.ops.verificacao import _linhas_br


class ExitCode(IntEnum):
    OK = 0
    STEP_ERROR = 1  # um passo não se aplica a este arquivo
    INVALID_RECIPE = 2  # receita inválida ou ilegível, ou uso incorreto
    UNREADABLE_INPUT = 3  # arquivo de entrada ilegível


class Formato(StrEnum):
    csv = "csv"
    parquet = "parquet"
    xlsx = "xlsx"


class Sep(StrEnum):
    virgula = ","
    ponto_e_virgula = ";"
    tab = "tab"


app = typer.Typer(
    name="wolfz",
    help="Limpeza de planilhas brasileiras com receitas reproduzíveis.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wolfz {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Mostra a versão e sai."
    ),
) -> None:
    """Limpeza de planilhas brasileiras com receitas reproduzíveis."""


def _fail(code: ExitCode, *lines: str) -> NoReturn:
    for line in lines:
        typer.echo(line, err=True)
    raise typer.Exit(int(code))


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _output_path(saida: str, arquivo: Path, formato: Formato) -> Path:
    """``-o`` pode ser um arquivo ou uma pasta (existente ou terminada em
    barra); numa pasta, o nome vem do arquivo de entrada. Recebe texto, e
    não ``Path``, porque ``Path`` descarta a barra final."""
    if saida.endswith(("/", "\\")) or Path(saida).is_dir():
        return Path(saida) / f"{arquivo.stem}.{formato.value}"
    return Path(saida)


_EPILOG = (
    "Vários arquivos (ou um padrão como 'entrada/*.xlsx'): -o é uma pasta e cada arquivo é processado "
    "à parte, com um relatório no fim; com --combine, -o é um arquivo e todos são juntados nele "
    "(se um falhar, nada é gravado). "
    "Códigos de saída: 0 ok · 1 um passo falhou (ou uma verificação reprovou) · "
    "2 receita inválida ou uso incorreto · 3 arquivo de entrada ilegível. "
    "Em lote, o maior código entre os arquivos."
)


class _Falha(Exception):
    """Falha de um arquivo: o código de saída, as linhas da mensagem do
    terminal e o que vai para o ``--report``. Cada chamada declara o que vai
    para o relatório (achado A2 do André): ele nunca copia as linhas do
    terminal, que podem trazer o texto de uma exceção, e nunca leva valor de
    célula (S2, D9)."""

    def __init__(self, code: ExitCode, *lines: str, relatorio: dict[str, Any]):
        super().__init__(lines[0] if lines else "")
        self.code = code
        self.lines = lines
        self.relatorio = relatorio


def _carregar_receita(receita: Path) -> Recipe:
    try:
        return load_recipe(receita)
    except FileNotFoundError:
        _fail(ExitCode.INVALID_RECIPE, f"Receita não encontrada: {receita}")
    except RecipeTooNewError as exc:
        _fail(
            ExitCode.INVALID_RECIPE,
            f"Receita de uma versão mais nova do WolfzBR: {receita}",
            *(f"  {e}" for e in exc.errors),
        )
    except RecipeError as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Receita inválida: {receita}", *(f"  {e}" for e in exc.errors))
    except (UnicodeDecodeError, OSError) as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Não foi possível ler a receita {receita}: {_first_line(exc)}")


# ---------------------------------------------------------------------------
# Texto vindo da planilha no terminal (R9) e números em pt-BR
# ---------------------------------------------------------------------------

_CONTROLE = re.compile("[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def _literal(texto: str, limite: int | None = None) -> str:
    """Texto de dado (cabeçalho, nome de arquivo) para o terminal: sem
    caractere de controle nem sequência ANSI, cortado em ``limite``. A
    marcação do Rich é escapada onde o Rich imprime (``escape``)."""
    texto = _CONTROLE.sub("", texto)
    if limite is not None and len(texto) > limite:
        texto = texto[: limite - 1] + "…"
    return texto


def _pct_br(parte: int, todo: int) -> str:
    return _pct(parte / todo) if todo else "0%"


def _limite_br(fracao: float) -> str:
    texto = f"{fracao * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{texto}%"


def _lista_br(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} e {itens[-1]}"


# Nomes das operações que mudam o número de linhas, como na interface
# (frontend/src/textos.ts). Op sem nome aqui aparece com o nome técnico.
_NOMES_OPS = {
    "select_range": "Recortar a área",
    "header_rows": "Definir o cabeçalho",
    "drop_empty_rows": "Remover linhas vazias",
    "drop_rows_where": "Remover linhas",
    "filter": "Filtrar linhas",
    "dedupe": "Remover duplicadas",
    "unpivot": "Despivotar colunas",
}


def _passo(s: StepCount) -> str:
    return f"{s.id} {_NOMES_OPS.get(s.op, s.op)}"


def _max_drop(valor: str | None) -> float | None:
    """'1%', '1', '0.5%', '0,5%' e '0' -> fração (0.01, 0.01, 0.005, 0.0)."""
    if valor is None:
        return None
    texto = valor.strip().removesuffix("%").strip().replace(",", ".")
    try:
        pct = float(texto)
    except ValueError:
        raise typer.BadParameter(f"{valor!r} não é um percentual (ex.: 1%, 0.5%, 0)") from None
    if not 0 <= pct <= 100:
        raise typer.BadParameter(f"{valor!r} precisa estar entre 0% e 100%")
    return pct / 100


# ---------------------------------------------------------------------------
# Mensagens de falha
# ---------------------------------------------------------------------------

_MOTIVO_VERIFICACAO = {"not_null": "vazias", "in_range": "fora da faixa", "matches": "fora do padrão"}


def _texto_verificacao(passo: str, v: dict[str, Any]) -> str:
    """O ``erro`` do ``--report`` para uma verificação reprovada, montado só
    dos campos estruturados (D9), nunca do texto de uma exceção."""
    q = v["quantidade"]
    if v["verificacao"] == "row_count_min":
        return f"Verificação reprovada no passo {passo}: a tabela tem {_int_br(q)} linhas, abaixo do mínimo."
    linhas = _linhas_br(v["linhas"], q)
    if v["verificacao"] == "unique":
        detalhe = f"{v['coluna']} se repete em {_int_br(q)} linhas: {linhas}"
    else:
        detalhe = f"{v['coluna']} tem {_int_br(q)} linhas {_MOTIVO_VERIFICACAO[v['verificacao']]}: {linhas}"
    return f"Verificação reprovada no passo {passo}: {detalhe}."


def _falha_de_passo(exc: StepError, mostrar_valores: bool) -> _Falha:
    columns = ", ".join(exc.available_columns) or "(nenhuma)"
    if exc.detalhe_seguro or mostrar_valores:
        principal = [f"{exc.title}: {exc.message}"]
    else:
        principal = [
            f"{exc.title}: O passo {exc.step_id} ({exc.op}) falhou.",
            "Rode com --show-values para ver o detalhe do erro (pode mostrar valores da planilha).",
        ]
    if mostrar_valores and exc.valores:
        principal.append(f"Valores: {_literal('; '.join(exc.valores), 300)}")
    relatorio: dict[str, Any] = {"passo": exc.step_id}
    if exc.verificacao is not None:
        relatorio["erro"] = _texto_verificacao(exc.step_id, exc.verificacao)
        relatorio.update(exc.verificacao)
    elif exc.title == "Coluna não encontrada":
        relatorio["erro"] = f"{exc.title}: {exc.message}"
    else:
        relatorio["erro"] = f"{exc.title}: o passo {exc.step_id} ({exc.op}) falhou."
    if exc.contagem_parcial is not None:
        lidas, feitos = exc.contagem_parcial
        relatorio["linhas_lidas"] = lidas
        relatorio["passos"] = [s.to_dict() for s in feitos]
    return _Falha(
        ExitCode.STEP_ERROR,
        *principal,
        f"Colunas disponíveis antes do passo {exc.step_id}: {columns}",
        "Nada foi gravado.",
        relatorio=relatorio,
    )


def _parado(r: RunReport, limite: float) -> _Falha:
    """``--max-drop`` estourado: a mensagem do terminal e do relatório."""
    culpados = [s for s in r.steps if s.lost]
    pct = _pct_br(r.lost, r.rows_read)
    if len(culpados) == 1:
        quem = f"o passo {_passo(culpados[0])} tirou {pct} das linhas"
    else:
        quem = f"a receita tirou {pct} das linhas (passos {_lista_br([s.id for s in culpados])})"
    principal = f"Parado: {quem}, acima do limite de {_limite_br(limite)} (--max-drop)."
    contas = f"Lidas {_int_br(r.rows_read)} · sairiam {_int_br(r.rows_written)}."
    return _Falha(
        ExitCode.STEP_ERROR,
        principal,
        contas,
        "Nada foi gravado.",
        relatorio={"erro": f"{principal} {contas}", **r.to_dict()},
    )


# ---------------------------------------------------------------------------
# Resumo da reconciliação (stderr, D12)
# ---------------------------------------------------------------------------

_MAX_PASSOS = 3
# Só ASCII nos sinais: o console do Windows em cp850/cp1252 não tem o menos
# e o vezes tipográficos do painel (ux.md §1.1), e mostraria "\u2212".
_MENOS, _VEZES = "-", "x"


def _linha_do_passo(s: StepCount, r: RunReport) -> str:
    if s.reason == "multiplicacao":
        if s.factor is not None:
            fator = f"{s.factor:.1f}".rstrip("0").rstrip(".").replace(".", ",")
            total = _int_br(s.rows_out)
            return f"  {_passo(s)}: {_VEZES} {fator} -> {total} linhas, numa tabela já despivotada."
        return f"  {_passo(s)}: +{_int_br(s.rows_out - s.rows_in)} linhas."
    if s.reason == "fora_da_area":
        pct = _pct_br(s.outside_area, r.rows_read)
        texto = f"  {_passo(s)}: {_MENOS}{_int_br(s.outside_area)} linhas ({pct})."
        fim_area, fim_grade = r.area_ends.get(s.id, (None, None))
        if fim_area and fim_grade:
            texto += f" A área termina na linha {fim_area}; o arquivo vai até a linha {fim_grade}."
        return texto
    return f"  {_passo(s)}: {_MENOS}{_int_br(s.lost)} linhas ({_pct_br(s.lost, r.rows_read)})."


def _resumo(r: RunReport, prefixo: str = "") -> list[tuple[str, bool]]:
    """Linhas do resumo: (texto, é aviso). Sem alerta, uma linha só."""
    alertas = [s for s in r.steps if s.alert]
    partes = [f"lidas {_int_br(r.rows_read)}", f"gravadas {_int_br(r.rows_written)}"]
    for s in alertas:
        if s.reason == "fora_da_area" and s.outside_area:
            pct = _pct_br(s.outside_area, r.rows_read)
            partes.append(f"{_int_br(s.outside_area)} fora da área recortada ({pct})")
        elif s.reason == "perda":
            partes.append(
                f"{_int_br(s.lost)} removidas pelo passo {_passo(s)} ({_pct_br(s.lost, r.rows_read)})"
            )
        elif s.reason == "multiplicacao":
            partes.append(f"{_int_br(s.rows_out)} linhas depois do passo {_passo(s)}")
    sem_alerta = sum(s.lost for s in r.steps if not s.alert)
    if sem_alerta:
        partes.append(f"{_int_br(sem_alerta)} removidas pela receita")
    vazias = sum(s.empty_removed for s in r.steps)
    if vazias:
        partes.append(
            f"{_int_br(vazias)} {'linha vazia removida' if vazias == 1 else 'linhas vazias removidas'}"
        )
    linha = " · ".join(partes)
    if not r.alert:
        return [(prefixo + linha[0].upper() + linha[1:], False)]
    saida = [(f"{prefixo}Atenção: {linha}", True)]
    com_linha = [s for s in alertas if s.reason != "fora_da_area" or s.outside_area]
    com_linha.sort(key=lambda s: max(s.lost, s.rows_out - s.rows_in), reverse=True)
    saida += [(_linha_do_passo(s, r), True) for s in com_linha[:_MAX_PASSOS]]
    if len(com_linha) > _MAX_PASSOS:
        resto = len(com_linha) - _MAX_PASSOS
        saida.append((f"  e mais {resto} {'passo' if resto == 1 else 'passos'} (veja --report)", True))
    if not alertas:  # vários passos pequenos, somados, passaram do limite
        saida.append((f"  A receita tirou {_pct_br(r.lost, r.rows_read)} das linhas lidas.", True))
    return saida


def _avisos_fora_da_area(r: RunReport, prefixo: str = "") -> list[str]:
    """Colunas preenchidas fora da área (resto da C1, D3). O cabeçalho é
    nome de coluna, não valor de dado: aparece aqui, sem caractere de
    controle e cortado em 60 caracteres, e nunca no ``--report``."""
    por_passo: dict[str, list[OutsideColumn]] = {}
    for c in r.outside_columns:
        por_passo.setdefault(c.step, []).append(c)
    avisos = []
    for passo, cols in por_passo.items():
        total = sum(c.cells for c in cols)
        celulas = f"{_int_br(total)} {'célula preenchida' if total == 1 else 'células preenchidas'}"
        nomes = [f"{c.letter} ({_literal(c.header, 60) if c.header else 'sem cabeçalho'})" for c in cols]
        if len(cols) == 1:
            quem = f"a coluna {nomes[0]} tem {celulas}"
        elif len(cols) <= _MAX_PASSOS:
            quem = f"as colunas {_lista_br(nomes)} têm {celulas}"
        else:
            quem = f"as colunas {cols[0].letter} a {cols[-1].letter} ({len(cols)} colunas) têm {celulas}"
        onde = f"fora da área {cols[0].area} do passo {passo}"
        avisos.append(f"{prefixo}Atenção: {quem} {onde}. Elas não entram na saída.")
    if avisos:
        avisos.append("Para incluir, ajuste a área na receita (interface: Original -> marcar a área).")
    return avisos


def _avisos_da_juncao(r: RunReport, prefixo: str = "", o_que: str = "as abas") -> list[str]:
    """Abas ocultas que ficaram de fora (R6) e colunas que não batem entre
    as partes (ADR-11, ux.md §3.4). Nome de aba e de coluna vêm do arquivo:
    sem caractere de controle e cortados (R9)."""
    avisos = []
    if r.hidden_sheets:
        n = len(r.hidden_sheets)
        nomes = ", ".join(_literal(a, 60) for a in r.hidden_sheets)
        quantas = "1 aba oculta não foi incluída" if n == 1 else f"{n} abas ocultas não foram incluídas"
        avisos.append(f"{prefixo}Atenção: {quantas}: {nomes}.")
    if r.divergences:
        avisos.append(f"{prefixo}Atenção: {o_que} não têm as mesmas colunas.")
        for d in r.divergences:
            parte = _literal(d.parte, 60)
            quase = {a for a, _ in d.quase_iguais} | {b for _, b in d.quase_iguais}
            falta = [_literal(c, 60) for c in d.falta if c not in quase]
            a_mais = [_literal(c, 60) for c in d.a_mais if c not in quase]
            if falta and a_mais:
                avisos.append(f"  {parte}: falta {', '.join(falta)}; tem a mais {', '.join(a_mais)}.")
            elif falta:
                avisos.append(f"  {parte}: falta {', '.join(falta)}.")
            elif a_mais:
                avisos.append(f"  {parte}: tem a mais {', '.join(a_mais)}.")
            for nesta, nas_outras in d.quase_iguais:
                avisos.append(
                    f'  {parte}: tem "{_literal(nesta, 60)}", as outras têm "{_literal(nas_outras, 60)}". '
                    "Viraram duas colunas."
                )
        avisos.append("Nas linhas de uma parte sem a coluna, ela fica vazia. Nenhuma coluna foi tirada.")
    return avisos


def _imprimir_resumo(r: RunReport, prefixo: str = "", o_que: str = "as abas") -> None:
    for texto, aviso in _resumo(r, prefixo):
        typer.secho(texto, err=True, fg="yellow" if aviso else None)
    for texto in _avisos_fora_da_area(r, prefixo):
        typer.secho(texto, err=True, fg="yellow")
    for texto in _avisos_da_juncao(r, prefixo, o_que):
        typer.secho(texto, err=True, fg="yellow")


# ---------------------------------------------------------------------------
# Processar um arquivo
# ---------------------------------------------------------------------------


def _calcular(
    recipe: Recipe,
    arquivo: Path,
    sheet: str | None = None,
    max_drop: float | None = None,
    mostrar_valores: bool = False,
) -> RunReport:
    """Lê o arquivo e aplica a receita, contando as linhas, sem gravar
    nada. Falhou, ou a perda passou do ``--max-drop``: ``_Falha``."""
    if not arquivo.is_file():
        nao_existe = f"Arquivo não encontrado: {arquivo}"
        raise _Falha(ExitCode.UNREADABLE_INPUT, nao_existe, relatorio={"erro": f"{nao_existe}."})
    if sheet is not None and arquivo.suffix.lower() in (".csv", ".txt", ".tsv"):
        sem_abas = f"--sheet vale para planilha; {arquivo.name} é CSV e não tem abas."
        raise _Falha(ExitCode.INVALID_RECIPE, sem_abas, "Nada foi gravado.", relatorio={"erro": sem_abas})
    try:
        partes, ocultas = read_parts(recipe, arquivo, sheet=sheet)
    except IngestError as exc:
        if exc.code == "sheet_not_found" and sheet is not None:
            abas = ", ".join(s.name for s in list_sheets(arquivo))
            linhas = (
                f"A aba {_literal(sheet, 60)} não existe em {_literal(arquivo.name, 60)}.",
                f"Abas do arquivo: {_literal(abas)}.",
            )
            raise _Falha(
                ExitCode.UNREADABLE_INPUT, *linhas, "Nada foi gravado.", relatorio={"erro": " ".join(linhas)}
            ) from None
        # Mensagem montada pela ingestão (tamanho, senha, aba que falta).
        texto = f"{exc.title}: {exc.message}"
        raise _Falha(ExitCode.UNREADABLE_INPUT, texto, relatorio={"erro": texto}) from None
    except (OSError, pl.exceptions.PolarsError) as exc:
        # O texto da exceção fica só no terminal (A2).
        raise _Falha(
            ExitCode.UNREADABLE_INPUT,
            f"Não foi possível ler {arquivo}: {_first_line(exc)}",
            relatorio={"erro": f"Não foi possível ler {arquivo}."},
        ) from None
    try:
        report = reconciliar_partes(recipe, partes, ocultas)
    except StepError as exc:
        raise _falha_de_passo(exc, mostrar_valores) from None
    except ErroAoJuntar as exc:
        texto = f"{exc.titulo}: {exc.mensagem}"
        raise _Falha(ExitCode.STEP_ERROR, texto, "Nada foi gravado.", relatorio={"erro": texto}) from None
    if max_drop is not None and report.lost > max_drop * report.rows_read:
        raise _parado(report, max_drop)
    return report


def _processar(
    recipe: Recipe,
    arquivo: Path,
    destino: Path,
    formato: Formato,
    opcoes: OpcoesCsv,
    neutralizar: bool,
    overwrite: bool,
    max_drop: float | None = None,
    mostrar_valores: bool = False,
    sheet: str | None = None,
) -> RunReport:
    """Aplica a receita a um arquivo, contando as linhas, e grava. Nada é
    gravado se algo falhar ou se a perda passar do ``--max-drop``."""
    if destino.exists() and not overwrite:
        existe = f"A saída já existe: {destino}"
        raise _Falha(
            ExitCode.INVALID_RECIPE,
            existe,
            "Use --overwrite para substituir.",
            relatorio={"erro": f"{existe}."},
        )
    report = _calcular(recipe, arquivo, sheet, max_drop, mostrar_valores)
    try:
        gravar_juntos({destino: escritor(formato.value, report.table, opcoes, neutralizar, aba=recipe.name)})
    except ExportError as exc:
        raise _Falha(
            ExitCode.INVALID_RECIPE, str(exc), "Nada foi gravado.", relatorio={"erro": str(exc)}
        ) from None
    return report


_BLOQUEIO = re.compile(r"^~\$.*|^\.~lock\..*#$")


def _expandir(arquivos: list[str]) -> list[Path]:
    """Os arquivos pedidos; padrões ('pasta/*.xlsx') são expandidos aqui,
    porque o PowerShell e o cmd do Windows não expandem sozinhos. O arquivo
    de bloqueio que o Excel (``~$``) e o LibreOffice (``.~lock.…#``) criam
    com a planilha aberta é ignorado quando vem de um padrão, com aviso
    (R4); passado pelo nome, continua dando erro de leitura."""
    saida: list[Path] = []
    for a in arquivos:
        if any(ch in a for ch in "*?["):
            achados = sorted(Path(p) for p in glob.glob(a))
            if not achados:
                _fail(ExitCode.UNREADABLE_INPUT, f"Nenhum arquivo casa com {a}")
            for achado in achados:
                if _BLOQUEIO.fullmatch(achado.name):
                    typer.echo(
                        f"Atenção: {_literal(str(achado))} é o arquivo de bloqueio de uma planilha aberta "
                        "e foi ignorado.",
                        err=True,
                    )
                else:
                    saida.append(achado)
        else:
            saida.append(Path(a))
    return list(dict.fromkeys(saida))


def _sem_as_saidas(entradas: list[Path], saidas: list[Path]) -> list[Path]:
    """Tira das entradas as que são uma das saídas (R4): o consolidado do
    mês passado na pasta de entrada não entra de novo, e uma saída nunca
    sobrescreve uma entrada. Compara o caminho resolvido (pega link e caixa
    no Windows)."""
    ficam = []
    for e in entradas:
        if any(_mesmo_arquivo(e, s) for s in saidas):
            typer.echo(
                f"Atenção: {_literal(str(e))} é a saída deste comando e foi tirado das entradas.", err=True
            )
        else:
            ficam.append(e)
    if not ficam:
        _fail(
            ExitCode.INVALID_RECIPE, "Nenhum arquivo de entrada sobrou: a única entrada era a própria saída."
        )
    return ficam


def _mesmo_arquivo(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _conferir_relatorio(relatorio: Path, receita: Path, entradas: list[Path], overwrite: bool) -> None:
    """O ``--report`` nunca destrói nada (R2): não sobrescreve sem
    ``--overwrite`` e nunca cai em cima da receita ou de uma entrada, nem
    com ``--overwrite``. Conferido antes de processar o primeiro arquivo."""
    if _mesmo_arquivo(relatorio, receita) or any(_mesmo_arquivo(relatorio, e) for e in entradas):
        _fail(
            ExitCode.INVALID_RECIPE,
            f"O relatório não pode ser gravado em {relatorio}: é a receita ou um dos arquivos de entrada.",
            "Escolha outro nome para --report. Nada foi gravado.",
        )
    if relatorio.is_dir():
        _fail(ExitCode.INVALID_RECIPE, f"--report precisa ser um arquivo, não uma pasta: {relatorio}")
    if relatorio.exists() and not overwrite:
        _fail(
            ExitCode.INVALID_RECIPE,
            f"O relatório já existe: {relatorio}",
            "Use --overwrite para substituir. Nada foi gravado.",
        )


def _gravar_relatorio(
    relatorio: Path, recipe: Recipe, itens: list[dict[str, Any]], combinado: dict[str, Any] | None = None
) -> None:
    """Grava o relatório por um temporário renomeado no fim (R2). Com
    ``--combine``, ``combinado`` é a conta da saída juntada."""
    dados: dict[str, Any] = {"receita": recipe.name, "arquivos": itens}
    if combinado is not None:
        dados["combinado"] = combinado
    corpo = json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    gravar_juntos({relatorio: lambda tmp: tmp.write_text(corpo, encoding="utf-8")})


def _item_ok(arquivo: Path, destino: Path, r: RunReport) -> dict[str, Any]:
    # ``arquivo`` é o caminho como foi digitado (ou como o padrão o casou),
    # nunca resolvido para absoluto (R2). ``linhas`` = ``linhas_gravadas``.
    return {
        "arquivo": str(arquivo),
        "ok": True,
        "saida": str(destino),
        "linhas": r.rows_written,
        "colunas": r.table.width,
        **r.to_dict(),
    }


def _item_falha(arquivo: Path, falha: _Falha) -> dict[str, Any]:
    return {"arquivo": str(arquivo), "ok": False, "codigo": int(falha.code), **falha.relatorio}


@app.command(epilog=_EPILOG)
def run(
    receita: Annotated[Path, typer.Argument(help="Receita .wolfz.json.", show_default=False)],
    arquivos: Annotated[
        list[str],
        typer.Argument(
            help="Planilha(s) a limpar (.xlsx, .xls, .ods ou .csv), ou um padrão como 'entrada/*.xlsx'.",
            show_default=False,
        ),
    ],
    saida: Annotated[
        str,
        typer.Option(
            "--output", "-o", help="Arquivo de saída, ou pasta (o nome vem da entrada).", show_default=False
        ),
    ],
    formato: Annotated[Formato, typer.Option("--format", "-f", help="Formato da saída.")] = Formato.csv,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Sobrescreve a saída (e o --report) se já existir.")
    ] = False,
    sep: Annotated[
        Sep, typer.Option("--sep", help="Separador do CSV (';' abre direto no Excel em português).")
    ] = Sep.virgula,
    decimal_comma: Annotated[
        bool, typer.Option("--decimal-comma", help="Número no CSV com vírgula decimal (1234,5).")
    ] = False,
    neutralizar: Annotated[
        bool,
        typer.Option(
            "--neutralize-formulas",
            help="Prefixa com ' o texto do CSV que começa com =, +, -, @ (evita injeção de fórmula).",
        ),
    ] = False,
    relatorio: Annotated[
        Path | None,
        typer.Option(
            "--report",
            help="Grava um relatório em JSON: linhas lidas e gravadas, por arquivo e por passo, "
            "sem valor de célula.",
            show_default=False,
        ),
    ] = None,
    max_drop: Annotated[
        str | None,
        typer.Option(
            "--max-drop",
            help="Para sem gravar (código 1) se a receita tirar mais que este percentual das linhas lidas "
            "(ex.: 1%, 0.5%, 0). Linhas vazias, título e cabeçalho não contam. Em lote, vale por arquivo.",
            show_default=False,
        ),
    ] = None,
    mostrar_valores: Annotated[
        bool,
        typer.Option(
            "--show-values",
            help="Mostra no terminal os valores das células de uma verificação reprovada ou de um erro. "
            "Eles nunca vão para o --report.",
        ),
    ] = False,
    sheet: Annotated[
        str | None,
        typer.Option(
            "--sheet",
            help="Aba a ler, no lugar da aba da receita (e do padrão de nome). Lê só essa aba.",
            show_default=False,
        ),
    ] = None,
    combinar: Annotated[
        bool,
        typer.Option(
            "--combine",
            help="Junta as tabelas de todos os arquivos num arquivo só (-o é um arquivo), com a coluna de "
            "origem. Se um arquivo falhar, nada é gravado.",
        ),
    ] = False,
    origem: Annotated[
        str,
        typer.Option(
            "--origin-col", help="Com --combine: nome da coluna com o nome do arquivo de cada linha."
        ),
    ] = "arquivo",
    sem_origem: Annotated[
        bool, typer.Option("--no-origin-col", help="Com --combine: sem a coluna com o nome do arquivo.")
    ] = False,
) -> None:
    """Aplica uma receita a uma ou mais planilhas e grava a tabela limpa.

    Nada é gravado para um arquivo se algum passo falhar nele.
    """
    limite = _max_drop(max_drop)
    if (origem != "arquivo" or sem_origem) and not combinar:
        _fail(ExitCode.INVALID_RECIPE, "--origin-col e --no-origin-col só valem com --combine.")
    if origem != "arquivo" and sem_origem:
        _fail(ExitCode.INVALID_RECIPE, "Use --origin-col ou --no-origin-col, não os dois.")
    if not origem.strip():
        _fail(ExitCode.INVALID_RECIPE, "--origin-col precisa de um nome.")
    recipe = _carregar_receita(receita)
    entradas = _expandir(arquivos)
    opcoes = OpcoesCsv(separator="\t" if sep is Sep.tab else sep.value, decimal_comma=decimal_comma)

    if combinar:
        destino = Path(saida)
        if saida.endswith(("/", "\\")) or destino.is_dir():
            _fail(
                ExitCode.INVALID_RECIPE, f"Com --combine, -o precisa ser um arquivo, não uma pasta: {saida}"
            )
        entradas = _sem_as_saidas(entradas, [destino])
        if relatorio is not None:
            _conferir_relatorio(relatorio, receita, [*entradas, destino], overwrite)
        _juntar_arquivos(
            recipe,
            entradas,
            destino,
            formato,
            opcoes,
            neutralizar,
            overwrite,
            relatorio,
            limite,
            mostrar_valores,
            sheet,
            None if sem_origem else origem,
        )
        return

    if len(entradas) == 1:
        entradas = _sem_as_saidas(entradas, [_output_path(saida, entradas[0], formato)])
    else:
        entradas = _sem_as_saidas(entradas, [Path(saida) / f"{a.stem}.{formato.value}" for a in entradas])
    if relatorio is not None:
        _conferir_relatorio(relatorio, receita, entradas, overwrite)

    if len(entradas) == 1:
        arquivo = entradas[0]
        destino = _output_path(saida, arquivo, formato)
        if relatorio is not None and _mesmo_arquivo(relatorio, destino):
            _fail(ExitCode.INVALID_RECIPE, f"--report e -o apontam para o mesmo arquivo: {relatorio}")
        try:
            r = _processar(
                recipe,
                arquivo,
                destino,
                formato,
                opcoes,
                neutralizar,
                overwrite,
                limite,
                mostrar_valores,
                sheet,
            )
        except _Falha as falha:
            if relatorio is not None:
                _gravar_relatorio(relatorio, recipe, [_item_falha(arquivo, falha)])
            _fail(falha.code, *falha.lines)
        typer.echo(f"{r.rows_written} linhas, {r.table.width} colunas -> {destino}")
        _imprimir_resumo(r)
        _avisar_formulas(r.table, formato, neutralizar)
        if relatorio is not None:
            _gravar_relatorio(relatorio, recipe, [_item_ok(arquivo, destino, r)])
        return

    _lote(
        recipe,
        entradas,
        saida,
        formato,
        opcoes,
        neutralizar,
        overwrite,
        relatorio,
        limite,
        mostrar_valores,
        sheet,
    )


def _avisar_formulas(result: pl.DataFrame, formato: Formato, neutralizar: bool) -> None:
    formulas = celulas_formula(result)
    if formulas and formato is Formato.csv and not neutralizar:
        typer.echo(
            f"Atenção: {formulas} células de texto começam com =, +, -, @ e podem virar fórmula ao abrir "
            "o CSV numa planilha. Use --neutralize-formulas se o arquivo vier de fonte não confiável.",
            err=True,
        )


def _lote(
    recipe: Recipe,
    entradas: list[Path],
    saida: str,
    formato: Formato,
    opcoes: OpcoesCsv,
    neutralizar: bool,
    overwrite: bool,
    relatorio: Path | None,
    max_drop: float | None = None,
    mostrar_valores: bool = False,
    sheet: str | None = None,
) -> None:
    """Vários arquivos (F2.F3): cada um à parte; uma falha não para os
    outros. No fim, a tabela do que deu certo e do que falhou, e o resumo
    das linhas dos arquivos que alertaram."""
    pasta = Path(saida)
    if pasta.exists() and not pasta.is_dir():
        _fail(ExitCode.INVALID_RECIPE, f"Com vários arquivos, -o precisa ser uma pasta: {saida}")
    nomes = [a.stem for a in entradas]
    repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
    if repetidos:
        _fail(
            ExitCode.INVALID_RECIPE, f"Arquivos com o mesmo nome dariam a mesma saída: {', '.join(repetidos)}"
        )
    destinos = [pasta / f"{a.stem}.{formato.value}" for a in entradas]
    if relatorio is not None and any(_mesmo_arquivo(relatorio, d) for d in destinos):
        _fail(ExitCode.INVALID_RECIPE, f"--report cairia em cima de uma das saídas: {relatorio}")
    pasta.mkdir(parents=True, exist_ok=True)

    itens: list[dict[str, Any]] = []
    linhas_terminal: list[str] = []
    reports: dict[int, RunReport] = {}
    pior = ExitCode.OK
    for i, (arquivo, destino) in enumerate(zip(entradas, destinos, strict=True)):
        try:
            r = _processar(
                recipe,
                arquivo,
                destino,
                formato,
                opcoes,
                neutralizar,
                overwrite,
                max_drop,
                mostrar_valores,
                sheet,
            )
        except _Falha as falha:
            pior = max(pior, falha.code)
            itens.append(_item_falha(arquivo, falha))
            linhas_terminal.append(" ".join(falha.lines))
            continue
        reports[i] = r
        itens.append(_item_ok(arquivo, destino, r))
        linhas_terminal.append("")

    # O nome vem da receita, que pode vir de terceiro: sem controle nem ANSI (A1, R9).
    titulo = f"{_literal(recipe.name, 60)}: {sum(r['ok'] for r in itens)} de {len(itens)} arquivos"
    tabela = Table(title=escape(titulo))
    tabela.add_column("Arquivo")
    tabela.add_column("Resultado")
    for i, item in enumerate(itens):
        nome = escape(_literal(Path(item["arquivo"]).name, 60))
        if item["ok"]:
            r = reports[i]
            cor, rotulo = ("yellow", "atenção") if r.alert else ("green", "ok")
            contas = f"lidas {_int_br(r.rows_read)} · gravadas {_int_br(r.rows_written)}"
            saida_nome = escape(_literal(Path(item["saida"]).name))
            tabela.add_row(nome, f"[{cor}]{rotulo}[/{cor}] {contas} -> {saida_nome}")
        else:
            tabela.add_row(nome, f"[red]falhou[/red] {escape(_literal(linhas_terminal[i]))}")
    Console(width=max(120, Console().width)).print(tabela)
    for i, r in reports.items():
        if r.alert or r.outside_columns or r.hidden_sheets or r.divergences:
            _imprimir_resumo(r, prefixo=f"{_literal(entradas[i].name, 60)}: ")
    if relatorio is not None:
        _gravar_relatorio(relatorio, recipe, itens)
    if pior is not ExitCode.OK:
        raise typer.Exit(int(pior))


def _juntar_arquivos(
    recipe: Recipe,
    entradas: list[Path],
    destino: Path,
    formato: Formato,
    opcoes: OpcoesCsv,
    neutralizar: bool,
    overwrite: bool,
    relatorio: Path | None,
    max_drop: float | None,
    mostrar_valores: bool,
    sheet: str | None,
    origem: str | None,
) -> None:
    """``--combine`` (F3, ADR-12): a receita roda em cada arquivo, as
    tabelas são empilhadas num arquivo só, com a coluna de origem (só o nome
    do arquivo, nunca a pasta). Tudo ou nada: se um arquivo falhar, nada é
    gravado. O lote passa antes pelo teto de memória (R3)."""
    if destino.exists() and not overwrite:
        _fail(ExitCode.INVALID_RECIPE, f"A saída já existe: {destino}", "Use --overwrite para substituir.")
    nomes = [a.name for a in entradas]
    repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
    if repetidos and origem is not None:
        _fail(
            ExitCode.INVALID_RECIPE,
            f"Arquivos com o mesmo nome em pastas diferentes: {', '.join(repetidos)}. "
            "A coluna de origem não conseguiria separá-los.",
        )
    try:
        teto_de_juntar(entradas)
    except ErroAoJuntar as exc:
        _fail(ExitCode.INVALID_RECIPE, f"{exc.titulo}: {exc.mensagem}", "Nada foi gravado.")

    itens: list[dict[str, Any]] = []
    feitos: list[tuple[Path, RunReport]] = []
    falhas: list[tuple[Path, _Falha]] = []
    for arquivo in entradas:
        try:
            r = _calcular(recipe, arquivo, sheet, max_drop, mostrar_valores)
        except _Falha as falha:
            falhas.append((arquivo, falha))
            itens.append(_item_falha(arquivo, falha))
            continue
        feitos.append((arquivo, r))
        itens.append({"arquivo": str(arquivo), "ok": True, **r.to_dict()})

    combinado: RunReport | None = None
    if not falhas:
        try:
            juncao = empilhar([(a.name, r.table) for a, r in feitos], origem)
        except ErroAoJuntar as exc:
            falhas.append(
                (Path("(junção)"), _Falha(ExitCode.STEP_ERROR, f"{exc.titulo}: {exc.mensagem}", relatorio={}))
            )
        else:
            combinado = somar([como_parte(r, a.name) for a, r in feitos], juncao.tabela, juncao.divergencias)
    if falhas or combinado is None:
        pior = max(f.code for _, f in falhas)
        quantas = "1 arquivo não passou" if len(falhas) == 1 else f"{len(falhas)} arquivos não passaram"
        typer.echo(f"Lote parado: {quantas}.", err=True)
        for arquivo, falha in falhas:
            typer.echo(f"  {_literal(arquivo.name, 60)}: {' '.join(falha.lines)}", err=True)
        if feitos:
            outros = "1 arquivo passou" if len(feitos) == 1 else f"Os outros {len(feitos)} arquivos passaram"
            typer.echo(f"{outros}, mas a saída junta todos.", err=True)
        typer.echo("Nenhum arquivo consolidado foi gravado.", err=True)
        if relatorio is not None:
            _gravar_relatorio(relatorio, recipe, itens)
        raise typer.Exit(int(pior))
    try:
        gravar_juntos(
            {destino: escritor(formato.value, combinado.table, opcoes, neutralizar, aba=recipe.name)}
        )
    except ExportError as exc:
        _fail(ExitCode.INVALID_RECIPE, str(exc), "Nada foi gravado.")
    typer.echo(
        f"{combinado.rows_written} linhas, {combinado.table.width} colunas -> {destino} "
        f"({len(feitos)} {'arquivo' if len(feitos) == 1 else 'arquivos'} juntos)"
    )
    for arquivo, r in feitos:
        nome = _literal(arquivo.name, 60)
        contas = f"lidas {_int_br(r.rows_read)} · gravadas {_int_br(r.rows_written)}"
        typer.secho(
            f"{'Atenção: ' if r.alert else '  '}{nome}  {contas}",
            err=True,
            fg="yellow" if r.alert else None,
        )
        if r.alert or r.outside_columns or r.hidden_sheets or r.divergences:
            for texto, _ in _resumo(r, f"{nome}: ")[1:]:
                typer.secho(texto, err=True, fg="yellow")
            for texto in [*_avisos_fora_da_area(r, f"{nome}: "), *_avisos_da_juncao(r, f"{nome}: ")]:
                typer.secho(texto, err=True, fg="yellow")
    for texto in _avisos_da_juncao(combinado, o_que="os arquivos"):
        typer.secho(texto, err=True, fg="yellow")
    _avisar_formulas(combinado.table, formato, neutralizar)
    if relatorio is not None:
        corpo = {"saida": str(destino), "linhas": combinado.rows_written, "colunas": combinado.table.width}
        _gravar_relatorio(relatorio, recipe, itens, combinado={**corpo, **combinado.to_dict()})


@app.command()
def ui(
    port: Annotated[
        int,
        typer.Option("--port", min=0, max=65535, help="Porta local (padrão: uma livre, escolhida na hora)."),
    ] = 0,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Não abre o navegador; só mostra o endereço.")
    ] = False,
) -> None:
    """Abre a interface no navegador.

    A API escuta só em 127.0.0.1, com uma chave de acesso nova a cada
    execução. O endereço impresso já traz a chave; Ctrl+C encerra.
    """
    # Importa a API só aqui: os outros comandos não pagam o custo do FastAPI.
    from wolfz.api.security import STATIC_DIR
    from wolfz.api.server import abrir_quando_pronto, criar_servidor, porta_disponivel

    if port and not porta_disponivel(port):
        _fail(
            ExitCode.INVALID_RECIPE,
            f"A porta {port} já está em uso (outro WolfzBR aberto?).",
            "Use outra com --port, ou deixe sem --port para usar uma livre.",
        )
    servidor, url = criar_servidor(port=port)
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo("Atenção: a interface não foi compilada neste pacote; só a API vai responder.", err=True)
    typer.echo(f"WolfzBR rodando em {url}")
    typer.echo("Deixe este terminal aberto enquanto usa a interface. Ctrl+C encerra.")
    if not no_browser:
        abrir_quando_pronto(servidor, url)
    servidor.run()


@app.command()
def schema() -> None:
    """Imprime o JSON Schema da receita (wolfz schema > recipe.schema.json)."""
    # ASCII puro: redirecionar para arquivo no Windows não depende do encoding do console.
    typer.echo(json.dumps(recipe_json_schema(), indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# wolfz inspect
# ---------------------------------------------------------------------------


def _int_br(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _pct(x: float) -> str:
    return "0%" if x == 0 else f"{x * 100:.1f}%".replace(".", ",")


def _valor(v: float | date | None) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):  # data e hora: sem segundos no perfil (ux.md §3.3)
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if float(v).is_integer():
        return _int_br(int(v))
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _cabecalho(t: LoadedTable, p: TableProfile) -> list[str]:
    linhas = [f"[bold]{t.path.name}[/bold] ({t.format})"]
    if t.sheet is not None:
        outras = [f"{s.name} (oculta)" if s.hidden else s.name for s in t.sheets]
        linhas.append(f"Aba: {t.sheet} · abas: {', '.join(outras)}")
        linhas.append(f"Cabeçalho na linha {t.header_row} (mude com --header-row)")
    linhas.append(f"{_int_br(p.total_rows)} linhas, {len(p.columns)} colunas")
    if p.is_sample:
        linhas.append(f"[yellow]Perfil numa amostra de {_int_br(p.sampled_rows)} linhas.[/yellow]")
    return linhas


def _tabela(perfil: TableProfile) -> Table:
    tabela = Table(show_lines=False, header_style="bold")
    for nome, justify in [
        ("Coluna", "left"),
        ("Tipo", "left"),
        ("Nulos", "right"),
        ("Marcadores", "right"),
        ("Distintos", "right"),
        ("Formas", "left"),
        ("Exemplos", "left"),
        ("Mín.", "right"),
        ("Máx.", "right"),
    ]:
        # Em terminal estreito o texto quebra em vez de virar "Munic…".
        tabela.add_column(nome, justify=justify, overflow="fold")  # type: ignore[arg-type]
    for c in perfil.columns:
        tabela.add_row(*_linha(c))
    return tabela


def _linha(c: ColumnProfile) -> list[str]:
    tipo = c.inferred_type if c.type_rate >= 0.999 else f"{c.inferred_type} ({_pct(c.type_rate)})"
    formas = "\n".join(f"{s} ({_int_br(n)})" for s, n in c.top_shapes)
    return [
        c.name,
        tipo,
        _pct(c.null_pct),
        _pct(c.null_marker_pct),
        _int_br(c.distinct),
        formas,
        "\n".join(c.examples),
        _valor(c.minimum),
        _valor(c.maximum),
    ]


@app.command()
def inspect(
    arquivo: Annotated[Path, typer.Argument(help="Planilha ou CSV.", show_default=False)],
    sheet: Annotated[
        str | None,
        typer.Option("--sheet", "-s", help="Aba (padrão: a primeira visível).", show_default=False),
    ] = None,
    header_row: Annotated[
        int | None,
        typer.Option(
            "--header-row",
            min=1,
            help="Linha do cabeçalho (padrão: a primeira não vazia).",
            show_default=False,
        ),
    ] = None,
    amostra: Annotated[int, typer.Option("--sample", min=1, help="Tamanho máximo da amostra.")] = SAMPLE_SIZE,
    como_json: Annotated[bool, typer.Option("--json", help="Saída em JSON, para scripts.")] = False,
) -> None:
    """Mostra o perfil de cada coluna: tipo, nulos, formas, exemplos, mínimo e máximo."""
    try:
        tabela = load_table(arquivo, sheet, header_row)
    except IngestError as exc:
        _fail(ExitCode.UNREADABLE_INPUT, f"{exc.title}: {exc.message}")
    except ValueError as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Uso incorreto: {exc}")
    perfil = profile_table(tabela.frame, amostra)

    if como_json:
        dados = {
            "arquivo": str(tabela.path),
            "formato": tabela.format,
            "aba": tabela.sheet,
            "linha_cabecalho": tabela.header_row,
            **perfil.to_dict(),
        }
        # ASCII puro: redirecionar para arquivo no Windows não depende do encoding do console.
        typer.echo(json.dumps(dados, indent=2))
        return
    console = Console(highlight=False)
    for linha in _cabecalho(tabela, perfil):
        console.print(linha)
    console.print(_tabela(perfil))

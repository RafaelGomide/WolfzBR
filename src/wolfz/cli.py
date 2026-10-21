"""CLI ``wolfz``: argumentos, saída no terminal e códigos de retorno.

Sem regra de negócio; os comandos chamam o núcleo (``wolfz.core``). As
mensagens de erro são as mesmas que a API devolve (``StepError.message``,
``RecipeError.errors``), para que interface e terminal falhem com o mesmo
texto (§5.4).
"""

from __future__ import annotations

import glob
import json
from datetime import date
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from wolfz import __version__
from wolfz.core.engine import StepError, collect, read_input
from wolfz.core.ingest import IngestError
from wolfz.core.profile import ColumnProfile, LoadedTable, TableProfile, load_table, profile_table
from wolfz.core.profile.column import SAMPLE_SIZE
from wolfz.core.recipe import Recipe, RecipeError, load_recipe, recipe_json_schema
from wolfz.export.dados import ExportError, OpcoesCsv, celulas_formula, escritor, gravar_juntos


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
    "à parte, com um relatório no fim. "
    "Códigos de saída: 0 ok · 1 um passo falhou (ou uma verificação reprovou) · "
    "2 receita inválida ou uso incorreto · 3 arquivo de entrada ilegível. "
    "Em lote, o maior código entre os arquivos."
)


class _Falha(Exception):
    """Falha de um arquivo: o código de saída e as linhas da mensagem."""

    def __init__(self, code: ExitCode, *lines: str):
        super().__init__(lines[0] if lines else "")
        self.code = code
        self.lines = lines


def _carregar_receita(receita: Path) -> Recipe:
    try:
        return load_recipe(receita)
    except FileNotFoundError:
        _fail(ExitCode.INVALID_RECIPE, f"Receita não encontrada: {receita}")
    except RecipeError as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Receita inválida: {receita}", *(f"  {e}" for e in exc.errors))
    except (UnicodeDecodeError, OSError) as exc:
        _fail(ExitCode.INVALID_RECIPE, f"Não foi possível ler a receita {receita}: {_first_line(exc)}")


def _processar(
    recipe: Recipe,
    arquivo: Path,
    destino: Path,
    formato: Formato,
    opcoes: OpcoesCsv,
    neutralizar: bool,
    overwrite: bool,
) -> pl.DataFrame:
    """Aplica a receita a um arquivo e grava. Nada é gravado se algo falhar."""
    if destino.exists() and not overwrite:
        raise _Falha(
            ExitCode.INVALID_RECIPE, f"A saída já existe: {destino}", "Use --overwrite para substituir."
        )
    if not arquivo.is_file():
        raise _Falha(ExitCode.UNREADABLE_INPUT, f"Arquivo não encontrado: {arquivo}")
    try:
        df = read_input(recipe, arquivo)
    except IngestError as exc:
        raise _Falha(ExitCode.UNREADABLE_INPUT, f"{exc.title}: {exc.message}") from None
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise _Falha(
            ExitCode.UNREADABLE_INPUT, f"Não foi possível ler {arquivo}: {_first_line(exc)}"
        ) from None
    try:
        result = collect(recipe, df.lazy())
    except StepError as exc:
        columns = ", ".join(exc.available_columns) or "(nenhuma)"
        raise _Falha(
            ExitCode.STEP_ERROR,
            f"{exc.title}: {exc.message}",
            f"Colunas disponíveis antes do passo {exc.step_id}: {columns}",
            "Nada foi gravado.",
        ) from None
    try:
        gravar_juntos({destino: escritor(formato.value, result, opcoes, neutralizar, aba=recipe.name)})
    except ExportError as exc:
        raise _Falha(ExitCode.INVALID_RECIPE, str(exc), "Nada foi gravado.") from None
    return result


def _expandir(arquivos: list[str]) -> list[Path]:
    """Os arquivos pedidos; padrões ('pasta/*.xlsx') são expandidos aqui,
    porque o PowerShell e o cmd do Windows não expandem sozinhos."""
    saida: list[Path] = []
    for a in arquivos:
        if any(ch in a for ch in "*?["):
            achados = sorted(Path(p) for p in glob.glob(a))
            if not achados:
                _fail(ExitCode.UNREADABLE_INPUT, f"Nenhum arquivo casa com {a}")
            saida += achados
        else:
            saida.append(Path(a))
    return list(dict.fromkeys(saida))


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
        bool, typer.Option("--overwrite", help="Sobrescreve a saída se ela já existir.")
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
        typer.Option("--report", help="Em lote: grava o relatório por arquivo em JSON.", show_default=False),
    ] = None,
) -> None:
    """Aplica uma receita a uma ou mais planilhas e grava a tabela limpa.

    Nada é gravado para um arquivo se algum passo falhar nele.
    """
    recipe = _carregar_receita(receita)
    entradas = _expandir(arquivos)
    opcoes = OpcoesCsv(separator="\t" if sep is Sep.tab else sep.value, decimal_comma=decimal_comma)

    if len(entradas) == 1 and relatorio is None:
        arquivo = entradas[0]
        destino = _output_path(saida, arquivo, formato)
        try:
            result = _processar(recipe, arquivo, destino, formato, opcoes, neutralizar, overwrite)
        except _Falha as falha:
            _fail(falha.code, *falha.lines)
        typer.echo(f"{result.height} linhas, {result.width} colunas -> {destino}")
        _avisar_formulas(result, formato, neutralizar)
        return

    _lote(recipe, entradas, saida, formato, opcoes, neutralizar, overwrite, relatorio)


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
) -> None:
    """Vários arquivos (F2.F3): cada um à parte; uma falha não para os
    outros. No fim, a tabela do que deu certo e do que falhou."""
    pasta = Path(saida)
    if pasta.exists() and not pasta.is_dir():
        _fail(ExitCode.INVALID_RECIPE, f"Com vários arquivos, -o precisa ser uma pasta: {saida}")
    nomes = [a.stem for a in entradas]
    repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
    if repetidos:
        _fail(
            ExitCode.INVALID_RECIPE, f"Arquivos com o mesmo nome dariam a mesma saída: {', '.join(repetidos)}"
        )
    pasta.mkdir(parents=True, exist_ok=True)

    linhas: list[dict] = []
    pior = ExitCode.OK
    for arquivo in entradas:
        destino = pasta / f"{arquivo.stem}.{formato.value}"
        try:
            result = _processar(recipe, arquivo, destino, formato, opcoes, neutralizar, overwrite)
        except _Falha as falha:
            pior = max(pior, falha.code)
            linhas.append(
                {
                    "arquivo": str(arquivo),
                    "ok": False,
                    "codigo": int(falha.code),
                    "erro": " ".join(falha.lines),
                }
            )
            continue
        linhas.append(
            {
                "arquivo": str(arquivo),
                "ok": True,
                "saida": str(destino),
                "linhas": result.height,
                "colunas": result.width,
            }
        )

    tabela = Table(title=f"{recipe.name}: {sum(r['ok'] for r in linhas)} de {len(linhas)} arquivos")
    tabela.add_column("Arquivo")
    tabela.add_column("Resultado")
    for r in linhas:
        if r["ok"]:
            tabela.add_row(
                Path(r["arquivo"]).name, f"[green]ok[/green] {r['linhas']} linhas -> {Path(r['saida']).name}"
            )
        else:
            tabela.add_row(Path(r["arquivo"]).name, f"[red]falhou[/red] {r['erro']}")
    Console(width=max(120, Console().width)).print(tabela)
    if relatorio is not None:
        relatorio.write_text(
            json.dumps({"receita": recipe.name, "arquivos": linhas}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if pior is not ExitCode.OK:
        raise typer.Exit(int(pior))


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

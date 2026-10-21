"""Mede quanto dos passos necessários as sugestões cobrem (pronto da Fase 2).

Para cada um dos 10 arquivos de validação (``dev/dados_validacao/``, F1.B5),
parte da receita que a importação monta (detecção) e segue o roteiro da
cronometragem passo a passo. Antes de cada passo, olha as sugestões da
tabela daquele momento — as mesmas que a interface mostra — e confere se
alguma propõe aquele passo; depois aplica o passo do roteiro, como a pessoa
faria, e segue.

Um passo de várias colunas conta pela fração das colunas que alguma
sugestão da mesma operação cobre (as sugestões vêm uma por coluna). Os
passos da detecção contam como cobertos: já chegam prontos na receita.

Só mede: os arquivos de validação não servem para ajustar regra (F1.B5).
Rode com::

    uv run python scripts/medir_sugestoes.py
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from wolfz.core.detect import detect_tables, main_table
from wolfz.core.engine import collect, read_input
from wolfz.core.ingest import detect_format, import_file, read_sheet
from wolfz.core.ingest.csv import open_csv_lazy
from wolfz.core.recipe import load_recipe, recipe_from_dict
from wolfz.core.suggest import suggest
from wolfz.core.workspace import RAW_FILE, Workspace

BASE = Path(__file__).resolve().parent.parent / "dev" / "dados_validacao"

INMET_DATA, INMET_HORA = "DATA (YYYY-MM-DD)", "HORA (UTC)"
INEP_UF = "Unidade_da_Federação"
INEP_PRE = "Matrícula por Dependência Administrativa_Pré-escolar_"
INEP_ALF = "Matrícula por Dependência Administrativa_Classe de Alfabetização_"
DEPENDENCIAS = ["Total", "Federal", "Estadual", "Municipal", "Particular"]


@dataclass
class Arquivo:
    pasta: str
    aba: str | None
    # Passos depois da detecção. Uma função recebe as colunas do momento.
    roteiro: list[Any] = field(default_factory=list)


def _todas_menos(*fora: str):
    return lambda cols: [c for c in cols if c not in fora]


ARQUIVOS = [
    Arquivo(
        "01_senatran_frota_municipio_tipo",
        None,
        [
            {"op": "drop_cols", "cols": ["TOTAL"]},
            {
                "op": "unpivot",
                "index": ["UF", "MUNICIPIO"],
                "variable_name": "tipo",
                "value_name": "quantidade",
            },
            {"op": "cast", "types": {"quantidade": "int"}},
        ],
    ),
    Arquivo(
        "02_receita_arrecadacao_federal",
        "2025",
        [
            {"op": "trim", "cols": ["RECEITAS"]},
            {"op": "drop_cols", "cols": ["TOTAL"]},
            {"op": "rename", "mapping": {"RECEITAS": "receita"}},
            {"op": "unpivot", "index": ["receita"], "variable_name": "mes", "value_name": "valor"},
            {"op": "parse_decimal_br", "cols": ["valor"]},
        ],
    ),
    Arquivo(
        "03_conab_feijao_serie_historica",
        "Produção",
        [
            {
                "op": "drop_rows_where",
                "col": "REGIÃO/UF",
                "match": "in",
                "value": [
                    "NORTE",
                    "NORDESTE",
                    "CENTRO-OESTE",
                    "SUDESTE",
                    "SUL",
                    "NORTE/NORDESTE",
                    "CENTRO-SUL",
                    "BRASIL",
                ],
            },
            {"op": "rename", "mapping": {"REGIÃO/UF": "uf"}},
            {"op": "unpivot", "index": ["uf"], "variable_name": "safra", "value_name": "producao"},
            {"op": "trim", "cols": ["safra"]},
            {"op": "parse_decimal_br", "cols": ["producao"]},
        ],
    ),
    Arquivo(
        "04_inep_sinopse_1996",
        "1.1",
        [
            {"op": "drop_empty_rows"},
            {
                "op": "drop_rows_where",
                "col": INEP_UF,
                "match": "in",
                "value": ["Brasil", "Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"],
            },
            {"op": "drop_cols", "cols": [INEP_PRE + "Total"] + [INEP_ALF + d for d in DEPENDENCIAS]},
            {"op": "rename", "mapping": {INEP_UF: "uf"}},
            {"op": "unpivot", "index": ["uf"], "variable_name": "dependencia", "value_name": "matriculas"},
            {"op": "parse_decimal_br", "cols": ["matriculas"], "dash_is_zero": True},
            {"op": "cast", "types": {"matriculas": "int"}},
        ],
    ),
    Arquivo(
        "05_tesouro_resultado_serie_historica",
        "1.1",
        [
            {"op": "unpivot", "index": ["Discriminação"], "variable_name": "mes", "value_name": "valor"},
            {"op": "parse_date_br", "cols": ["mes"]},
            {"op": "parse_decimal_br", "cols": ["valor"]},
        ],
    ),
    Arquivo(
        "06_tesouro_transferencias_municipios",
        None,
        [
            {"op": "drop_cols", "cols": ["Item transferência"]},
            {"op": "merge_cols", "cols": ["Mês", "ANO"], "separator": "/", "into": "data"},
            {"op": "parse_month_year", "cols": ["data"]},
            {
                "op": "unpivot",
                "index": ["Município", "UF", "data", "Transferência"],
                "variable_name": "decendio",
                "value_name": "valor",
            },
            {"op": "parse_decimal_br", "cols": ["valor"]},
        ],
    ),
    Arquivo(
        "07_inmet_estacao_automatica",
        None,
        [
            {
                "op": "replace",
                "cols": _todas_menos(INMET_DATA, INMET_HORA),
                "old": "-9999",
                "new": None,
                "whole": True,
            },
            {"op": "parse_decimal_br", "cols": _todas_menos(INMET_DATA, INMET_HORA)},
            {"op": "parse_date_br", "cols": [INMET_DATA]},
        ],
    ),
    Arquivo(
        "08_aneel_conta_bandeira",
        None,
        [
            {"op": "trim", "cols": ["SigAgente"]},
            {"op": "parse_date_br", "cols": ["DatCompetencia", "DatGeracaoConjuntoDados"]},
            {"op": "parse_decimal_br", "cols": lambda cols: [c for c in cols if c.startswith("Vlr")]},
        ],
    ),
    Arquivo(
        "09_alagoas_frota_municipio",
        None,
        [
            {"op": "drop_rows_where", "col": "inf_subcategoria", "match": "starts_with", "value": "1. "},
            {"op": "split_col", "col": "inf_subcategoria", "delimiter": ". ", "into": ["codigo", "tipo"]},
            {"op": "drop_cols", "cols": ["variavel", "inf_categoria", "codigo"]},
            {"op": "cast", "types": {"valor": "int", "ano": "int"}},
        ],
    ),
    Arquivo(
        "10_ons_reservatorios",
        None,
        [
            {
                "op": "parse_decimal_br",
                "cols": lambda cols: [c for c in cols if c.startswith("val_") and c != "val_tipoperda"],
                "decimal": ".",
            },
            {"op": "parse_date_br", "cols": ["dat_entrada"]},
        ],
    ),
]

# Converter para número é uma intenção só: o roteiro diz "número BR" ou
# "inteiro", e a sugestão pode vir como moeda, sinais do IBGE ou cast.
NUMERO = {"parse_decimal_br", "parse_brl", "parse_ibge_value"}


def _receita(passos: list[dict]) -> Any:
    return recipe_from_dict(
        {
            "wolfz_version": "0.1",
            "name": "medição",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


def _intencao(passo: dict) -> dict[str, str]:
    """Coluna -> o que o passo faz com ela: 'numero', 'data' ou outro tipo."""
    op = passo["op"]
    if op == "cast":
        return {c: "numero" if t in ("int", "float") else t for c, t in passo["types"].items()}
    if op in NUMERO:
        return dict.fromkeys(passo["cols"], "numero")
    if op == "parse_date_br":
        return dict.fromkeys(passo["cols"], "date")
    return {}


def _numero(precisa: dict, sugeridos: list[dict]) -> tuple[float, str]:
    """Colunas que alguma sugestão converte para o mesmo tipo (número ou
    data), pela operação que for. Ponto decimal e traço como zero, quando o
    roteiro pede, têm de vir na sugestão."""
    alvo = _intencao(precisa)
    so_ponto = precisa["op"] == "parse_decimal_br" and precisa.get("decimal") == "."
    traco = precisa["op"] == "parse_decimal_br" and precisa.get("dash_is_zero")
    cobertas: set[str] = set()
    for s in sugeridos:
        if so_ponto and (s["op"] != "parse_decimal_br" or s.get("decimal") != "."):
            continue
        if traco and s["op"] == "parse_decimal_br" and not s.get("dash_is_zero"):
            continue
        cobertas |= {c for c, t in _intencao(s).items() if alvo.get(c) == t}
    ok = len(set(alvo) & cobertas)
    return ok / len(alvo), f"{ok}/{len(alvo)} colunas convertidas"


def _cobertura(precisa: dict, sugeridos: list[dict]) -> tuple[float, str]:
    """Fração do passo que as sugestões cobrem, e o porquê."""
    op = precisa["op"]
    if op in NUMERO or op in ("cast", "parse_date_br"):
        return _numero(precisa, sugeridos)
    if op == "drop_empty_cols":
        op, precisa = "drop_cols", {"op": "drop_cols", "cols": precisa["_tiradas"]}
    mesmos = [s for s in sugeridos if s["op"] == op]
    if not mesmos:
        return 0.0, "nenhuma sugestão dessa operação"
    if "cols" in precisa and op != "merge_cols":
        cobertas: set[str] = set()
        for s in mesmos:
            if op == "replace" and s.get("old") != precisa["old"]:
                continue
            cobertas |= set(s.get("cols", []))
        alvo = set(precisa["cols"])
        ok = len(alvo & cobertas)
        return ok / len(alvo), f"{ok}/{len(alvo)} colunas"
    if op == "unpivot":
        ok = any(set(s["index"]) == set(precisa["index"]) for s in mesmos)
        return float(ok), "mesmas colunas fixas" if ok else "colunas fixas diferentes"
    if op == "cast":
        tipos: dict = {}
        for s in mesmos:
            tipos |= s["types"]
        ok = sum(tipos.get(c) == t for c, t in precisa["types"].items())
        return ok / len(precisa["types"]), f"{ok}/{len(precisa['types'])} tipos"
    if op == "rename":
        mapa: dict = {}
        for s in mesmos:
            mapa |= s["mapping"]
        ok = sum(mapa.get(c) == n for c, n in precisa["mapping"].items())
        return ok / len(precisa["mapping"]), "nome"
    if op == "drop_rows_where":
        alvo = precisa["value"] if isinstance(precisa["value"], list) else [precisa["value"]]
        vistos: set = set()
        for s in mesmos:
            if s["col"] == precisa["col"]:
                v = s["value"]
                vistos |= set(v) if isinstance(v, list) else {v}
        ok = len(set(alvo) & vistos)
        return ok / len(alvo), f"{ok}/{len(alvo)} valores"
    if op == "merge_cols":
        ok = any(s["cols"] == precisa["cols"] for s in mesmos)
        return float(ok), "colunas"
    if op == "split_col":
        ok = any(s["col"] == precisa["col"] and s["delimiter"] == precisa["delimiter"] for s in mesmos)
        return float(ok), "coluna e separador"
    return 1.0, "operação sugerida"


Linha = tuple[str, float, str]


def seguir_roteiro(
    entrada: pl.LazyFrame, passos: list[dict], roteiro: list[Any], detectados: list[dict] = ()
) -> list[Linha]:
    """Segue o roteiro a partir de ``passos``. Uma sugestão vista antes, em
    qualquer momento, também vale (a pessoa a tinha na tela), e os passos que
    a detecção propôs também. Passo que não muda a tabela não conta."""
    linhas: list[Linha] = []
    vistos: list[dict] = list(detectados)
    tabela = collect(_receita(passos), entrada)
    for modelo in roteiro:
        precisa = {k: (v(tabela.columns) if callable(v) else v) for k, v in modelo.items()}
        vistos += [p for s in suggest(tabela, steps=passos) if s.kind == "passo" for p in s.steps]
        depois = collect(_receita([*passos, precisa]), entrada)
        if depois.schema == tabela.schema and depois.equals(tabela):
            linhas.append((precisa["op"], -1.0, "não muda a tabela (não conta)"))
        else:
            tiradas = [c for c in tabela.columns if c not in depois.columns]
            frac, motivo = _cobertura({**precisa, "_tiradas": tiradas}, vistos)
            linhas.append((precisa["op"], frac, motivo))
        passos, tabela = [*passos, precisa], depois
    return linhas


def medir(arquivo: Arquivo, ws: Workspace) -> list[Linha]:
    caminho = next((BASE / arquivo.pasta).glob("original.*"))
    importado = import_file(caminho, sheet=arquivo.aba, workspace=ws)
    grade = pl.read_parquet(importado.path / RAW_FILE)
    deteccao = main_table(detect_tables(grade, importado.structure))
    passos = deteccao.to_steps() if deteccao else []
    linhas: list[Linha] = [(f"(detecção) {p['op']}", 1.0, "já vem na receita") for p in passos]
    return linhas + seguir_roteiro(pl.scan_parquet(importado.path / RAW_FILE), passos, arquivo.roteiro)


_ESTRUTURA = {"select_range", "header_rows"}
CORPUS = Path(__file__).resolve().parent.parent / "tests" / "corpus"


def _deteccao(receita: Any, original: Path) -> list[dict]:
    """O que a importação proporia (todas as tabelas da aba): totais a tirar
    e colunas a preencher para baixo também são sugestão."""
    if detect_format(original) == "csv":
        with open_csv_lazy(original, has_header=False) as lf:
            grade, estrutura = lf.collect(), None
    else:
        dados = read_sheet(original, receita.source.sheet)
        grade, estrutura = dados.frame, dados.structure
    return [p for t in detect_tables(grade, estrutura) for p in t.to_steps()]


def medir_corpus() -> list[tuple[str, list[Linha]]]:
    """No corpus de desenvolvimento: a receita esperada é o roteiro, a partir
    dos passos de recorte e cabeçalho."""
    saida = []
    for caminho in sorted(CORPUS.glob("[!_]*/receita_esperada*.wolfz.json")):
        originais = list(caminho.parent.glob("original.*"))
        if not originais:
            continue
        receita = load_recipe(caminho)
        passos = [s.model_dump(mode="json", exclude={"id"}, exclude_none=True) for s in receita.steps]
        k = 0
        while k < len(passos) and passos[k]["op"] in _ESTRUTURA:
            k += 1
        entrada = read_input(receita, originais[0]).lazy()
        sufixo = caminho.name.removeprefix("receita_esperada").removesuffix(".wolfz.json")
        detectados = _deteccao(receita, originais[0]) if k else []
        saida.append(
            (caminho.parent.name + sufixo, seguir_roteiro(entrada, passos[:k], passos[k:], detectados))
        )
    return saida


def _resumo(rotulo: str, linhas: list[Linha]) -> float:
    contam = [(op, f) for op, f, _ in linhas if f >= 0]
    soma = sum(f for _, f in contam)
    print(f"{rotulo}: {soma:.1f} de {len(contam)} passos = {soma / max(len(contam), 1):.0%}")
    sem_nome = [(op, f) for op, f in contam if op != "rename"]
    soma_sem = sum(f for _, f in sem_nome)
    print(
        f"  sem contar renomear: {soma_sem:.1f} de {len(sem_nome)} = {soma_sem / max(len(sem_nome), 1):.0%}"
    )
    return soma / max(len(contam), 1)


def _mostrar(nome: str, linhas: list[Linha]) -> None:
    print(f"\n{nome}")
    for op, frac, motivo in linhas:
        valor = "  -  " if frac < 0 else f"{frac:5.0%}"
        print(f"  {valor}  {op:<28} {motivo}")


def main() -> int:
    warnings.filterwarnings("ignore")
    todas: list[Linha] = []
    if "--corpus" in sys.argv:
        for nome, linhas in medir_corpus():
            _mostrar(nome, linhas)
            todas += linhas
        print()
        _resumo("Corpus, depois do recorte e do cabeçalho", todas)
        return 0
    if not BASE.is_dir():
        print(f"Sem os arquivos de validação em {BASE} (veja o README de lá).")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(Path(tmp))
        for arquivo in ARQUIVOS:
            linhas = medir(arquivo, ws)
            _mostrar(arquivo.pasta, linhas)
            todas += linhas
    print()
    _resumo("Com os passos da detecção", todas)
    _resumo("Só os passos depois da detecção", [x for x in todas if not x[0].startswith("(detecção)")])
    return 0


if __name__ == "__main__":
    sys.exit(main())

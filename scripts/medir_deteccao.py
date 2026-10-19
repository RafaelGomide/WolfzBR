"""Mede a detecção de estrutura no corpus (F1.C8).

Para cada arquivo do corpus, roda ``detect_structure`` e compara com o
``estrutura_esperada.json`` (a primeira tabela, quando há mais de uma):

- **área**: primeira e última linha de dados e primeira e última coluna;
- **cabeçalho**: linhas do cabeçalho (a v1 só acerta cabeçalho de uma linha);
- **totais**: linhas de total e subtotal;
- **fill_down**: colunas com mesclagem vertical;
- **tabelas**: ``detect_tables`` acha o mesmo número de tabelas da aba, com
  as mesmas áreas (F2.D3). Num arquivo de uma tabela só, pega o corte que não
  devia acontecer.

Rode a cada PR que mexer em ``wolfz/core/detect/`` e cole a tabela no PR::

    python scripts/medir_deteccao.py              # tabela em Markdown
    python scripts/medir_deteccao.py --validacao  # inclui o conjunto de validação

O conjunto de validação fica de fora por padrão: ele mede o critério do MVP
e não deve ser olhado enquanto se ajusta a heurística (F1.B5).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tests" / "test_corpus"))

from corpus_lib import Entrada, entradas  # noqa: E402

from wolfz.core.detect import detect_structure, detect_tables  # noqa: E402
from wolfz.core.ingest import detect_format, read_sheet  # noqa: E402
from wolfz.core.ingest.csv import open_csv_lazy  # noqa: E402

CRITERIOS = ("area", "cabecalho", "totais", "fill_down", "tabelas")
ROTULOS = {
    "area": "área",
    "cabecalho": "cabeçalho",
    "totais": "totais",
    "fill_down": "fill_down",
    "tabelas": "tabelas",
    "tudo": "tudo certo",
}


@dataclass
class Resultado:
    nome: str
    conjunto: str
    acertos: dict[str, bool] = field(default_factory=dict)
    detalhes: dict[str, str] = field(default_factory=dict)
    erro: str | None = None

    @property
    def tudo_certo(self) -> bool:
        return self.erro is None and all(self.acertos.values())


def _intervalo(par: list | None) -> str:
    if not par:
        return "nenhum"
    return str(par[0]) if par[0] == par[1] else f"{par[0]}-{par[1]}"


def medir_entrada(entrada: Entrada) -> Resultado | None:
    """``None`` se o original não foi baixado (arquivo externo)."""
    if entrada.original is None:
        return None
    esperado = json.loads((entrada.pasta / "estrutura_esperada.json").read_text(encoding="utf-8"))
    tabela = esperado["tabelas"][0]
    resultado = Resultado(entrada.nome, entrada.conjunto)
    try:
        if detect_format(entrada.original) == "csv":
            with open_csv_lazy(entrada.original, has_header=False) as lf:
                df, estrutura = lf.collect(), None
        else:
            dados = read_sheet(entrada.original, esperado["aba"])
            df, estrutura = dados.frame, dados.structure
        det = detect_structure(df, estrutura)
        tabelas = detect_tables(df, estrutura)
    except Exception as exc:  # um arquivo que quebra a detecção não derruba a medição
        resultado.erro = f"{type(exc).__name__}: {exc}"
        return resultado
    if det is None:
        resultado.erro = "nada detectado"
        return resultado

    obtido = det.to_dict()
    pares = {
        "area": (
            (obtido["dados"], obtido["colunas"]),
            (tabela["dados"], tabela["colunas"]),
            lambda v: f"{_intervalo(v[0])} {v[1][0]}:{v[1][1]}",
        ),
        "cabecalho": (obtido["cabecalho"], tabela["cabecalho"], _intervalo),
        "totais": (obtido["totais"], tabela["totais"], lambda v: ", ".join(map(str, v)) or "nenhum"),
        "fill_down": (obtido["fill_down"], tabela["fill_down"], lambda v: ", ".join(v) or "nenhum"),
        "tabelas": (
            [(t.to_dict()["dados"], t.to_dict()["colunas"]) for t in tabelas],
            [(t["dados"], t["colunas"]) for t in esperado["tabelas"]],
            lambda v: "; ".join(f"{_intervalo(d)} {c[0]}:{c[1]}" for d, c in v) or "nenhuma",
        ),
    }
    for criterio, (veio, devia, fmt) in pares.items():
        certo = veio == devia
        resultado.acertos[criterio] = certo
        if not certo:
            resultado.detalhes[criterio] = f"{fmt(veio)} (esperado {fmt(devia)})"
    return resultado


def medir(validacao: bool = False) -> list[Resultado]:
    return [r for e in entradas(validacao) if (r := medir_entrada(e)) is not None]


def resumo(resultados: list[Resultado]) -> dict[str, int]:
    contagem = {c: sum(r.acertos.get(c, False) for r in resultados) for c in CRITERIOS}
    contagem["tudo"] = sum(r.tudo_certo for r in resultados)
    contagem["arquivos"] = len(resultados)
    return contagem


def markdown(resultados: list[Resultado]) -> str:
    def marca(r: Resultado, c: str) -> str:
        if r.erro:
            return "erro"
        return "✓" if r.acertos[c] else f"✗ {r.detalhes[c]}"

    linhas = [
        "| Arquivo | Área | Cabeçalho | Totais | fill_down | Tabelas |",
        "|---|---|---|---|---|---|",
    ]
    for r in resultados:
        nome = r.nome if r.conjunto == "desenvolvimento" else f"{r.nome} (validação)"
        linhas.append(f"| {nome} | " + " | ".join(marca(r, c) for c in CRITERIOS) + " |")
    s = resumo(resultados)
    n = s["arquivos"] or 1
    linhas.append("")
    partes = [f"{rotulo} {s[c]} ({s[c] / n:.0%})" for c, rotulo in ROTULOS.items()]
    linhas.append(f"**{s['arquivos']} arquivos** · " + " · ".join(partes))
    erros = [r for r in resultados if r.erro]
    for r in erros:
        linhas.append(f"- `{r.nome}`: {r.erro}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--validacao", action="store_true", help="Inclui o conjunto de validação.")
    parser.add_argument("--json", action="store_true", help="Saída em JSON.")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # o console do Windows não é UTF-8
    resultados = medir(args.validacao)
    if args.json:
        dados = {
            "resumo": resumo(resultados),
            "arquivos": [
                {
                    "nome": r.nome,
                    "conjunto": r.conjunto,
                    "acertos": r.acertos,
                    "detalhes": r.detalhes,
                    "erro": r.erro,
                }
                for r in resultados
            ],
        }
        print(json.dumps(dados, indent=2))
    else:
        print(markdown(resultados))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Desenha ``docs/arquitetura.png``, o diagrama do README e do design (FH.D9).

Precisa do matplotlib, que não é dependência do projeto::

    uv run --no-project --with matplotlib python scripts/gerar_arquitetura.py

Mudou um módulo, uma entrada ou o workspace? Ajuste as listas abaixo e
rode de novo: a figura é gerada, nunca editada à mão.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

DESTINO = Path(__file__).resolve().parents[1] / "docs" / "arquitetura.png"

TEXTO, SUAVE = "#1f2933", "#52606d"
CORES = {
    "interface": ("#e8f0fb", "#3b7dc4"),
    "entrada": ("#e8f5ec", "#3f9a5b"),
    "nucleo": ("#fdf3e3", "#d08a2c"),
    "modulo": ("#ffffff", "#ddb87a"),
    "workspace": ("#eef0f3", "#7b8794"),
}

ENTRADAS = [
    ("API (FastAPI)", "projetos · receita · preview\nsugestões · exportação"),
    ("CLI (Typer)", "wolfz ui · run\ninspect · schema"),
    ("Python", "import wolfz\nrun · load_recipe · br"),
]
MODULOS = [
    ("ingest/", "leitura de arquivos,\nencoding, abas, limites"),
    ("detect/", "área da tabela,\ncabeçalho, totais"),
    ("profile/", "tipos, nulos, padrões,\ncardinalidade"),
    ("suggest/", "regras heurísticas\n→ passos sugeridos"),
    ("recipe/", "modelo da receita,\nvalidação, migração"),
    ("engine/", "execução (Polars lazy),\npreview com cache"),
    ("ops/", "catálogo: 40 operações,\ncada uma em Polars, M e Python"),
    ("br/", "parsers e validadores\nbrasileiros, municípios IBGE"),
    ("export/", "CSV, Excel, Parquet, M,\nPython, Hyper, PBIP"),
]


def caixa(ax, x, y, w, h, tipo, raio=0.012):
    fundo, borda = CORES[tipo]
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={raio}",
            facecolor=fundo,
            edgecolor=borda,
            linewidth=2 if tipo != "modulo" else 1.4,
        )
    )


def seta(ax, x, y0, y1):
    ax.add_patch(
        FancyArrowPatch((x, y0), (x, y1), arrowstyle="-|>", mutation_scale=18, linewidth=2, color=SUAVE)
    )


def main() -> None:
    fig = plt.figure(figsize=(14.4, 16.4), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(0.5, 0.965, "WolfzBR — Arquitetura", ha="center", fontsize=28, weight="bold", color=TEXTO)
    ax.text(0.5, 0.94, "100% local · nenhum dado sai da máquina", ha="center", fontsize=15, color=SUAVE)

    # Interface
    caixa(ax, 0.10, 0.83, 0.80, 0.085, "interface")
    ax.text(0.5, 0.888, "Interface (SPA local)", ha="center", fontsize=19, weight="bold", color=TEXTO)
    ax.text(
        0.5,
        0.85,
        "React + Glide Data Grid · grade antes/depois · receita · sugestões · exportar",
        ha="center",
        fontsize=13.5,
        color=SUAVE,
    )
    seta(ax, 0.235, 0.83, 0.765)
    ax.text(0.255, 0.795, "HTTP em 127.0.0.1 + token de sessão", fontsize=12.5, color=SUAVE)

    # Entradas: API, CLI e Python
    largura, gap = 0.25, 0.025
    for i, (titulo, texto) in enumerate(ENTRADAS):
        x = 0.10 + i * (largura + gap)
        caixa(ax, x, 0.68, largura, 0.085, "entrada")
        ax.text(x + largura / 2, 0.738, titulo, ha="center", fontsize=17, weight="bold", color=TEXTO)
        ax.text(x + largura / 2, 0.697, texto, ha="center", fontsize=12, color=SUAVE, linespacing=1.4)
        seta(ax, x + largura / 2, 0.68, 0.625)

    # Núcleo
    caixa(ax, 0.10, 0.215, 0.80, 0.41, "nucleo")
    ax.text(0.5, 0.592, "Núcleo", ha="center", fontsize=19, weight="bold", color=TEXTO)
    ax.text(
        0.5,
        0.567,
        "biblioteca Python pura, sem dependência da API nem da CLI",
        ha="center",
        fontsize=13,
        style="italic",
        color=SUAVE,
    )
    colunas, w, h = 3, 0.245, 0.085
    for i, (nome, texto) in enumerate(MODULOS):
        linha, coluna = divmod(i, colunas)
        x = 0.12 + coluna * (w + 0.0125)
        y = 0.455 - linha * (h + 0.014)
        caixa(ax, x, y, w, h, "modulo", raio=0.008)
        ax.text(x + 0.015, y + h - 0.028, nome, fontsize=15.5, weight="bold", family="monospace", color=TEXTO)
        ax.text(x + 0.015, y + 0.015, texto, fontsize=11.5, color=SUAVE, linespacing=1.35)
    seta(ax, 0.5, 0.215, 0.16)

    # Workspace
    caixa(ax, 0.10, 0.065, 0.80, 0.095, "workspace")
    ax.text(
        0.5,
        0.125,
        "~/.wolfz/  (workspace local)",
        ha="center",
        fontsize=19,
        weight="bold",
        family="monospace",
        color=TEXTO,
    )
    ax.text(
        0.5,
        0.083,
        "projetos · receitas (.wolfz.json) · grade crua em Parquet · cache por passo · exportações",
        ha="center",
        fontsize=13.5,
        color=SUAVE,
    )

    fig.savefig(DESTINO, dpi=100, facecolor="white")
    print(f"gravado: {DESTINO}")


if __name__ == "__main__":
    main()

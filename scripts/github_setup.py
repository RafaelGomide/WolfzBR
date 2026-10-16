"""Configura o repositório no GitHub: labels, milestones, issues da Fase 0
e o quadro do GitHub Projects (F0.I2–F0.I4).

Idempotente: o que já existe é mantido, só o que falta é criado. Precisa do
GitHub CLI autenticado com permissão de Projects:

    winget install GitHub.cli
    gh auth login
    gh auth refresh -s project

Uso:

    python scripts/github_setup.py --dry-run   # mostra o que faria
    python scripts/github_setup.py

A visualização em quadro (colunas pelo campo "Quadro") é configurada à mão
no Project: a API do GitHub não cria views.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

OWNER = "RafaelGomide"
REPO = f"{OWNER}/WolfzBR"
PROJECT_TITLE = "WolfzBR"
BOARD_FIELD = "Quadro"
BOARD_OPTIONS = ["Backlog", "Semana", "Em andamento", "Em revisão", "Feito"]

AREA = "c5def5"
LABELS = {
    "tipo:bug": ("d73a4a", "Algo não funciona como deveria"),
    "tipo:feature": ("a2eeef", "Funcionalidade ou operação nova"),
    "tipo:docs": ("0075ca", "Documentação"),
    "area:ingest": (AREA, "Leitura de arquivos"),
    "area:detect": (AREA, "Detecção de estrutura"),
    "area:ops": (AREA, "Catálogo de operações"),
    "area:br": (AREA, "Parsers e validadores brasileiros"),
    "area:export": (AREA, "Exportação (M, Python, Tableau, Power BI)"),
    "area:api": (AREA, "API local"),
    "area:ui": (AREA, "Interface"),
    "area:cli": (AREA, "Linha de comando"),
    "prioridade:alta": ("b60205", "Fazer antes do resto"),
    "bom-primeiro-issue": ("7057ff", "Bom para quem está começando no projeto"),
}

# Tabela §2.3 do planejamento.
MILESTONES = {
    "v0.1.0": "Fase 0: receita + 3 operações + wolfz run. Tag e GitHub Release.",
    "v0.2.0": "Fase 1: ingestão completa + profiling + CLI inspect. TestPyPI.",
    "v0.3.0": "Fase 1: detecção v1 + ~25 operações. TestPyPI.",
    "v0.4.0": "Fase 1 — MVP: interface + export CSV/Parquet/Excel. Primeira publicação no PyPI.",
    "v0.5.0": "Fase 2: export Power Query M + script Python.",
    "v0.6.0": "Fase 2: pacote BR completo + cabeçalho multinível.",
    "v0.7.0": "Fase 2: sugestões automáticas + assert.",
    "v0.8.0": "Fase 3: .hyper + .tds.",
    "v0.9.0": "Fase 3: PBIP.",
    "v1.0.0rc1": "Congelamento de funcionalidades. PyPI (pré-release).",
    "v1.0.0": "Lançamento. PyPI + GitHub Release.",
}

# O que falta da Fase 0. As tarefas já feitas estão no histórico de commits.
ISSUES = [
    {
        "title": "Receita e CSV de exemplo para o teste de ponta a ponta [F0]",
        "labels": ["tipo:feature", "area:cli"],
        "milestone": "v0.1.0",
        "body": (
            "Critério de pronto da Fase 0:\n\n"
            "`uv run wolfz run exemplo.wolfz.json tests/corpus/minimo.csv -o saida/` funciona.\n\n"
            "- [ ] `exemplo.wolfz.json` usando as 3 operações\n"
            "- [ ] `tests/corpus/minimo.csv` com dados inventados\n"
            "- [ ] Teste que roda o comando acima"
        ),
    },
    {
        "title": "Confirmar CI verde nas 4 combinações da matriz [F0]",
        "labels": ["prioridade:alta"],
        "milestone": "v0.1.0",
        "body": "ubuntu-latest e windows-latest com Python 3.12 e 3.13, no push do `main`.",
    },
    {
        "title": "Release v0.1.0: tag + GitHub Release com notas [F0]",
        "labels": ["tipo:docs"],
        "milestone": "v0.1.0",
        "body": (
            "- [ ] Mover a seção *Não publicado* do `CHANGELOG.md` para `0.1.0`\n"
            '- [ ] `version = "0.1.0"` no `pyproject.toml`\n'
            "- [ ] Tag `v0.1.0` e GitHub Release com as notas do changelog"
        ),
    },
    {
        "title": "Branch protection no main [F0.D4]",
        "labels": [],
        "milestone": "v0.4.0",
        "body": (
            "Cortado enquanto o repositório for privado (o plano gratuito não aplica a regra). "
            "Retomar ao tornar o repositório público (F1.K5): PR obrigatório sem aprovação mínima, "
            "as 4 verificações do CI obrigatórias e bypass de admin permitido."
        ),
    },
]


class GitHub:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def read(self, *args: str) -> object:
        out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8")
        return json.loads(out.stdout) if out.stdout.strip() else None

    def write(self, *args: str) -> str:
        print("  gh " + " ".join(args))
        if self.dry_run:
            return ""
        out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8")
        return out.stdout


def setup_labels(gh: GitHub) -> None:
    print("Labels")
    existing = {
        label["name"] for label in gh.read("label", "list", "-R", REPO, "--limit", "200", "--json", "name")
    }
    for name, (color, description) in LABELS.items():
        if name not in existing:
            gh.write("label", "create", name, "-R", REPO, "--color", color, "--description", description)


def setup_milestones(gh: GitHub) -> None:
    print("Milestones")
    existing = {m["title"] for m in gh.read("api", f"repos/{REPO}/milestones?state=all&per_page=100")}
    for title, description in MILESTONES.items():
        if title not in existing:
            gh.write(
                "api",
                "-X",
                "POST",
                f"repos/{REPO}/milestones",
                "-f",
                f"title={title}",
                "-f",
                f"description={description}",
            )


def setup_issues(gh: GitHub) -> list[str]:
    """Cria as issues que faltam e devolve as URLs de todas as da lista."""
    print("Issues")
    existing = {
        issue["title"]: issue["url"]
        for issue in gh.read(
            "issue", "list", "-R", REPO, "--state", "all", "--limit", "500", "--json", "title,url"
        )
    }
    urls = []
    for issue in ISSUES:
        if issue["title"] in existing:
            urls.append(existing[issue["title"]])
            continue
        args = ["issue", "create", "-R", REPO, "--title", issue["title"], "--body", issue["body"]]
        args += ["--milestone", issue["milestone"]]
        for label in issue["labels"]:
            args += ["--label", label]
        urls.append(gh.write(*args).strip())
    return urls


def setup_project(gh: GitHub, issue_urls: list[str]) -> None:
    print("Project")
    projects = gh.read("project", "list", "--owner", OWNER, "--format", "json", "--limit", "100")["projects"]
    project = next((p for p in projects if p["title"] == PROJECT_TITLE), None)
    if project is None:
        if gh.dry_run:
            gh.write("project", "create", "--owner", OWNER, "--title", PROJECT_TITLE)
            print(
                f"  (+ campo {BOARD_FIELD!r} com {BOARD_OPTIONS}, vínculo ao repositório e issues no Backlog)"
            )
            return
        project = json.loads(
            gh.write("project", "create", "--owner", OWNER, "--title", PROJECT_TITLE, "--format", "json")
        )
        gh.write("project", "link", str(project["number"]), "--owner", OWNER, "--repo", REPO)
    number = str(project["number"])

    fields = gh.read("project", "field-list", number, "--owner", OWNER, "--format", "json")["fields"]
    board = next((f for f in fields if f["name"] == BOARD_FIELD), None)
    if board is None:
        gh.write(
            "project",
            "field-create",
            number,
            "--owner",
            OWNER,
            "--name",
            BOARD_FIELD,
            "--data-type",
            "SINGLE_SELECT",
            "--single-select-options",
            ",".join(BOARD_OPTIONS),
        )
        if gh.dry_run:
            return
        fields = gh.read("project", "field-list", number, "--owner", OWNER, "--format", "json")["fields"]
        board = next(f for f in fields if f["name"] == BOARD_FIELD)
    backlog = next(o["id"] for o in board["options"] if o["name"] == "Backlog")

    items = gh.read("project", "item-list", number, "--owner", OWNER, "--format", "json", "--limit", "500")
    in_project = {item.get("content", {}).get("url") for item in items["items"]}
    for url in issue_urls:
        if not url or url in in_project:
            continue
        added = gh.write("project", "item-add", number, "--owner", OWNER, "--url", url, "--format", "json")
        if added:
            gh.write(
                "project",
                "item-edit",
                "--id",
                json.loads(added)["id"],
                "--project-id",
                project["id"],
                "--field-id",
                board["id"],
                "--single-select-option-id",
                backlog,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="mostra os comandos sem executar")
    args = parser.parse_args()
    if shutil.which("gh") is None:
        print("GitHub CLI não encontrado. Instale com: winget install GitHub.cli", file=sys.stderr)
        return 1
    gh = GitHub(dry_run=args.dry_run)
    setup_labels(gh)
    setup_milestones(gh)
    setup_project(gh, setup_issues(gh))
    print("\nFalta só uma coisa à mão: no Project, crie a view 'Board' agrupada pelo campo 'Quadro'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

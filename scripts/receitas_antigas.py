"""Guarda receitas reais de uma versão publicada do WolfzBR (F2.G1).

Para cada tag, ``tests/receitas_antigas/<tag>/`` recebe receitas gravadas
pelo código daquela versão (``save_recipe`` dela, byte a byte) e a tabela
que o motor dela produziu. O teste ``tests/test_recipe/test_receitas_antigas.py``
abre cada uma com o WolfzBR atual — passando pela migração quando o formato
tiver mudado — e confere que o resultado é o mesmo.

As receitas vêm do corpus que existia na tag; das que rodam sobre um
arquivo versionado no Git, entram as que cobrem todas as operações usadas
nele (o exemplo da raiz entra sempre). Junto vai ``catalogo.wolfz.json``, uma
receita com um passo por exemplo de cada operação que a versão tinha: não
roda, mas garante que os parâmetros de todas continuam sendo lidos. Rode a
cada release, depois de criar a tag::

    uv run python scripts/receitas_antigas.py v0.7.0

O código antigo roda num ``git worktree`` temporário, com as dependências do
ambiente atual. Os arquivos gerados nunca são editados à mão: se um teste
quebrar, ou o WolfzBR atual mudou o resultado sem querer, ou a mudança foi
de propósito e precisa de uma migração.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "tests" / "receitas_antigas"

# Roda dentro do worktree da tag, com o ``src`` dela na frente do sys.path.
_FILHO = r"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
import wolfz
from wolfz.core.engine import run_file
from wolfz.core.recipe import dumps_recipe, load_recipe

assert Path(wolfz.__file__).resolve().is_relative_to(Path("src").resolve()), wolfz.__file__
saida = Path(sys.argv[1])
resultado = {}
for item in json.loads(sys.argv[2]):
    try:
        receita = load_recipe(item["receita"])
        df = run_file(receita, item["entrada"])
    except Exception as exc:
        resultado[item["nome"]] = {"erro": f"{type(exc).__name__}: {exc}"}
        continue
    (saida / f"{item['nome']}.wolfz.json").write_text(dumps_recipe(receita), encoding="utf-8")
    df.write_parquet(saida / f"{item['nome']}.parquet")
    resultado[item["nome"]] = {"ops": sorted({s.op for s in receita.steps})}

# Catálogo: um passo por exemplo de cada operação da versão. Não roda (cada
# exemplo tem a sua entrada); serve para conferir que os parâmetros de toda
# operação continuam sendo lidos.
from datetime import UTC, datetime
import wolfz.ops
from wolfz.core.recipe import CURRENT_VERSION, Recipe, Source, registered_ops

passos = []
for nome, cls in sorted(registered_ops().items()):
    if not cls.__module__.startswith("wolfz."):
        continue
    for exemplo in cls.examples:
        dados = {"id": f"s{len(passos) + 1}", "op": nome, **exemplo["step"]}
        passos.append(cls.model_validate(dados))
catalogo = Recipe(
    wolfz_version=CURRENT_VERSION,
    name="catálogo",
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
    source=Source(type="csv"),
    steps=passos,
)
(saida / "catalogo.wolfz.json").write_text(dumps_recipe(catalogo), encoding="utf-8")
resultado["catalogo"] = {"ops": sorted({s.op for s in passos})}
print(json.dumps(resultado))
"""


def _git(*args: str, cwd: Path = RAIZ) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _candidatas(arvore: Path, arquivos: set[str]) -> list[dict[str, str]]:
    """Receitas da tag que rodam sobre um arquivo versionado no Git."""
    itens = []
    if "exemplo.wolfz.json" in arquivos and "tests/corpus/minimo.csv" in arquivos:
        itens.append(
            {"nome": "exemplo", "receita": "exemplo.wolfz.json", "entrada": "tests/corpus/minimo.csv"}
        )
    for receita in sorted(arquivos):
        partes = receita.split("/")
        if len(partes) != 4 or partes[:2] != ["tests", "corpus"] or partes[2].startswith("_"):
            continue
        if not (partes[3].startswith("receita_esperada") and partes[3].endswith(".wolfz.json")):
            continue
        pasta = "/".join(partes[:3])
        entradas = [a for a in arquivos if a.startswith(f"{pasta}/original.")]
        if len(entradas) != 1:
            continue  # original grande demais para o Git (externo.json)
        sufixo = partes[3].removeprefix("receita_esperada").removesuffix(".wolfz.json")
        itens.append({"nome": partes[2] + sufixo, "receita": receita, "entrada": entradas[0]})
    assert all((arvore / i["receita"]).is_file() for i in itens)
    return itens


def _cobertura(ops: dict[str, list[str]]) -> list[str]:
    """Poucas receitas que juntas usam todas as operações (guloso)."""
    faltam = set().union(*ops.values()) if ops else set()
    escolhidas = ["exemplo"] if "exemplo" in ops else []
    for nome in escolhidas:
        faltam -= set(ops[nome])
    while faltam:
        nome = max(sorted(ops), key=lambda n: len(faltam & set(ops[n])))
        escolhidas.append(nome)
        faltam -= set(ops[nome])
    return sorted(escolhidas)


def guardar(tag: str) -> Path:
    destino = DESTINO / tag
    with tempfile.TemporaryDirectory(prefix="wolfz-receitas-") as tmp:
        arvore = Path(tmp) / "arvore"
        bruto = Path(tmp) / "bruto"
        bruto.mkdir()
        _git("worktree", "add", "--detach", str(arvore), tag)
        try:
            arquivos = set(_git("ls-tree", "-r", "--name-only", tag).splitlines())
            itens = _candidatas(arvore, arquivos)
            filho = subprocess.run(
                [sys.executable, "-c", _FILHO, str(bruto), json.dumps(itens)],
                cwd=arvore,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            resultado = json.loads(filho.stdout.strip().splitlines()[-1])
        finally:
            _git("worktree", "remove", "--force", str(arvore))

        erros = {n: r["erro"] for n, r in resultado.items() if "erro" in r}
        for nome, erro in erros.items():
            print(f"  {nome}: não rodou na {tag} ({erro}); fica de fora")
        catalogo = resultado.pop("catalogo")["ops"]
        ops = {n: r["ops"] for n, r in resultado.items() if "erro" not in r}
        escolhidas = _cobertura(ops)

        if destino.exists():
            shutil.rmtree(destino)
        destino.mkdir(parents=True)
        shutil.copyfile(bruto / "catalogo.wolfz.json", destino / "catalogo.wolfz.json")
        entradas = {}
        for item in itens:
            if item["nome"] not in escolhidas:
                continue
            for ext in (".wolfz.json", ".parquet"):
                shutil.copyfile(bruto / f"{item['nome']}{ext}", destino / f"{item['nome']}{ext}")
            # O teste lê a entrada do corpus atual; se ela mudou desde a tag,
            # vai uma cópia da antiga junto.
            atual = RAIZ / item["entrada"]
            igual = (
                subprocess.run(
                    ["git", "diff", "--quiet", tag, "--", item["entrada"]], cwd=RAIZ, check=False
                ).returncode
                == 0
            )
            if atual.is_file() and igual:
                entradas[item["nome"]] = item["entrada"]
            else:
                copia = f"{item['nome']}.entrada{Path(item['entrada']).suffix}"
                (destino / copia).write_bytes(
                    subprocess.run(
                        ["git", "show", f"{tag}:{item['entrada']}"],
                        cwd=RAIZ,
                        check=True,
                        capture_output=True,
                    ).stdout
                )
                entradas[item["nome"]] = f"{tag}/{copia}"
        todas = sorted(set().union(*ops.values())) if ops else []
        manifesto = {"tag": tag, "operacoes": todas, "entradas": entradas, "catalogo": catalogo}
        (destino / "manifesto.json").write_text(
            json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        f"{tag}: {len(escolhidas)} receita(s) do corpus com {len(todas)} operação(ões);"
        f" catálogo com {len(catalogo)} -> {destino}"
    )
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tags", nargs="+", help="tags publicadas, ex.: v0.6.0")
    for tag in parser.parse_args().tags:
        guardar(tag)


if __name__ == "__main__":
    main()

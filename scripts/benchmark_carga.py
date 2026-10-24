"""Teste de carga (FH.B): arquivos de 10, 50 e 100 MB pela API de verdade.

Gera, para cada tamanho, um CSV (``;``, cp1252, vírgula decimal) e um
``.xlsx`` com o jeito de exportação de sistema brasileiro: data
``dd/mm/aaaa``, competência, CNPJ e CPF com máscara, município e UF, CEP,
``R$ 1.234,56`` e doze colunas de valor mensal. Os dados são inventados e
determinísticos (mesma semente, mesmo arquivo). Depois mede cada arquivo
num processo próprio, para a memória de pico ser só dele:

- **importação + detecção**: o ``POST /api/projects`` inteiro (upload,
  leitura, ``raw.parquet``, estrutura e receita inicial);
- **memória de pico** do processo (orçamento de 2 GB para 100 MB, §3.5);
- **preview depois de editar o último passo**: ``PUT`` da receita com um
  filtro novo no fim + ``GET`` da primeira página, p50 e p95 (SLO do §12.4:
  p50 ≤ 300 ms, p95 ≤ 1 s);
- **acima do limite** (FH.B4): um CSV de 110 MB tem de voltar ``413`` com a
  mensagem, rápido e sem gastar memória.

Uso::

    uv run python scripts/benchmark_carga.py              # gera o que falta e mede tudo
    uv run python scripts/benchmark_carga.py --tamanhos 10 --formatos csv
    uv run python scripts/benchmark_carga.py --json dev/carga.json

Os arquivos ficam em ``dev/dados_carga/`` (fora do Git). Sai com código 1
se algum caso passar do SLO, do orçamento de memória ou não der ``413``.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "dev" / "dados_carga"
MB = 1024 * 1024
TAMANHOS = (10, 50, 100)
ACIMA_DO_LIMITE = 110
SLO_P50, SLO_P95 = 0.300, 1.0
ORCAMENTO_MEMORIA = 2048 * MB
MAX_LINHAS_XLSX = 1_048_575  # 1.048.576 do Excel menos o cabeçalho

MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
CABECALHO = [
    "Data de emissão",
    "Competência",
    "CNPJ do fornecedor",
    "Razão social",
    "CPF do responsável",
    "Município",
    "UF",
    "CEP",
    "Pago",
    "Descrição",
    "Quantidade",
    "Valor total",
    *(f"Valor {m}" for m in MESES),
]
MUNICIPIOS = [
    ("Vitória", "ES"),
    ("Vila Velha", "ES"),
    ("Serra", "ES"),
    ("Cariacica", "ES"),
    ("São Paulo", "SP"),
    ("Campinas", "SP"),
    ("Rio de Janeiro", "RJ"),
    ("Niterói", "RJ"),
    ("Belo Horizonte", "MG"),
    ("Uberlândia", "MG"),
    ("Salvador", "BA"),
    ("Feira de Santana", "BA"),
    ("Curitiba", "PR"),
    ("Londrina", "PR"),
    ("Porto Alegre", "RS"),
    ("Goiânia", "GO"),
    ("Recife", "PE"),
    ("Fortaleza", "CE"),
    ("Belém", "PA"),
    ("Manaus", "AM"),
]
PALAVRAS = ["material", "serviço", "manutenção", "locação", "consultoria", "insumo", "obra", "licença"]


# ---------------------------------------------------------------------------
# Geração (FH.B1)
# ---------------------------------------------------------------------------


def _dv(digitos: str, pesos: range | list[int]) -> str:
    resto = sum(int(d) * p for d, p in zip(digitos, pesos, strict=False)) % 11
    return "0" if resto < 2 else str(11 - resto)


def _cpf(rng: random.Random) -> str:
    base = "".join(str(rng.randint(0, 9)) for _ in range(9))
    base += _dv(base, range(10, 1, -1))
    base += _dv(base, range(11, 1, -1))
    return f"{base[:3]}.{base[3:6]}.{base[6:9]}-{base[9:]}"


def _cnpj(rng: random.Random) -> str:
    base = "".join(str(rng.randint(0, 9)) for _ in range(8)) + "0001"
    base += _dv(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    base += _dv(base, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return f"{base[:2]}.{base[2:5]}.{base[5:8]}/{base[8:12]}-{base[12:]}"


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Linhas:
    """Linhas determinísticas; ``xlsx`` deixa os valores mensais como número."""

    def __init__(self, semente: int = 0):
        self.rng = random.Random(semente)
        self.fornecedores = [(_cnpj(self.rng), f"Fornecedor {i} Ltda") for i in range(5000)]
        self.cpfs = [_cpf(self.rng) for _ in range(20000)]

    def linha(self, numerico: bool) -> list[str | float | int]:
        r = self.rng
        cnpj, razao = r.choice(self.fornecedores)
        municipio, uf = r.choice(MUNICIPIOS)
        mensais = [round(r.uniform(0, 50_000), 2) for _ in MESES]
        return [
            f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/{r.randint(2015, 2025)}",
            f"{r.randint(1, 12):02d}/{r.randint(2015, 2025)}",
            cnpj,
            razao,
            r.choice(self.cpfs),
            municipio,
            uf,
            f"{r.randint(10000, 99999)}-{r.randint(0, 999):03d}",
            r.choice(("Sim", "Não")),
            f"Item {r.randint(1, 99999)} - {r.choice(PALAVRAS)}",
            r.randint(1, 500),
            "R$ " + _brl(sum(mensais)),
            *(mensais if numerico else [_brl(v) for v in mensais]),
        ]


def gerar_csv(destino: Path, alvo: int, semente: int = 0) -> None:
    linhas = Linhas(semente)
    tmp = destino.with_suffix(".tmp")
    with tmp.open("w", encoding="cp1252", newline="") as f:
        f.write(";".join(CABECALHO) + "\r\n")
        while True:  # para antes de passar do alvo: o de 100 MB tem de caber no limite
            texto = ";".join(str(v) for v in linhas.linha(numerico=False)) + "\r\n"
            if f.tell() + len(texto.encode("cp1252")) > alvo:
                break
            f.write(texto)
    tmp.replace(destino)


def _coluna(i: int) -> str:
    nome = ""
    i += 1
    while i:
        i, resto = divmod(i - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


_COLUNAS = [_coluna(i) for i in range(len(CABECALHO))]


def _linha_xml(n: int, valores: list) -> str:
    celulas = []
    for col, v in zip(_COLUNAS, valores, strict=True):
        if isinstance(v, int | float):
            celulas.append(f'<c r="{col}{n}"><v>{v}</v></c>')
        else:
            celulas.append(f'<c r="{col}{n}" t="inlineStr"><is><t>{escape(v)}</t></is></c>')
    return f'<row r="{n}">{"".join(celulas)}</row>'


_FIXOS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    ),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Lançamentos" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    ),
}


def _escrever_xlsx(destino: Path, linhas: Linhas, n: int) -> None:
    ultima = f"{_COLUNAS[-1]}{n + 1}"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for nome, conteudo in _FIXOS.items():
            zf.writestr(nome, conteudo)
        with zf.open("xl/worksheets/sheet1.xml", "w", force_zip64=True) as f:
            f.write(
                (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f'<dimension ref="A1:{ultima}"/><sheetData>' + _linha_xml(1, CABECALHO)
                ).encode()
            )
            bloco = []
            for i in range(2, n + 2):
                bloco.append(_linha_xml(i, linhas.linha(numerico=True)))
                if len(bloco) == 2000:
                    f.write("".join(bloco).encode())
                    bloco = []
            f.write(("".join(bloco) + "</sheetData></worksheet>").encode())


def gerar_xlsx(destino: Path, alvo: int, semente: int = 0) -> None:
    """XML escrito à mão, com texto inline (o Excel usaria a tabela de
    textos compartilhados; o calamine lê os dois). O número de linhas sai
    de uma amostra comprimida, para o arquivo ficar perto do alvo."""
    with tempfile.TemporaryDirectory() as t:
        amostra = Path(t) / "amostra.xlsx"
        _escrever_xlsx(amostra, Linhas(semente + 1), 20_000)
        por_linha = amostra.stat().st_size / 20_000
    n = int(alvo * 0.985 / por_linha)  # a estimativa erra ~1%: fica abaixo do alvo
    if n > MAX_LINHAS_XLSX:
        raise SystemExit(f"{destino.name}: {n} linhas não cabem numa aba do Excel")
    tmp = destino.with_suffix(".tmp")
    _escrever_xlsx(tmp, Linhas(semente), n)
    tmp.replace(destino)


def arquivo(tamanho_mb: int, formato: str, pasta: Path = PASTA) -> Path:
    """Caminho do arquivo sintético, gerado se ainda não existe."""
    destino = pasta / f"carga_{tamanho_mb}mb.{formato}"
    if not destino.exists():
        pasta.mkdir(parents=True, exist_ok=True)
        inicio = time.perf_counter()
        (gerar_csv if formato == "csv" else gerar_xlsx)(destino, tamanho_mb * MB)
        tempo = time.perf_counter() - inicio
        print(f"gerado {destino.name}: {destino.stat().st_size / MB:.1f} MB em {tempo:.0f} s", flush=True)
    return destino


# ---------------------------------------------------------------------------
# Medição (FH.B2 e FH.B4), um arquivo por processo
# ---------------------------------------------------------------------------


def memoria_de_pico() -> int:
    """Pico de memória residente deste processo, em bytes."""
    if sys.platform == "win32":

        class Contadores(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32")
        # Sem os tipos, o handle de 64 bits é cortado e a chamada falha calada.
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_int
        c = Contadores()
        c.cb = ctypes.sizeof(c)
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise OSError("GetProcessMemoryInfo falhou")
        return int(c.PeakWorkingSetSize)
    import resource

    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return pico if sys.platform == "darwin" else pico * 1024


def _percentil(amostra: list[float], p: float) -> float:
    ordenada = sorted(amostra)
    return ordenada[min(len(ordenada) - 1, round(p * (len(ordenada) - 1)))]


def _cliente(pasta: Path):
    from fastapi.testclient import TestClient

    from wolfz.api.app import create_app
    from wolfz.api.security import Settings
    from wolfz.core.workspace import Workspace

    settings = Settings(workspace=Workspace(pasta / "home"), port=8765, token="carga")
    return TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer carga"},
    )


def _filtro(i: int, coluna: str) -> dict:
    if i % 2:
        return {"op": "filter", "col": coluna, "match": "not_null"}
    return {"op": "filter", "col": coluna, "match": "contains", "value": str(i % 10), "ignore_case": True}


def medir_um(caminho: Path, repeticoes: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="wolfz-carga-") as t, _cliente(Path(t)) as c:
        inicio = time.perf_counter()
        with caminho.open("rb") as f:
            r = c.post("/api/projects", files={"file": (caminho.name, f, "application/octet-stream")})
        importacao = time.perf_counter() - inicio
        if r.status_code != 201:
            return {"erro": f"{r.status_code}: {r.text[:300]}"}
        projeto = r.json()
        pid, etag, receita = projeto["id"], projeto["etag"], projeto["recipe"]

        inicio = time.perf_counter()
        pagina = c.get(f"/api/projects/{pid}/preview").json()
        abertura = time.perf_counter() - inicio
        coluna = pagina["columns"][-1]["name"] if isinstance(pagina["columns"][-1], dict) else None
        coluna = coluna or pagina["columns"][-1]

        passos = receita["steps"]
        edicoes = []
        for i in range(repeticoes):
            nova = {**receita, "steps": [*passos, {"id": f"s{len(passos) + 1}", **_filtro(i, coluna)}]}
            inicio = time.perf_counter()
            salvo = c.put(f"/api/projects/{pid}/recipe", json=nova, headers={"If-Match": etag})
            assert salvo.status_code == 200, salvo.text
            etag = salvo.json()["etag"]
            assert c.get(f"/api/projects/{pid}/preview").status_code == 200
            edicoes.append(time.perf_counter() - inicio)

    return {
        "arquivo": caminho.name,
        "mb": round(caminho.stat().st_size / MB, 1),
        "linhas": projeto["raw"]["rows"],
        "colunas": len(projeto["raw"]["columns"]),
        "passos_detectados": len(passos),
        "importacao_s": round(importacao, 2),
        "primeiro_preview_ms": round(abertura * 1000),
        "edicao_p50_ms": round(statistics.median(edicoes) * 1000),
        "edicao_p95_ms": round(_percentil(edicoes, 0.95) * 1000),
        "memoria_pico_mb": round(memoria_de_pico() / MB),
    }


def medir_acima_do_limite(pasta: Path) -> dict:
    """FH.B4: arquivo maior que o limite volta 413, sem ler o conteúdo."""
    caminho = pasta / f"carga_{ACIMA_DO_LIMITE}mb.csv"
    if not caminho.exists():
        pasta.mkdir(parents=True, exist_ok=True)
        with caminho.open("wb") as f:  # o conteúdo não importa: tem de ser recusado antes
            f.write(b"a;b\r\n" * (ACIMA_DO_LIMITE * MB // 5))
    with tempfile.TemporaryDirectory(prefix="wolfz-carga-") as t, _cliente(Path(t)) as c:
        inicio = time.perf_counter()
        with caminho.open("rb") as f:
            r = c.post("/api/projects", files={"file": (caminho.name, f, "text/csv")})
        tempo = time.perf_counter() - inicio
        corpo = r.json()
    return {
        "arquivo": caminho.name,
        "mb": round(caminho.stat().st_size / MB, 1),
        "status": r.status_code,
        "detail": corpo.get("detail"),
        "tempo_s": round(tempo, 2),
        "memoria_pico_mb": round(memoria_de_pico() / MB),
    }


def _em_processo(args: list[str]) -> dict:
    saida = subprocess.run(
        [sys.executable, __file__, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if saida.returncode != 0:
        return {"erro": saida.stderr.strip().splitlines()[-1] if saida.stderr.strip() else "falhou"}
    return json.loads(saida.stdout.strip().splitlines()[-1])


def _maquina() -> dict:
    import polars as pl

    memoria = None
    if sys.platform == "win32":

        class Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                *((n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")),
            ]

        s = Status()
        s.dwLength = ctypes.sizeof(s)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        memoria = s.ullTotalPhys
    elif hasattr(os, "sysconf"):
        memoria = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return {
        "sistema": f"{platform.system()} {platform.release()}",
        "processador": platform.processor() or platform.machine(),
        "nucleos": os.cpu_count(),
        "memoria_gb": round(memoria / 1024**3, 1) if memoria else None,
        "python": platform.python_version(),
        "polars": pl.__version__,
    }


def _problemas(r: dict) -> list[str]:
    if "erro" in r:
        return [r["erro"]]
    saida = []
    if r["edicao_p50_ms"] > SLO_P50 * 1000 or r["edicao_p95_ms"] > SLO_P95 * 1000:
        saida.append("preview fora do SLO")
    if r["memoria_pico_mb"] * MB > ORCAMENTO_MEMORIA:
        saida.append("memória acima de 2 GB")
    return saida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tamanhos", type=int, nargs="+", default=list(TAMANHOS), help="Em MB.")
    parser.add_argument("--formatos", nargs="+", default=["csv", "xlsx"], choices=["csv", "xlsx"])
    parser.add_argument("--repeticoes", type=int, default=20, help="Edições medidas por arquivo.")
    parser.add_argument("--pasta", type=Path, default=PASTA)
    parser.add_argument("--json", type=Path, help="Grava o relatório neste arquivo.")
    parser.add_argument("--so-gerar", action="store_true", help="Só gera os arquivos.")
    parser.add_argument("--_um", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_acima", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args._um:
        print(json.dumps(medir_um(args._um, args.repeticoes)))
        return 0
    if args._acima:
        print(json.dumps(medir_acima_do_limite(args.pasta)))
        return 0

    arquivos = [arquivo(t, f, args.pasta) for t in args.tamanhos for f in args.formatos]
    if args.so_gerar:
        return 0

    maquina = _maquina()
    print(
        f"{maquina['sistema']} · {maquina['processador']} · {maquina['nucleos']} núcleos · "
        f"{maquina['memoria_gb']} GB · Python {maquina['python']} · Polars {maquina['polars']}"
    )
    resultados, falhas = [], 0
    for caminho in arquivos:
        r = _em_processo(["--_um", str(caminho), "--repeticoes", str(args.repeticoes)])
        r.setdefault("arquivo", caminho.name)
        resultados.append(r)
        problemas = _problemas(r)
        falhas += bool(problemas)
        if "erro" in r:
            print(f"{caminho.name}: ERRO {r['erro']}", flush=True)
            continue
        print(
            f"{r['arquivo']} ({r['mb']} MB, {r['linhas']:,} linhas): importação {r['importacao_s']} s · "
            f"memória {r['memoria_pico_mb']} MB · 1º preview {r['primeiro_preview_ms']} ms · "
            f"edição p50 {r['edicao_p50_ms']} ms, p95 {r['edicao_p95_ms']} ms"
            + (f" · {', '.join(problemas)}" if problemas else ""),
            flush=True,
        )

    acima = _em_processo(["--_acima", "--pasta", str(args.pasta)])
    ok_acima = acima.get("status") == 413
    falhas += not ok_acima
    print(
        f"{acima.get('arquivo')}: {acima.get('status')} em {acima.get('tempo_s')} s, "
        f"memória {acima.get('memoria_pico_mb')} MB — {acima.get('detail') or acima.get('erro')}"
    )

    if args.json:
        relatorio = {"maquina": maquina, "arquivos": resultados, "acima_do_limite": acima}
        args.json.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

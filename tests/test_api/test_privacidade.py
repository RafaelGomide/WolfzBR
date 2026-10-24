"""Privacidade (FH.C2 e FH.C3, §11.7 e §12.1 do design).

Um fluxo completo, da importação à exportação em todos os formatos, sobre
um CSV sintético em que todo valor de célula tem a marca ``QXZ``:

- **sem rede**: qualquer conexão de socket fora do loopback falha e fica
  registrada; o fluxo tem de terminar sem nenhuma;
- **sem dado no log**: nenhum registro de log, em nenhum nível, traz a
  marca ou o CPF, nem quando uma regra de sugestão ou uma rota falham com o
  valor na mensagem;
- **sem token no disco**: o token da sessão não vai para o workspace.

E uma varredura estática: o pacote não importa cliente de rede e a
interface não carrega fonte nem script de fora.
"""

import ast
import ipaddress
import re
import socket
from pathlib import Path

import pytest
from apoio_api import PORTA, cliente
from typer.testing import CliRunner

from wolfz.api.security import Settings
from wolfz.cli import app as cli
from wolfz.core.workspace import Workspace
from wolfz.export.tableau import hyper_disponivel

RAIZ = Path(__file__).resolve().parents[2]
MARCA = "QXZ"
CPF = "529.982.247-25"
TOKEN = "token-QXZ-de-teste-que-nao-pode-ir-para-o-disco"


# ---------------------------------------------------------------------------
# Rede desligada
# ---------------------------------------------------------------------------


def _loopback(host: object) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        return False


@pytest.fixture
def sem_rede(monkeypatch):
    """Conexão para fora do loopback vira erro, e a tentativa fica na lista."""
    tentativas: list[str] = []
    conectar = socket.socket.connect
    resolver = socket.getaddrinfo

    def connect(self, endereco):
        host = endereco[0] if isinstance(endereco, tuple) else endereco
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(host):
            tentativas.append(f"connect {endereco}")
            raise OSError("rede desligada no teste")
        return conectar(self, endereco)

    def getaddrinfo(host, *args, **kwargs):
        if not _loopback(host):
            tentativas.append(f"getaddrinfo {host}")
            raise socket.gaierror("rede desligada no teste")
        return resolver(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return tentativas


def test_trava_de_rede_funciona(sem_rede):
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
    assert sem_rede == ["getaddrinfo example.com"]


# ---------------------------------------------------------------------------
# Fluxo completo com dado marcado
# ---------------------------------------------------------------------------

LINHAS = [
    ("Ana Souza QXZ1", CPF, "Vitória", "ES", "1.234,56", "01/02/2024", "obs QXZ a"),
    ("Bruno Lima QXZ2", "111.444.777-35", "Vila Velha QXZ", "ES", "12,5QXZ", "31/02QXZ", "obs QXZ b"),
    ("Carla Dias QXZ3", "390.533.447-05", "Serra", "es", "-", "15/03/2024", ""),
    ("Total QXZ", "", "", "", "1.247,06", "", "obs QXZ c"),
]


@pytest.fixture
def csv_marcado(tmp_path):
    caminho = tmp_path / "clientes.csv"
    cabecalho = "Nome;CPF;Município;UF;Valor;Data;Observação\n"
    corpo = "".join(";".join(linha) + "\n" for linha in LINHAS)
    caminho.write_bytes((cabecalho + corpo).encode("cp1252"))
    return caminho


def _numerados(passos, inicio):
    return [{**p, "id": f"s{i}"} for i, p in enumerate(passos, inicio)]


def _fluxo(client, csv_marcado, saida, monkeypatch):
    with csv_marcado.open("rb") as f:
        r = client.post("/api/projects", files={"file": ("clientes.csv", f, "text/csv")})
    assert r.status_code == 201, r.text
    projeto = r.json()
    url = f"/api/projects/{projeto['id']}"
    receita, etag = projeto["recipe"], projeto["etag"]
    for caminho in ("", "/structure", "/profile", "/preview", "/suggestions"):
        assert client.get(url + caminho).status_code == 200

    # Aceitar todas as sugestões e acrescentar as operações BR.
    sugestoes = sorted(client.get(url + "/suggestions").json(), key=lambda s: s["order"])
    passos = [p for s in sugestoes for p in s["steps"]]
    passos += [
        {"op": "clean_cpf", "cols": ["CPF"], "add_valid_col": True},
        {"op": "normalize_municipio", "col": "Município", "uf_col": "UF"},
        {"op": "parse_decimal_br", "cols": ["Valor"]},
        {"op": "parse_date_br", "cols": ["Data"]},
    ]
    nova = {**receita, "steps": receita["steps"] + _numerados(passos, len(receita["steps"]) + 1)}
    r = client.put(url + "/recipe", json=nova, headers={"If-Match": etag})
    assert r.status_code == 200, r.text
    etag, receita = r.json()["etag"], r.json()["recipe"]
    assert client.get(url + "/preview").status_code == 200
    municipio = next(s["id"] for s in receita["steps"] if s["op"] == "normalize_municipio")
    assert client.get(f"{url}/steps/{municipio}/municipios").status_code == 200
    assert client.get("/api/municipios", params={"q": "Vila Velha QXZ"}).status_code == 200

    # Erro de passo com o valor da célula: vai para o usuário, não para o log.
    quebrada = {
        **receita,
        "steps": [*receita["steps"], {"id": "s99", "op": "cast", "types": {"Nome": "int"}}],
    }
    r = client.put(url + "/recipe", json=quebrada, headers={"If-Match": etag})
    etag = r.json()["etag"]
    assert client.get(url + "/preview").status_code in (200, 422)
    r = client.put(url + "/recipe", json=receita, headers={"If-Match": etag})
    assert r.status_code == 200

    formatos = ["csv", "xlsx", "parquet", "powerquery", "python", "pbip"]
    formatos += ["hyper"] if hyper_disponivel() else []
    pedido = {"formats": formatos, "output_dir": str(saida), "source_path": str(csv_marcado)}
    r = client.post(url + "/exports", json=pedido)
    assert r.status_code == 200, r.text

    # Falhas forçadas, com o valor na mensagem.
    def regra_que_quebra(ctx):
        raise ValueError(f"não converti {CPF!r} nem 'Ana Souza QXZ1'")
        yield

    monkeypatch.setitem(
        __import__("wolfz.core.suggest", fromlist=["_REGRAS"])._REGRAS, "quebra", regra_que_quebra
    )
    assert client.get(url + "/suggestions").status_code == 200

    def preview_que_quebra(*args, **kwargs):
        raise RuntimeError(f"célula {CPF} QXZ")

    monkeypatch.setattr("wolfz.api.rotas.preview_project", preview_que_quebra)
    assert client.get(url + "/preview").status_code == 500
    return receita


def test_fluxo_completo_sem_rede_e_sem_dado_no_log(tmp_path, csv_marcado, sem_rede, caplog, monkeypatch):
    caplog.set_level("DEBUG")
    settings = Settings(workspace=Workspace(tmp_path / "home"), port=PORTA, token=TOKEN)
    saida = tmp_path / "saida"
    with cliente(settings) as client:
        receita = _fluxo(client, csv_marcado, saida, monkeypatch)

    # O mesmo pela CLI.
    arquivo = tmp_path / "receita.wolfz.json"
    import json

    arquivo.write_text(json.dumps(receita), encoding="utf-8")
    resultado = CliRunner().invoke(
        cli, ["run", str(arquivo), str(csv_marcado), "-o", str(tmp_path / "x.csv")]
    )
    assert resultado.exit_code in (0, 1), resultado.output

    assert sem_rede == [], "o fluxo tentou usar a rede"
    assert any(r.name.startswith("wolfz") for r in caplog.records), "as falhas forçadas não chegaram ao log"
    # httpx e httpcore são o lado cliente do TestClient (em produção, o
    # navegador); o servidor roda sem log de acesso (server.py).
    do_servidor = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    for registro in do_servidor:
        texto = registro.getMessage() + (registro.exc_text or "")
        if registro.exc_info:
            texto += repr(registro.exc_info[1])
        for proibido in (MARCA, CPF, "52998224725", "Ana Souza"):
            assert proibido not in texto, f"{proibido!r} no log: {registro.name}: {texto}"

    # O token da sessão não foi para nenhum arquivo do workspace.
    for caminho in (tmp_path / "home").rglob("*"):
        if caminho.is_file():
            assert TOKEN.encode() not in caminho.read_bytes(), caminho


# ---------------------------------------------------------------------------
# Varredura estática
# ---------------------------------------------------------------------------

REDE = {"httpx", "requests", "urllib", "urllib3", "http", "aiohttp", "ftplib", "smtplib", "socket", "ssl"}
# server.py: socket só para achar porta livre em 127.0.0.1; webbrowser abre a URL local.
PERMITIDOS = {("api/server.py", "socket"), ("api/server.py", "webbrowser")}


def _imports(caminho: Path) -> set[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            nomes.add(no.module.split(".")[0])
    return nomes


def test_pacote_nao_importa_cliente_de_rede():
    pacote = RAIZ / "src" / "wolfz"
    achados = []
    for caminho in sorted(pacote.rglob("*.py")):
        relativo = caminho.relative_to(pacote).as_posix()
        for nome in _imports(caminho) & (REDE | {"webbrowser"}):
            if (relativo, nome) not in PERMITIDOS:
                achados.append(f"{relativo}: {nome}")
    assert not achados


_RECURSO_REMOTO = re.compile(
    r"""(?:src|href)\s*=\s*["']?(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import\s+(?:url\()?["']?(?:https?:)?//"""
    r"""|fetch\(\s*["'`]https?://|import\(\s*["'`]https?://""",
    re.IGNORECASE,
)


def _sem_recurso_remoto(arquivos):
    achados = []
    for caminho in arquivos:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
        for m in _RECURSO_REMOTO.finditer(texto):
            achados.append(f"{caminho.name}: {texto[m.start() : m.start() + 80]!r}")
    return achados


def test_interface_nao_carrega_nada_de_fora():
    """Sem fonte, script ou folha de estilo de CDN (§11.7), no código da
    interface e no build empacotado, quando existir."""
    frontend = RAIZ / "frontend"
    fontes = [frontend / "index.html", *(frontend / "src").rglob("*.ts*"), *(frontend / "src").rglob("*.css")]
    assert not _sem_recurso_remoto(fontes)
    build = [
        p for p in (RAIZ / "src" / "wolfz" / "static").rglob("*") if p.suffix in {".html", ".js", ".css"}
    ]
    assert not _sem_recurso_remoto(build)


def test_varredura_pega_recurso_remoto(tmp_path):
    casos = [
        '<script src="https://cdn.example.com/x.js"></script>',
        "<link href='//fonts.googleapis.com/css?family=Inter'>",
        "@import url('https://fonts.example.com/a.css');",
        'fetch("https://telemetria.example.com/evento")',
    ]
    for i, caso in enumerate(casos):
        (tmp_path / f"{i}.html").write_text(caso, encoding="utf-8")
    assert len(_sem_recurso_remoto(sorted(tmp_path.iterdir()))) == len(casos)

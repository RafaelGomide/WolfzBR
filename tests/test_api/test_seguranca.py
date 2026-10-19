"""Um teste para cada item de segurança da API (F1.G2, §11 do design)."""

import io
import socket

import pytest
from apoio_api import PORTA, TOKEN, cliente, enviar
from fastapi import UploadFile

from wolfz.api.problems import Problem
from wolfz.api.rotas import _copia_com_limite
from wolfz.api.security import ORIGENS_VITE, Settings, novo_token
from wolfz.api.server import HOST, criar_servidor, porta_livre
from wolfz.core.ingest import Limits
from wolfz.core.workspace import Workspace

# ---------------------------------------------------------------------------
# Bind em 127.0.0.1, porta livre aleatória
# ---------------------------------------------------------------------------


def test_servidor_escuta_so_no_loopback(tmp_path):
    servidor, url = criar_servidor(Workspace(tmp_path))
    assert servidor.config.host == HOST == "127.0.0.1"
    assert servidor.config.port > 0
    assert url.startswith(f"http://127.0.0.1:{servidor.config.port}/")


def test_porta_livre_e_aleatoria_e_esta_livre():
    portas = {porta_livre() for _ in range(5)}
    assert all(p > 0 for p in portas) and len(portas) > 1
    with socket.socket() as s:
        s.bind(("127.0.0.1", portas.pop()))  # a porta devolvida pode mesmo ser usada


def test_porta_escolhida_e_respeitada(tmp_path):
    servidor, _ = criar_servidor(Workspace(tmp_path), port=PORTA)
    assert servidor.config.port == PORTA


# ---------------------------------------------------------------------------
# Token de sessão
# ---------------------------------------------------------------------------


def test_token_novo_a_cada_start(tmp_path):
    tokens = {novo_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 43 for t in tokens)  # 32 bytes em base64 url-safe
    a = Settings(workspace=Workspace(tmp_path), port=1)
    b = Settings(workspace=Workspace(tmp_path), port=1)
    assert a.token != b.token
    assert a.token not in repr(a)  # nunca aparece no repr (logs)


def test_token_vai_no_fragmento_da_url(tmp_path):
    servidor, url = criar_servidor(Workspace(tmp_path))
    token = servidor.config.app.state.settings.token
    assert url.endswith(f"/#token={token}")  # o navegador não envia o fragmento ao servidor


@pytest.mark.parametrize(
    "cabecalho",
    [None, "Bearer errado", f"Basic {TOKEN}", TOKEN, f"Bearer {TOKEN}x", "Bearer "],
)
def test_api_exige_token_bearer(settings, cabecalho):
    with cliente(settings) as c:
        headers = {"Authorization": cabecalho} if cabecalho else {}
        c.headers.pop("Authorization")
        r = c.get("/api/projects", headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_token_certo_passa(client):
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/projects", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_pagina_inicial_nao_exige_token(settings):
    with cliente(settings) as c:
        c.headers.pop("Authorization")
        r = c.get("/")
    assert r.status_code == 200 and "WolfzBR" in r.text


# ---------------------------------------------------------------------------
# Header Host (DNS rebinding)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["evil.example.com", f"evil.example.com:{PORTA}", "127.0.0.1:9999", "0.0.0.0:8765", "[::1]:8765", ""],
)
def test_host_estranho_e_recusado(client, host):
    r = client.get("/api/projects", headers={"Host": host})
    assert r.status_code == 403
    assert r.json()["title"] == "Host não permitido"
    assert client.get("/", headers={"Host": host}).status_code == 403  # vale também para a SPA


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"])
def test_host_do_loopback_passa(client, host):
    assert client.get("/api/projects", headers={"Host": host}).status_code == 200


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def _preflight(c, origem):
    return c.options(
        "/api/projects",
        headers={"Origin": origem, "Access-Control-Request-Method": "GET"},
    )


@pytest.mark.parametrize("origem", [*ORIGENS_VITE, "https://evil.example.com"])
def test_sem_cors_em_producao(client, origem):
    assert "access-control-allow-origin" not in _preflight(client, origem).headers
    r = client.get("/api/projects", headers={"Origin": origem})
    assert "access-control-allow-origin" not in r.headers


def test_cors_so_para_o_vite_em_desenvolvimento(tmp_path):
    settings = Settings(workspace=Workspace(tmp_path), port=PORTA, token=TOKEN, dev=True)
    with cliente(settings) as c:
        for origem in ORIGENS_VITE:
            r = _preflight(c, origem)
            assert r.headers["access-control-allow-origin"] == origem
        assert "access-control-allow-origin" not in _preflight(c, "https://evil.example.com").headers


def test_documentacao_da_api_so_em_desenvolvimento(tmp_path, client):
    assert client.get("/api/docs").status_code == 404
    settings = Settings(workspace=Workspace(tmp_path), port=PORTA, token=TOKEN, dev=True)
    with cliente(settings) as c:
        assert c.get("/api/docs").status_code == 200


# ---------------------------------------------------------------------------
# Limite de upload
# ---------------------------------------------------------------------------


def test_upload_acima_do_limite_pelo_content_length(tmp_path):
    settings = Settings(
        workspace=Workspace(tmp_path), port=PORTA, token=TOKEN, limits=Limits(max_file_bytes=1000)
    )
    with cliente(settings) as c:
        grande = b"a;b\n" * 100_000
        r = c.post("/api/projects", files={"file": ("x.csv", grande, "text/csv")})
    assert r.status_code == 413
    assert r.json()["code"] == "file_too_large"
    assert not (tmp_path / "projects").exists()  # nada foi criado


def test_upload_que_mente_o_tamanho_para_na_copia(tmp_path):
    upload = UploadFile(io.BytesIO(b"x" * 5000), filename="a.csv")
    with pytest.raises(Problem) as exc:
        _copia_com_limite(upload, tmp_path / "a.csv", 1000)
    assert exc.value.status == 413


def test_upload_dentro_do_limite_passa(tmp_path):
    settings = Settings(
        workspace=Workspace(tmp_path), port=PORTA, token=TOKEN, limits=Limits(max_file_bytes=10_000)
    )
    with cliente(settings) as c:
        r = c.post("/api/projects", files={"file": ("x.csv", b"a;b\n1;2\n", "text/csv")})
    assert r.status_code == 201, r.text


def test_lock_aberto_numa_thread_e_fechado_em_outra(tmp_path):
    """O servidor atende num pool de threads: o projeto é aberto numa
    requisição e fechado (ou apagado) em outra. O lock tem de soltar de
    verdade. Com o filelock por thread, o release da outra thread não fazia
    nada: o projeto aparecia "aberto em outra janela" no próprio servidor e
    o Windows não deixava apagar o .lock ("já está sendo usado por outro
    processo")."""
    import shutil
    import threading

    from wolfz.api.projetos import Projetos
    from wolfz.core.engine.cache import projeto_travado
    from wolfz.core.workspace import PROJECT_FILE, Workspace

    ws = Workspace(tmp_path / "home")
    project_id, pasta = ws.new_project()
    (pasta / PROJECT_FILE).write_text("{}", encoding="utf-8")
    projetos = Projetos(ws, 8765)

    # A thread que abriu continua viva, como as do pool: se ela morresse, o
    # filelock fecharia o arquivo sozinho e o bug não apareceria.
    aberto, fim = threading.Event(), threading.Event()

    def abrir_e_esperar():
        projetos.abrir(project_id)
        aberto.set()
        fim.wait(10)

    dona = threading.Thread(target=abrir_e_esperar)
    dona.start()
    try:
        aberto.wait(10)
        # Outra referência ao lock, como as que o servidor mantém (o filelock
        # só solta a posse de outra thread quando o último objeto some).
        referencia = projetos._locks[project_id]
        fechar = threading.Thread(target=projetos.fechar, args=(project_id,))
        fechar.start()
        fechar.join()
        assert not projeto_travado(pasta)
        assert not projetos.aberto_em_outra(project_id, pasta)
        shutil.rmtree(pasta)  # o WinError 32 do relato aparecia aqui
        del referencia
    finally:
        fim.set()
        dona.join()


def test_apagar_enquanto_a_listagem_le_os_projetos(client):
    """Apagar enquanto outra requisição lista os projetos (lê o project.json
    e abre o .lock de cada um) não pode falhar no Windows."""
    import threading

    parar, erros = threading.Event(), []

    def listar():
        while not parar.is_set():
            r = client.get("/api/projects")
            if r.status_code != 200:
                erros.append(r.text)

    t = threading.Thread(target=listar)
    t.start()
    try:
        for _ in range(8):
            pid = enviar(client).json()["id"]
            r = client.delete(f"/api/projects/{pid}")
            assert r.status_code == 204, r.text
    finally:
        parar.set()
        t.join()
    assert not erros

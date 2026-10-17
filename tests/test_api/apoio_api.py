"""Utilitários dos testes da API (importados pelos testes e pelo conftest)."""

from pathlib import Path

from fastapi.testclient import TestClient

from wolfz.api.app import create_app

PORTA = 8765
TOKEN = "token-de-teste"
CORPUS = Path(__file__).resolve().parents[1] / "corpus"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def cliente(settings, **kwargs) -> TestClient:
    return TestClient(
        create_app(settings),
        base_url=f"http://127.0.0.1:{settings.port}",
        headers={"Authorization": f"Bearer {settings.token}"},
        **kwargs,
    )


def enviar(client, nome="receita_municipal", arquivo="original.xlsx", **data):
    caminho = CORPUS / nome / arquivo
    with caminho.open("rb") as f:
        return client.post("/api/projects", files={"file": (nome + caminho.suffix, f, XLSX)}, data=data)

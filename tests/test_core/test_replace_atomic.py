"""Rename atômico que aguenta leitor concorrente no Windows (achado no F1.K1:
o salvamento automático falhava quando um preview lia a receita)."""

from pathlib import Path

import pytest

from wolfz.core import workspace
from wolfz.core.workspace import replace_atomic


def test_tenta_de_novo_quando_o_destino_esta_aberto(tmp_path, monkeypatch):
    tmp, dest = tmp_path / ".a.tmp", tmp_path / "a.json"
    tmp.write_text("novo")
    dest.write_text("antigo")
    original = Path.replace
    falhas = iter([True, True, False])

    def replace(self, alvo):
        if next(falhas):
            raise PermissionError(5, "Acesso negado")
        return original(self, alvo)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(workspace.time, "sleep", lambda _: None)
    replace_atomic(tmp, dest)
    assert dest.read_text() == "novo" and not tmp.exists()


def test_desiste_depois_das_tentativas(tmp_path, monkeypatch):
    tmp, dest = tmp_path / ".a.tmp", tmp_path / "a.json"
    tmp.write_text("novo")
    chamadas = []

    def replace(self, alvo):
        chamadas.append(alvo)
        raise PermissionError(5, "Acesso negado")

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(workspace.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        replace_atomic(tmp, dest, tentativas=3)
    assert len(chamadas) == 3


def test_outro_erro_nao_e_repetido(tmp_path, monkeypatch):
    chamadas = []

    def replace(self, alvo):
        chamadas.append(alvo)
        raise FileNotFoundError(alvo)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(FileNotFoundError):
        replace_atomic(tmp_path / "x", tmp_path / "y")
    assert len(chamadas) == 1

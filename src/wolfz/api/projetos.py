"""Projetos abertos nesta instância: lock por projeto e serialização do preview.

Lock (§9 do design, F0.A8): lock de arquivo do sistema operacional em
``<projeto>/.lock`` (pacote ``filelock``), adquirido ao criar ou abrir o
projeto e mantido até fechar o projeto ou encerrar o processo. Se o processo
morre, o SO libera sozinho. Ao lado, ``.lock.json`` com pid, porta e hora,
só para a mensagem de erro ("aberto em outra janela, em http://…").
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from filelock import FileLock, Timeout

from wolfz.api.problems import Problem
from wolfz.core.engine.cache import projeto_travado
from wolfz.core.workspace import PROJECT_FILE, Workspace

LOCK_META = ".lock.json"
TENTATIVAS_APAGAR = 40  # x 50 ms: até 2 s esperando outro handle do .lock fechar


def _tentando(acao: Callable[[], object]) -> None:
    """Apaga esperando o compartilhamento do Windows: um arquivo aberto por
    outra thread ("já está sendo usado por outro processo"), como o
    ``project.json`` que a listagem está lendo, fecha em milissegundos."""
    for tentativa in range(TENTATIVAS_APAGAR):
        try:
            acao()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if tentativa == TENTATIVAS_APAGAR - 1:
                raise
            time.sleep(0.05)


class Projetos:
    def __init__(self, workspace: Workspace, port: int):
        self.workspace = workspace
        self.port = port
        self._locks: dict[str, FileLock] = {}
        self._previews: dict[str, threading.Lock] = {}
        self._mutex = threading.Lock()

    def pasta(self, project_id: str) -> Path:
        """Pasta do projeto; 404 se o id é inválido ou não existe."""
        try:
            pasta = self.workspace.project_dir(project_id)
        except ValueError as exc:
            raise Problem(404, f"Projeto {project_id!r} não existe.") from exc
        if not (pasta / PROJECT_FILE).is_file():
            raise Problem(404, f"Projeto {project_id!r} não existe.")
        return pasta

    def abrir(self, project_id: str) -> Path:
        """Abre o projeto nesta instância (idempotente); 423 se ele está aberto
        em outra."""
        pasta = self.pasta(project_id)
        with self._mutex:
            if project_id in self._locks:
                return pasta
            # thread_local=False: o projeto é aberto numa thread de requisição e
            # fechado em outra (o servidor atende num pool de threads). Com o
            # padrão do filelock (por thread), o release da outra thread não
            # faz nada e o .lock fica preso até o processo morrer.
            lock = FileLock(pasta / ".lock", thread_local=False)
            try:
                lock.acquire(timeout=0)
            except Timeout as exc:
                raise Problem(
                    423,
                    "Este projeto já está aberto em outra janela do WolfzBR" + self._onde(pasta) + ".",
                ) from exc
            meta = {"pid": os.getpid(), "port": self.port, "opened_at": datetime.now(UTC).isoformat()}
            (pasta / LOCK_META).write_text(json.dumps(meta), encoding="utf-8")
            self._locks[project_id] = lock
        return pasta

    def _onde(self, pasta: Path) -> str:
        try:
            meta = json.loads((pasta / LOCK_META).read_text(encoding="utf-8"))
            return f", em http://127.0.0.1:{int(meta['port'])}"
        except (OSError, ValueError, KeyError, TypeError):
            return ""

    def aberto_aqui(self, project_id: str) -> bool:
        return project_id in self._locks

    def aberto_em_outra(self, project_id: str, pasta: Path) -> bool:
        return not self.aberto_aqui(project_id) and projeto_travado(pasta)

    def fechar(self, project_id: str) -> None:
        with self._mutex:
            lock = self._locks.pop(project_id, None)
            self._previews.pop(project_id, None)
        if lock is not None:
            pasta = Path(lock.lock_file).parent
            (pasta / LOCK_META).unlink(missing_ok=True)
            lock.release()

    def apagar(self, project_id: str) -> None:
        """Apaga o projeto (423 se está aberto em outra instância).

        No Windows, arquivo aberto em outra thread não pode ser apagado, e a
        listagem de projetos lê o ``project.json`` e abre o ``.lock`` de cada
        um. Por isso: com o lock ainda seguro, apaga o conteúdo, começando
        pelo ``project.json`` (a listagem para de ver o projeto); depois
        solta o lock e remove o resto. Cada remoção tenta de novo por um
        instante se outro handle ainda estiver aberto."""
        pasta = self.abrir(project_id)
        with self.lock_preview(project_id):
            _tentando((pasta / PROJECT_FILE).unlink)
            for item in list(pasta.iterdir()):
                if item.name in (".lock", LOCK_META):
                    continue
                _tentando(partial(shutil.rmtree, item) if item.is_dir() else item.unlink)
        self.fechar(project_id)
        _tentando(partial(shutil.rmtree, pasta))

    def fechar_todos(self) -> None:
        for project_id in list(self._locks):
            self.fechar(project_id)

    def lock_preview(self, project_id: str) -> threading.Lock:
        """Um preview por projeto por vez (§11.5): o segundo espera o primeiro."""
        with self._mutex:
            return self._previews.setdefault(project_id, threading.Lock())

    def abertos(self) -> set[Path]:
        return {Path(lock.lock_file).parent for lock in self._locks.values()}

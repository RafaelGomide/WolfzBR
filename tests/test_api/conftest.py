import pytest
from apoio_api import PORTA, TOKEN, cliente, enviar

from wolfz.api.security import Settings
from wolfz.core.workspace import Workspace


@pytest.fixture
def settings(tmp_path):
    return Settings(workspace=Workspace(tmp_path / "home"), port=PORTA, token=TOKEN)


@pytest.fixture
def client(settings):
    with cliente(settings) as c:
        yield c


@pytest.fixture
def projeto(client):
    resposta = enviar(client)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()

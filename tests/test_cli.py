import pytest
from typer.testing import CliRunner

import wolfz
from wolfz.cli import app


def test_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"wolfz {wolfz.__version__}"


def test_api_publica_ainda_nao_implementada():
    with pytest.raises(NotImplementedError):
        wolfz.load_recipe("receita.wolfz.json")
    with pytest.raises(NotImplementedError):
        wolfz.run("receita.wolfz.json", "dados.csv")

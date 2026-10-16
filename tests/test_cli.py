from typer.testing import CliRunner

import wolfz
from wolfz.cli import app


def test_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"wolfz {wolfz.__version__}"


def test_api_publica():
    assert wolfz.load_recipe is wolfz.core.recipe.load_recipe
    assert wolfz.run is wolfz.core.engine.run_file

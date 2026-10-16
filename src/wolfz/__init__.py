"""WolfzBR: limpeza de planilhas brasileiras com receitas reproduzíveis.

API pública mínima para uso em notebook e scripts::

    import wolfz

    receita = wolfz.load_recipe("vendas.wolfz.json")
    df = wolfz.run(receita, "vendas_jan.csv")
"""

from importlib.metadata import PackageNotFoundError, version

from wolfz.core.engine import StepError
from wolfz.core.engine import run_file as run
from wolfz.core.recipe import RecipeError, load_recipe

try:
    __version__ = version("wolfzbr")
except PackageNotFoundError:  # rodando do código-fonte sem instalar
    __version__ = "0.0.0+desconhecida"

__all__ = ["RecipeError", "StepError", "__version__", "load_recipe", "run"]

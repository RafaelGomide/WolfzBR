"""WolfzBR: limpeza de planilhas brasileiras com receitas reproduzíveis.

API pública para uso em notebook e scripts::

    import wolfz

    receita = wolfz.load_recipe("vendas.wolfz.json")
    df = wolfz.run(receita, "vendas_jan.csv")
    r = wolfz.run_report(receita, "vendas_jan.csv")  # a tabela e as linhas de cada passo
    wolfz.br.clean_cpf("123.456.789-09")

Só é pública, e segue o versionamento semântico a partir da 1.0, o que está
em ``__all__`` deste módulo e em ``wolfz.br.__all__``. O resto do pacote
(``wolfz.core``, ``wolfz.ops``, ``wolfz.export``, ``wolfz.api``,
``wolfz.cli`` e os submódulos de ``wolfz.br``) é interno: serve à CLI e à
interface e pode mudar em qualquer versão. O formato da receita
(``wolfz_version``) tem a própria política de compatibilidade (§5.7 do design).
"""

from importlib.metadata import PackageNotFoundError, version

from wolfz import br
from wolfz.core.engine import RunReport, StepCount, StepError, run_report
from wolfz.core.engine import run_file as run
from wolfz.core.recipe import RecipeError, load_recipe

try:
    __version__ = version("wolfzbr")
except PackageNotFoundError:  # rodando do código-fonte sem instalar
    __version__ = "0.0.0+desconhecida"

__all__ = [
    "RecipeError",
    "RunReport",
    "StepCount",
    "StepError",
    "__version__",
    "br",
    "load_recipe",
    "run",
    "run_report",
]

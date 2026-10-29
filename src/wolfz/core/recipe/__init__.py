"""Receita: modelo, validação, migração de versão e serialização estável."""

from wolfz.core.recipe.io import (
    RecipeError,
    RecipeTooNewError,
    dumps_recipe,
    formato_minimo,
    load_recipe,
    loads_recipe,
    recipe_from_dict,
    recipe_json_schema,
    save_recipe,
)
from wolfz.core.recipe.migrate import CURRENT_VERSION, NewerRecipeVersion, RecipeVersionError, migrate
from wolfz.core.recipe.models import (
    Op,
    Recipe,
    Source,
    SourceCombine,
    SourceMatch,
    register_op,
    registered_ops,
)

__all__ = [
    "CURRENT_VERSION",
    "NewerRecipeVersion",
    "Op",
    "Recipe",
    "RecipeError",
    "RecipeTooNewError",
    "RecipeVersionError",
    "Source",
    "SourceCombine",
    "SourceMatch",
    "dumps_recipe",
    "formato_minimo",
    "load_recipe",
    "loads_recipe",
    "migrate",
    "recipe_from_dict",
    "recipe_json_schema",
    "register_op",
    "registered_ops",
    "save_recipe",
]

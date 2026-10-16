"""Catálogo de operações: schema + Polars + M + Python para cada passo de receita.

Importar este pacote registra todas as operações (``@register_op``).
"""

from wolfz.ops.br import ParseBrl
from wolfz.ops.colunas import Rename
from wolfz.ops.linhas import DropRowsWhere

__all__ = ["DropRowsWhere", "ParseBrl", "Rename"]

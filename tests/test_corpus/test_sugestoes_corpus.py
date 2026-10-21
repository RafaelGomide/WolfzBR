"""Sugestões contra o corpus (pronto da Fase 2): a receita esperada de cada
arquivo é o roteiro, e as sugestões têm de cobrir a maior parte dos passos.

Mesma conta de ``scripts/medir_sugestoes.py --corpus``. Renomear fica de
fora: o nome que a pessoa escolhe nenhuma regra adivinha. O piso é o valor
medido quando as regras da 0.7 entraram, com uma folga pequena; subir uma
regra que cobre mais passos deve subir o piso também.
"""

import pytest
from corpus_lib import _script

PISO = 0.85


@pytest.fixture(scope="module")
def linhas():
    return [linha for _, ls in _script("medir_sugestoes").medir_corpus() for linha in ls]


def test_sugestoes_cobrem_o_corpus(linhas):
    contam = [(op, f) for op, f, _ in linhas if f >= 0 and op != "rename"]
    cobertura = sum(f for _, f in contam) / len(contam)
    assert cobertura >= PISO, f"as sugestões cobrem {cobertura:.0%} dos passos do corpus (piso {PISO:.0%})"

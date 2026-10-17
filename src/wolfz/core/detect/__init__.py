"""Detecção de estrutura: área da tabela, cabeçalho, totais e rodapé, propostos como passos de receita."""

from wolfz.core.detect.metrics import RowMetrics, classify, row_metrics
from wolfz.core.detect.structure import Detection, detect_structure

__all__ = ["Detection", "RowMetrics", "classify", "detect_structure", "row_metrics"]

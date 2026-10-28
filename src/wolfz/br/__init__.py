"""Parsers, validadores e constantes de dados brasileiros.

Funções de valor puras: recebem UM valor bruto e devolvem o valor limpo ou
``None``. Não dependem de Polars nem de arquivos (§6.2 do design); as
operações em ``wolfz.ops`` é que as aplicam em colunas inteiras.

API pública: os nomes de ``__all__``, importados daqui (``wolfz.br.clean_cpf``),
seguem o versionamento semântico a partir da 1.0. Os submódulos e o resto do
que eles têm (inclusive ``wolfz.br.municipios``, que depende do de-para do
IBGE embutido) são internos e podem mudar em qualquer versão.
"""

from wolfz.br.booleanos import parse_bool_br
from wolfz.br.constants import MESES, UFS
from wolfz.br.datas import excel_serial_to_date, parse_date_br, parse_datetime_br, parse_month_year
from wolfz.br.documentos import (
    clean_cep,
    clean_cnpj,
    clean_cpf,
    clean_cpf_cnpj,
    clean_phone,
    cnpj_is_valid,
    cpf_is_valid,
    format_cnpj,
    format_cpf,
)
from wolfz.br.geo import ibge_code_6, normalize_uf, split_municipio_uf
from wolfz.br.numeros import (
    format_brl,
    parse_brl,
    parse_ibge_value,
    parse_number_br,
    parse_percent_br,
    scale_from_unit,
)

__all__ = [
    "MESES",
    "UFS",
    "clean_cep",
    "clean_cnpj",
    "clean_cpf",
    "clean_cpf_cnpj",
    "clean_phone",
    "cnpj_is_valid",
    "cpf_is_valid",
    "excel_serial_to_date",
    "format_brl",
    "format_cnpj",
    "format_cpf",
    "ibge_code_6",
    "normalize_uf",
    "parse_bool_br",
    "parse_brl",
    "parse_date_br",
    "parse_datetime_br",
    "parse_ibge_value",
    "parse_month_year",
    "parse_number_br",
    "parse_percent_br",
    "scale_from_unit",
    "split_municipio_uf",
]

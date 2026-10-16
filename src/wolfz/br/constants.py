"""Constantes compartilhadas: UFs, meses e marcadores de ausência."""

from __future__ import annotations

UFS: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

# Abreviações em português e em inglês (Excel em inglês exporta "15-Mar-2024").
MESES: dict[str, int] = {
    "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "feb": 2,
    "mar": 3, "marco": 3, "abr": 4, "abril": 4, "apr": 4,
    "mai": 5, "maio": 5, "may": 5, "jun": 6, "junho": 6,
    "jul": 7, "julho": 7, "ago": 8, "agosto": 8, "aug": 8,
    "set": 9, "setembro": 9, "sep": 9, "sept": 9,
    "out": 10, "outubro": 10, "oct": 10, "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12, "dec": 12,
}

# Marcadores de "sem valor" vistos em bases públicas e em exportações
# corporativas, já normalizados por ``normalize_key``. Casos de origem:
#   Excel PT-BR/EN: #N/D, #VALOR!, #DIV/0!, #REF!, #NOME?, #NÚM!, #NULO!
#   TSE: #NULO#, #NE#
#   Portal da Transparência: "Sem Informação", "Não Identificado"
#   Datas vazias de sistemas legados: 00/00/0000, 0000-00-00, 00000000
# "-" fica de fora de propósito: em formato contábil e nas tabelas do IBGE
# ele significa ZERO, não ausência (ver wolfz.br.numeros.parse_brl e parse_ibge_value).
NULL_TOKENS: frozenset[str] = frozenset({
    "", "--", "---", "?", "na", "n/a", "n.a.", "n/d", "nd", "nan", "null",
    "none", "nil", "<null>", "(null)", "#n/d", "#n/a", "#valor!", "#value!",
    "#div/0!", "#ref!", "#nome?", "#name?", "#num!", "#nulo!", "#null!",
    "#nulo#", "#ne#", "s/i", "s.i.", "sem informacao", "nao informado",
    "nao identificado", "nao disponivel", "(vazio)", "(em branco)", "(blank)",
    "00/00/0000", "0000-00-00", "00000000",
})

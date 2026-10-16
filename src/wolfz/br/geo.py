"""UF, município e código IBGE."""

from __future__ import annotations

import re

from wolfz.br.constants import UFS
from wolfz.br.documentos import _prepare_id
from wolfz.core.text import clean_text, normalize_key, only_digits

_UF_BY_KEY = {normalize_key(name): uf for uf, name in UFS.items()} | {uf.lower(): uf for uf in UFS}


def normalize_uf(value: object) -> str | None:
    """'ES', 'es', 'Espírito Santo', 'ESPIRITO SANTO' -> 'ES'."""
    return _UF_BY_KEY.get(normalize_key(value))


_MUN_UF = (
    re.compile(r"(.+?)\s*\(([A-Za-z]{2})\)"),  # Alta Floresta D'Oeste (RO)  [SIDRA]
    re.compile(r"(.+?)\s*[-\u2013/]\s*([A-Za-z]{2})"),  # Vitória - ES / Vitória/ES
)


def split_municipio_uf(text: object) -> tuple[str | None, str | None]:
    """Separa município e UF quando vêm no mesmo campo.

    'Alta Floresta D'Oeste (RO)' -> ("Alta Floresta D'Oeste", 'RO')
    'Vitória - ES' -> ('Vitória', 'ES');  'Vitória' -> ('Vitória', None).
    Só separa se o sufixo for uma UF real, para não cortar nomes como
    'Embu-Guaçu'."""
    s = clean_text(text)
    if s is None:
        return None, None
    for pattern in _MUN_UF:
        if (m := pattern.fullmatch(s)) and m[2].upper() in UFS:
            return m[1].strip(), m[2].upper()
    return s, None


def ibge_code_6(code: object) -> str | None:
    """Código de município IBGE de 7 dígitos -> 6 dígitos.

    DATASUS (SIM, SINASC, SIH, CNES) usa 6 dígitos, sem o dígito
    verificador: '3550308' -> '355030'. Para cruzar DATASUS com IBGE, faça o
    join pelos 6 primeiros dígitos em vez de tentar reconstruir o sétimo."""
    d = only_digits(_prepare_id(code))
    return d[:6] if len(d) in (6, 7) else None

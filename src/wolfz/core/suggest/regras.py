"""As regras de sugestão (F2.E2). Uma função por regra; o nome da função é o
nome da regra, que aparece na interface e na lista de rejeitadas.

Cada regra só olha colunas que ainda são texto: depois que o passo
sugerido entra na receita, a coluna muda de tipo (ou de forma) e a
sugestão some sozinha.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

import polars as pl

from wolfz.br.constants import MESES, UFS
from wolfz.br.datas import parse_date_br, parse_month_year
from wolfz.br.documentos import clean_cep, clean_cnpj, clean_cpf, cnpj_is_valid, cpf_is_valid
from wolfz.br.numeros import decimal_provavel, parse_number_br
from wolfz.core.suggest import CONVERSAO, DOCUMENTO, FORMA, LIMPEZA, VERIFICACAO, Contexto, Suggestion, rule
from wolfz.core.text import (
    fix_mojibake,
    is_null_token,
    normalize_key,
    normalize_spaces,
    strip_footnote_marks,
)

TAXA = 0.9  # fração dos valores que precisa casar com o tipo
SINAIS_IBGE = {"-", "..", "...", "x", "X"}
# Espaço não separável, de número, estreito, fino e ideográfico; zero-width, BOM e hífen suave.
_ESPECIAIS = (0x00A0, 0x2007, 0x202F, 0x2009, 0x3000, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD)
ESPACOS_ESPECIAIS = re.compile("[" + "".join(map(chr, _ESPECIAIS)) + "\t\r\n]")


def _lista(cols: list[str], n: int = 3) -> str:
    nomes = ", ".join(f"'{c}'" for c in cols[:n])
    return nomes + (f" e mais {len(cols) - n}" if len(cols) > n else "")


def _exemplo(ctx: Contexto, col: str) -> str:
    valores = ctx.valores(col)
    return f" (ex.: '{valores[0]}')" if valores else ""


def _uteis(ctx: Contexto, col: str) -> list[str]:
    """Valores preenchidos que não são marcador de nulo ('-', 'N/D')."""
    return [v for v in ctx.valores(col) if not is_null_token(v)]


def _tem_sinais_ibge(ctx: Contexto, col: str) -> bool:
    return any(v in SINAIS_IBGE for v in ctx.valores(col))


_NOME_DE_CODIGO = re.compile(r"\b(cod|codigo|cd|id|cep|cnpj|cpf|matricula|ibge|cnae|ncm|lote|conta)\b")


def _nome(col: str) -> str:
    """Nome da coluna em palavras: 'codTipoOrgao' -> 'cod tipo orgao', 'CD_MUN' -> 'cd mun'."""
    separado = re.sub(r"([a-z])([A-Z])", r"\1 \2", col)
    return " ".join(re.sub(r"[_.\-/]", " ", normalize_key(separado)).split())


def _parece_codigo(ctx: Contexto, col: str) -> bool:
    """Nome de código ('Cód.', 'CD_MUN', 'Id_SERVIDOR') ou só inteiros com
    o mesmo tamanho, de 5 dígitos ou mais (código IBGE, CEP, CNPJ)."""
    nome = _nome(col)
    if _NOME_DE_CODIGO.search(nome):
        return True
    valores = _uteis(ctx, col)
    return (
        bool(valores)
        and all(v.isdigit() for v in valores)
        and len({len(v) for v in valores}) == 1
        and (len(valores[0]) >= 5)
    )


def _do_tipo(ctx: Contexto, tipo: str) -> list[tuple[str, float]]:
    saida = []
    for c in ctx.texto:
        p = ctx.perfil(c)
        if p.inferred_type != tipo or p.type_rate < TAXA or _tem_sinais_ibge(ctx, c):
            continue
        if tipo in ("numero", "moeda") and _parece_codigo(ctx, c):
            continue
        saida.append((c, p.type_rate))
    return saida


def _debito_credito(ctx: Contexto, cols: list[str]) -> bool:
    """Algum valor de dinheiro com sufixo D/C de débito e crédito ('5.000,00 D')."""
    return any(re.search(r"\d,\d{2}\s*[DdCc]$", v) for c in cols for v in ctx.valores(c))


def _conversao(ctx: Contexto, regra: str, tipo: str, op: str, motivo: str, **params) -> Iterator[Suggestion]:
    achadas = _do_tipo(ctx, tipo)
    if not achadas:
        return
    cols = [c for c, _ in achadas]
    taxa = min(t for _, t in achadas)
    if op in ("parse_brl", "parse_decimal_br") and _debito_credito(ctx, cols):
        params = {**params, "debit_negative": True}
        motivo += ", com D (débito) negativo"
    yield Suggestion(
        regra,
        ({"op": op, "cols": cols, **params},),
        taxa,
        f"{_lista(cols)}: {motivo}{_exemplo(ctx, cols[0])}.",
        tuple(cols),
        order=CONVERSAO,
    )


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------


@rule
def moeda(ctx: Contexto) -> Iterator[Suggestion]:
    yield from _conversao(ctx, "moeda", "moeda", "parse_brl", "valor em reais escrito como texto")


_MES_ANO = re.compile(r"[a-z]{3,9}\.?\s*[/ -]\s*\d{2,4}|\d{1,2}\s*[/-]\s*(19|20)\d{2}")


@rule
def mes_ano(ctx: Contexto) -> Iterator[Suggestion]:
    """Mês e ano escritos como texto ('jan/2024', 'Março 2025', '03/2024'):
    viram data, o dia 1 do mês."""
    cols = []
    for c in ctx.texto:
        if ctx.perfil(c).inferred_type in ("data", "numero", "moeda"):
            continue
        valores = _uteis(ctx, c)
        casam = [v for v in valores if _MES_ANO.fullmatch(normalize_key(v)) and parse_month_year(v)]
        if valores and len(casam) / len(valores) >= TAXA:
            cols.append(c)
    if cols:
        yield Suggestion(
            "mes_ano",
            ({"op": "parse_month_year", "cols": cols},),
            0.85,
            f"{_lista(cols)}: mês e ano escritos como texto{_exemplo(ctx, cols[0])}; "
            "viram data (dia 1 do mês).",
            tuple(cols),
            order=CONVERSAO,
        )


@rule
def notas_de_rodape(ctx: Contexto) -> Iterator[Suggestion]:
    """Marca de nota no fim do rótulo ('Abacaxi*', 'Brasília (1)', 'Total²'):
    a mesma categoria apareceria com e sem a marca."""
    cols = []
    for c in ctx.texto:
        if ctx.perfil(c).inferred_type != "texto":
            continue
        valores = _uteis(ctx, c)
        marcados = [v for v in valores if strip_footnote_marks(v) != v]
        # Exceção, não regra: se quase todo valor tem a "marca", ela é parte do nome.
        if marcados and len(marcados) <= len(valores) / 2:
            cols.append(c)
    if cols:
        exemplo = next(v for v in _uteis(ctx, cols[0]) if strip_footnote_marks(v) != v)
        yield Suggestion(
            "notas_de_rodape",
            ({"op": "strip_footnotes", "cols": cols},),
            0.75,
            f"{_lista(cols)}: marca de nota no fim do nome "
            f"('{exemplo}' é '{strip_footnote_marks(exemplo)}').",
            tuple(cols),
            order=LIMPEZA,
        )


_INTEIRO = re.compile(r"-?(0|[1-9]\d*)")


def _so_inteiros(ctx: Contexto, col: str) -> bool:
    valores = _uteis(ctx, col)
    return bool(valores) and all(_INTEIRO.fullmatch(v) for v in valores)


def _decimal_da_tabela(ctx: Contexto, cols: list[str]) -> str:
    """Separador decimal decidido pela tabela inteira, não coluna a coluna:
    se nenhuma coluna tem vírgula e alguma tem ponto que só pode ser decimal
    ('0.5', '8725.3480'), a fonte publica com ponto, e '104.000' também é
    cento e quatro. Senão, ``auto`` (cada coluna decide)."""
    valores = {c: ctx.valores(c) for c in cols}
    if any("," in v for vs in valores.values() for v in vs):
        return "auto"
    return "." if any(decimal_provavel(vs) == "." for vs in valores.values()) else "auto"


@rule
def decimal_br(ctx: Contexto) -> Iterator[Suggestion]:
    cols = [c for c, _ in _do_tipo(ctx, "numero") if not _so_inteiros(ctx, c)]
    if not cols:
        return
    decimal = _decimal_da_tabela(ctx, cols)
    motivo = "número escrito como texto"
    if decimal == ".":
        motivo += ", com ponto decimal (nenhuma coluna da tabela usa vírgula)"
    taxa = min(ctx.perfil(c).type_rate for c in cols)
    passo: dict = {"op": "parse_decimal_br", "cols": cols, "decimal": decimal}
    if _debito_credito(ctx, cols):
        passo["debit_negative"] = True
        motivo += ", com D (débito) negativo"
    yield Suggestion(
        "decimal_br",
        (passo,),
        taxa,
        f"{_lista(cols)}: {motivo}{_exemplo(ctx, cols[0])}.",
        tuple(cols),
        order=CONVERSAO,
    )


_DINHEIRO = re.compile(r"\b(valor|vlr|vl|preco|custo|receita|despesa|saldo|montante|r)\b")


@rule
def inteiro(ctx: Contexto) -> Iterator[Suggestion]:
    """Contagem escrita como texto ('1532') ou guardada como decimal
    (1532.0): vira número inteiro."""
    # Mês e ano que a regra mes_e_ano junta numa data não viram inteiro.
    texto = [
        c for c, _ in _do_tipo(ctx, "numero") if _so_inteiros(ctx, c) and c not in (_mes_e_ano(ctx) or ())
    ]
    decimais = [
        c
        for c, t in ctx.total.schema.items()
        if t in (pl.Float32, pl.Float64)
        and not _DINHEIRO.search(_nome(c))
        and (s := ctx.total[c].drop_nulls()).len() > 0
        and bool((s == s.round(0)).all())
        and bool((s.abs() < 2**53).all())
    ]
    cols = texto + decimais
    if cols:
        yield Suggestion(
            "inteiro",
            ({"op": "cast", "types": dict.fromkeys(cols, "int")},),
            0.8 if texto else 0.65,
            f"{_lista(cols)}: só números inteiros{_exemplo(ctx, cols[0]) if texto else ''}.",
            tuple(cols),
            order=CONVERSAO,
        )


_SENTINELAS = {-99999.0, -9999.0, -999.0, 9999.0, 99999.0}


@rule
def sentinela(ctx: Contexto) -> Iterator[Suggestion]:
    """Valor que a fonte usa para "sem medição" ('-9999' do INMET, '9999'):
    fora da faixa dos outros, vira vazio antes de converter o número."""
    por_valor: dict[str, list[str]] = {}
    for c in ctx.texto:
        coluna = ctx.total[c].drop_nulls().str.strip_chars()
        # Filtro barato antes de converter a coluna inteira.
        if not coluna.str.contains(r"^-?9{3,5}([.,]0+)?$").any():
            continue
        distintos = [v for v in coluna.unique().to_list() if v]
        decimal = decimal_provavel(distintos)
        numeros = {v: parse_number_br(v, decimal=decimal) for v in distintos}
        candidatos = [v for v, n in numeros.items() if n in _SENTINELAS]
        if not candidatos or any(n is None for n in numeros.values()):
            continue
        outros = [abs(n) for w, n in numeros.items() if w not in candidatos and n is not None]
        for v in candidatos:
            if outros and max(outros) < abs(numeros[v]):
                por_valor.setdefault(v, []).append(c)
    for valor, cols in por_valor.items():
        yield Suggestion(
            "sentinela",
            ({"op": "replace", "cols": cols, "old": valor, "new": None, "whole": True},),
            0.85,
            f"{_lista(cols)}: '{valor}' marca medição que falta (fica fora da faixa dos outros valores) "
            "e viraria número.",
            tuple(cols),
            order=LIMPEZA,
        )


_NOME_ANO = re.compile(r"^(ano|year|exercicio)( .*)?$")
_NOME_MES = re.compile(r"^(mes|month)( .*)?$")


def _mes_e_ano(ctx: Contexto) -> tuple[str, str] | None:
    """As colunas de mês e de ano, quando há exatamente uma de cada."""
    anos = [
        c
        for c in ctx.total.columns
        if _NOME_ANO.match(_nome(c)) and _so_valores(ctx, c, lambda v: bool(_ANO.fullmatch(v)))
    ]
    meses = [
        c
        for c in ctx.total.columns
        if _NOME_MES.match(_nome(c))
        and _so_valores(
            ctx, c, lambda v: (v.isdigit() and 1 <= int(v) <= 12) or normalize_key(v).rstrip(".") in MESES
        )
    ]
    return (meses[0], anos[0]) if len(anos) == 1 and len(meses) == 1 else None


@rule
def mes_e_ano(ctx: Contexto) -> Iterator[Suggestion]:
    """Mês e ano em colunas separadas viram uma data (o dia 1 do mês)."""
    if (par := _mes_e_ano(ctx)) is None:
        return
    mes, ano = par
    into = _nome_livre("data", ctx.total.columns)
    yield Suggestion(
        "mes_e_ano",
        (
            {"op": "merge_cols", "cols": [mes, ano], "separator": "/", "into": into},
            {"op": "parse_month_year", "cols": [into]},
        ),
        0.8,
        f"'{mes}' e '{ano}' viram uma data só, '{into}' (dia 1 do mês): é o que o Power BI usa "
        "para filtrar e ordenar por período.",
        (mes, ano),
        order=CONVERSAO,
    )


def _so_valores(ctx: Contexto, col: str, teste) -> bool:
    s = ctx.total[col].drop_nulls()
    valores = [
        str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip() for v in s.to_list()
    ]
    valores = [v for v in valores if v]
    return bool(valores) and sum(map(teste, valores)) / len(valores) >= TAXA


_TRAVESSAO = chr(0x2013)
_CODIGO_ROTULO = re.compile(r"(\d+(?:\.\d+)*)(\. | - | " + _TRAVESSAO + r" )(\S.*)")


@rule
def codigo_e_rotulo(ctx: Contexto) -> Iterator[Suggestion]:
    """Código e nome na mesma célula ('1. Automóvel', '3.1 - Pessoal'): duas
    colunas, uma para filtrar pelo código e outra para ler."""
    for c in ctx.texto:
        if ctx.perfil(c).inferred_type != "texto":
            continue
        valores = _uteis(ctx, c)
        casam = [m for v in valores if (m := _CODIGO_ROTULO.fullmatch(v))]
        if len(valores) < 2 or len(casam) / len(valores) < TAXA:
            continue
        separador = Counter(m.group(2) for m in casam).most_common(1)[0][0]
        into = [_nome_livre(f"{c}_codigo", ctx.total.columns), _nome_livre(f"{c}_nome", ctx.total.columns)]
        yield Suggestion(
            "codigo_e_rotulo",
            ({"op": "split_col", "col": c, "separator": separador, "into": into},),
            0.75,
            f"'{c}': código e nome na mesma célula{_exemplo(ctx, c)}; separados, dá para filtrar "
            "pelo código.",
            (c,),
            order=CONVERSAO,
        )


@rule
def data(ctx: Contexto) -> Iterator[Suggestion]:
    """Datas; com 8 dígitos, a ordem (AAAAMMDD ou DDMMAAAA) que serve para
    todos os valores da coluna."""
    por_ordem: dict[str, list[tuple[str, float]]] = {}
    for c, taxa in _do_tipo(ctx, "data"):
        oito = [v for v in _uteis(ctx, c) if re.fullmatch(r"\d{8}", v)]
        ordem = "auto"
        if oito:
            ymd = all(parse_date_br(v, eight_digits="ymd", accept_excel_serial=False) for v in oito)
            dmy = all(parse_date_br(v, eight_digits="dmy", accept_excel_serial=False) for v in oito)
            ordem = "ymd" if ymd and not dmy else "dmy" if dmy and not ymd else "auto"
        por_ordem.setdefault(ordem, []).append((c, taxa))
    for ordem, achadas in por_ordem.items():
        cols = [c for c, _ in achadas]
        passo = {"op": "parse_date_br", "cols": cols}
        if ordem != "auto":
            passo["eight_digits"] = ordem
        detalhe = {"ymd": " em AAAAMMDD", "dmy": " em DDMMAAAA"}.get(ordem, "")
        yield Suggestion(
            "data",
            (passo,),
            min(t for _, t in achadas),
            f"{_lista(cols)}: data escrita como texto{detalhe}{_exemplo(ctx, cols[0])}.",
            tuple(cols),
            order=CONVERSAO,
        )


@rule
def percentual(ctx: Contexto) -> Iterator[Suggestion]:
    yield from _conversao(ctx, "percentual", "percentual", "parse_percent", "percentual escrito como texto")


@rule
def sinais_ibge(ctx: Contexto) -> Iterator[Suggestion]:
    """Coluna de valor com '-', '..', '...' ou 'X': o '-' é zero, os outros
    não podem virar zero nem sumir em silêncio."""
    cols, virgula = [], False
    for c in ctx.texto:
        valores = ctx.valores(c)
        sinais = [v for v in valores if v in SINAIS_IBGE]
        numeros = [v for v in valores if v not in SINAIS_IBGE]
        if not sinais or not numeros:
            continue
        convertidos = sum(parse_number_br(v, decimal=decimal_provavel(numeros)) is not None for v in numeros)
        if convertidos / len(numeros) >= TAXA:
            cols.append(c)
            # Vírgula decimal só com evidência; sem ela, o padrão do IBGE (ponto).
            virgula = virgula or (any("," in v for v in numeros) and decimal_provavel(numeros) == ",")
    if not cols:
        return
    passo = {"op": "parse_ibge_value", "cols": cols}
    if virgula:
        passo["decimal"] = ","
    yield Suggestion(
        "sinais_ibge",
        (passo,),
        0.9,
        f"{_lista(cols)}: números com os sinais do IBGE ('-', '..', '...', 'X'). O '-' vira zero; "
        "os outros ficam nulos, com a situação numa coluna ao lado.",
        tuple(cols),
        order=CONVERSAO,
    )


# ---------------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------------


@rule
def coluna_vazia(ctx: Contexto) -> Iterator[Suggestion]:
    if ctx.total.height == 0:
        return
    vazias = [c for c in ctx.total.columns if all(is_null_token(v) for v in ctx.total[c].to_list())]
    if vazias and len(vazias) < ctx.total.width:
        yield Suggestion(
            "coluna_vazia",
            ({"op": "drop_cols", "cols": vazias},),
            0.95,
            f"{_lista(vazias)}: coluna sem nenhum valor.",
            tuple(vazias),
            order=LIMPEZA,
        )


@rule
def espacos(ctx: Contexto) -> Iterator[Suggestion]:
    cols, juntar = [], False
    for c in ctx.texto:
        sujos = [v for v in ctx.df[c].to_list() if v is not None and normalize_spaces(v) != v]
        if sujos:
            cols.append(c)
            juntar = juntar or any("  " in v.strip() or ESPACOS_ESPECIAIS.search(v.strip()) for v in sujos)
    if cols:
        passo = {"op": "trim", "cols": cols}
        if juntar:
            passo["collapse_spaces"] = True
        yield Suggestion(
            "espacos",
            (passo,),
            0.9,
            f"{_lista(cols)}: espaço nas pontas, repetido ou invisível (não aparece na tela, mas "
            "atrapalha filtro e junção).",
            tuple(cols),
            order=LIMPEZA,
        )


@rule
def mojibake(ctx: Contexto) -> Iterator[Suggestion]:
    cols = [c for c in ctx.texto if any(fix_mojibake(v) != v for v in ctx.valores(c))]
    if cols:
        errado = next(v for v in ctx.valores(cols[0]) if fix_mojibake(v) != v)
        yield Suggestion(
            "mojibake",
            ({"op": "fix_mojibake", "cols": cols},),
            0.9,
            f"{_lista(cols)}: acento estragado ('{errado}' é '{fix_mojibake(errado)}').",
            tuple(cols),
            order=LIMPEZA,
        )


@rule
def variacao_categoria(ctx: Contexto) -> Iterator[Suggestion]:
    """A mesma categoria escrita de jeitos diferentes ('São Paulo', 'SAO
    PAULO', 'são paulo'): padroniza a caixa e, se for o caso, o acento."""
    por_modo: dict[str, list[str]] = {}
    sem_acento: list[str] = []
    for c in ctx.texto:
        if ctx.perfil(c).inferred_type != "texto":
            continue
        valores = _uteis(ctx, c)
        distintos = set(valores)
        if len(distintos) < 2 or len(distintos) > max(50, len(valores) // 2):
            continue
        caixa = {v.casefold() for v in distintos}
        chave = {normalize_key(v) for v in distintos}
        if len(chave) == len(distintos):
            continue
        maiusculas = sum(v.isupper() for v in valores) > len(valores) / 2
        por_modo.setdefault("upper" if maiusculas else "title", []).append(c)
        if len(chave) < len(caixa):
            sem_acento.append(c)
    for modo, cols in por_modo.items():
        passos = [{"op": "case", "cols": cols, "mode": modo}]
        acento = [c for c in cols if c in sem_acento]
        if acento:
            passos.append({"op": "remove_accents", "cols": acento})
        yield Suggestion(
            "variacao_categoria",
            tuple(passos),
            0.75,
            f"{_lista(cols)}: a mesma categoria aparece com caixa{' e acento' if acento else ''} "
            "diferentes e conta como valores distintos.",
            tuple(cols),
            order=LIMPEZA,
        )


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------


_TIPOS_PESSOA = {"f", "j", "pf", "pj", "fisica", "juridica", "pessoa fisica", "pessoa juridica"}


def _coluna_tipo_pessoa(ctx: Contexto) -> str | None:
    for c in ctx.texto:
        nome = normalize_key(c)
        if "tipo" in nome and "pessoa" in nome:
            return c
    for c in ctx.texto:
        valores = {normalize_key(v) for v in _uteis(ctx, c)}
        if valores and valores <= _TIPOS_PESSOA:
            return c
    return None


@rule
def documento(ctx: Contexto) -> Iterator[Suggestion]:
    """CPF e CNPJ com máscara misturada ou zeros perdidos no Excel."""
    for c in ctx.texto:
        valores = _uteis(ctx, c)
        if not valores:
            continue
        cpfs = [clean_cpf(v) for v in valores]
        cnpjs = [clean_cnpj(v) for v in valores]
        taxa_cpf = sum(cpf_is_valid(x) for x in cpfs) / len(valores)
        taxa_cnpj = sum(cnpj_is_valid(x) for x in cnpjs) / len(valores)
        if taxa_cpf >= 0.8:
            if any(x != v for x, v in zip(cpfs, valores, strict=True)):
                yield _documento(ctx, c, "clean_cpf", "CPF", taxa_cpf)
        elif taxa_cnpj >= 0.8:
            if any(x != v for x, v in zip(cnpjs, valores, strict=True)):
                yield _documento(ctx, c, "clean_cnpj", "CNPJ", taxa_cnpj)
        elif taxa_cpf + taxa_cnpj >= 0.8 and min(taxa_cpf, taxa_cnpj) >= 0.05:
            passo = {"op": "clean_cpf_cnpj", "col": c}
            if (tipo := _coluna_tipo_pessoa(ctx)) is not None and tipo != c:
                passo["person_type_col"] = tipo
            yield Suggestion(
                "documento",
                (passo,),
                taxa_cpf + taxa_cnpj,
                f"'{c}': CPF e CNPJ na mesma coluna, com máscara ou zeros à esquerda perdidos"
                f"{_exemplo(ctx, c)}.",
                (c,),
                order=DOCUMENTO,
            )


def _documento(ctx: Contexto, col: str, op: str, nome: str, taxa: float) -> Suggestion:
    return Suggestion(
        "documento",
        ({"op": op, "cols": [col]},),
        taxa,
        f"'{col}': {nome} com máscara misturada ou zeros à esquerda perdidos{_exemplo(ctx, col)}.",
        (col,),
        order=DOCUMENTO,
    )


@rule
def cep(ctx: Contexto) -> Iterator[Suggestion]:
    """CEP que perdeu o zero (7 dígitos, como os de São Paulo depois do Excel)."""
    cols, exemplo = [], ""
    for c in ctx.texto:
        valores = _uteis(ctx, c)
        if not valores:
            continue
        oito = [v for v in valores if re.fullmatch(r"\d{5}-?\d{3}", v)]
        sete = [v for v in valores if re.fullmatch(r"\d{7}", v)]
        # Sem 'cep' no nome, só o hífen distingue CEP de data em DDMMAAAA.
        com_hifen = [v for v in valores if re.fullmatch(r"\d{5}-\d{3}", v)]
        cara_de_cep = "cep" in normalize_key(c) or len(com_hifen) / len(valores) >= 0.3
        if sete and cara_de_cep and (len(oito) + len(sete)) / len(valores) >= TAXA:
            cols.append(c)
            exemplo = exemplo or sete[0]
    if cols:
        yield Suggestion(
            "cep",
            ({"op": "clean_cep", "cols": cols},),
            0.85,
            f"{_lista(cols)}: CEP com 7 dígitos, sem o zero do começo "
            f"('{exemplo}' é '{clean_cep(exemplo)}').",
            tuple(cols),
            order=DOCUMENTO,
        )


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------


@rule
def codigo_zero_esquerda(ctx: Contexto) -> Iterator[Suggestion]:
    """Código com zero à esquerda (IBGE, conta contábil, matrícula): não
    pode virar número. E código que já perdeu o zero ao passar pelo Excel."""
    com_zero, perdidos = [], []
    for c in ctx.texto:
        valores = _uteis(ctx, c)
        if not valores or not all(v.isdigit() for v in valores):
            continue
        if ctx.perfil(c).inferred_type == "codigo":
            com_zero.append(c)
            continue
        tamanhos = {len(v) for v in valores}
        nome = _nome(c)
        if "cep" in nome.split():
            continue  # a regra de CEP cuida do zero perdido
        if _NOME_DE_CODIGO.search(nome) and len(tamanhos) > 1 and max(tamanhos) - min(tamanhos) <= 2:
            perdidos.append(c)
    if com_zero:
        yield Suggestion(
            "codigo_zero_esquerda",
            (),
            0.9,
            f"{_lista(com_zero)}: código com zero à esquerda{_exemplo(ctx, com_zero[0])}. Mantenha como "
            "texto: convertido para número, perde o zero e deixa de casar com outras tabelas.",
            tuple(com_zero),
            kind="aviso",
            order=LIMPEZA,
        )
    if perdidos:
        yield Suggestion(
            "codigo_zero_esquerda",
            (),
            0.7,
            f"{_lista(perdidos)}: código com tamanhos diferentes; talvez tenha perdido zeros à esquerda ao "
            "passar pelo Excel. Confira na fonte.",
            tuple(perdidos),
            kind="aviso",
            order=LIMPEZA,
        )


# ---------------------------------------------------------------------------
# Forma da tabela
# ---------------------------------------------------------------------------


def _linhas_vazias(df: pl.DataFrame) -> pl.Series:
    """Máscara das linhas em que toda célula é nula ou só espaço."""
    if df.width == 0:
        return pl.Series([], dtype=pl.Boolean)
    return df.select(
        pl.all_horizontal(
            pl.col(c).is_null() | (pl.col(c).cast(pl.String).str.strip_chars() == "") for c in df.columns
        )
    ).to_series()


@rule
def linhas_vazias(ctx: Contexto) -> Iterator[Suggestion]:
    if ctx.total.height == 0:
        return
    vazias = int(_linhas_vazias(ctx.total).sum())
    if vazias and vazias < ctx.total.height:
        yield Suggestion(
            "linhas_vazias",
            ({"op": "drop_empty_rows"},),
            0.9,
            f"{vazias} {'linha vazia' if vazias == 1 else 'linhas vazias'} no meio dos dados.",
            order=LIMPEZA,
        )


@rule
def duplicadas(ctx: Contexto) -> Iterator[Suggestion]:
    if ctx.total.height < 2:
        return
    # Linha vazia repetida é assunto da regra linhas_vazias.
    cheias = ctx.total.filter(~_linhas_vazias(ctx.total))
    repetidas = cheias.height - cheias.n_unique()
    if repetidas:
        yield Suggestion(
            "duplicadas",
            ({"op": "dedupe"},),
            0.8,
            f"{repetidas} {'linha repetida' if repetidas == 1 else 'linhas repetidas'} "
            "(todas as colunas iguais a outra linha).",
            order=FORMA,
        )


_REGIOES = {
    "norte",
    "nordeste",
    "sudeste",
    "sul",
    "centro oeste",
    "centro-oeste",
    "norte/nordeste",
    "norte nordeste",
    "centro sul",
    "centro-sul",
    "brasil",
    "total brasil",
    "brasil total",
}
_UFS = {normalize_key(s) for s in UFS} | {normalize_key(n) for n in UFS.values()}


def _regiao(valor: str) -> bool:
    chave = re.sub(r"^regiao\s+", "", normalize_key(valor).strip())
    return chave in _REGIOES


@rule
def linhas_de_regiao(ctx: Contexto) -> Iterator[Suggestion]:
    """Coluna de UF com linhas de região ou do Brasil no meio (como o IBGE,
    a Conab e o INEP publicam): elas somam as UFs e duplicariam o total."""
    for c in ctx.texto:
        if ctx.total[c].n_unique() > 200:  # coluna de UF tem umas 40 linhas distintas, não milhares
            continue
        distintos = [v for v in ctx.total[c].drop_nulls().unique(maintain_order=True).to_list() if v.strip()]
        ufs = sum(normalize_key(v).strip() in _UFS for v in distintos)
        agregados = [v for v in distintos if _regiao(v)]
        if ufs >= 10 and agregados:
            yield Suggestion(
                "linhas_de_regiao",
                ({"op": "drop_rows_where", "col": c, "match": "in", "value": agregados},),
                0.85,
                f"'{c}': {len(agregados)} {'linha' if len(agregados) == 1 else 'linhas'} de região ou do "
                f"Brasil ({_lista(agregados)}) entre as UFs; elas somam as UFs e dobrariam o total.",
                (c,),
                order=LIMPEZA,
            )


_NOMES_DE_PERIODO = re.compile(
    r"\b(ano|mes|data|periodo|competencia|referencia|safra|exercicio|trimestre|semestre|uf|estado|"
    r"municipio|pais)\b"
)


@rule
def coluna_constante(ctx: Contexto) -> Iterator[Suggestion]:
    """Coluna com o mesmo valor em todas as linhas não informa nada. Ano,
    UF e afins ficam de fora: são o que diferencia um arquivo do outro
    quando os meses são empilhados."""
    if ctx.total.height < 10:
        return
    cols = [
        c
        for c in ctx.total.columns
        if ctx.total[c].null_count() == 0
        and ctx.total[c].n_unique() == 1
        and not _NOMES_DE_PERIODO.search(_nome(c))
        and ctx.total.schema[c] == pl.String
    ]
    if cols and len(cols) < ctx.total.width:
        yield Suggestion(
            "coluna_constante",
            ({"op": "drop_cols", "cols": cols},),
            0.6,
            f"{_lista(cols)}: o mesmo valor em todas as linhas ('{ctx.total[cols[0]][0]}').",
            tuple(cols),
            # Depois de despivotar e das conversões, que podem citar a coluna.
            order=FORMA + 5,
        )


# Tabela larga: o que vira linha ------------------------------------------------

_ANO = re.compile(r"(19|20)\d{2}")
_SAFRA = re.compile(r"(19|20)\d{2}\s*/\s*((19|20)?\d{2})")
_DATA_ISO = re.compile(r"(19|20)\d{2}-[01]\d-[0-3]\d( 00:00:00(\.0+)?)?|[0-3]\d/[01]\d/(19|20)\d{2}")
_TRIMESTRE = re.compile(r"(([1-4])\s*(o|°)?\s*tri(m(estre)?)?\.?|t([1-4]))(\s*[/ -]?\s*((19|20)?\d{2}))?")
_VARIAVEL = {"mes": "mes", "ano": "ano", "safra": "safra", "data": "data", "trimestre": "trimestre"}


def _periodo(nome: str) -> str | None:
    """Tipo de período de um nome de coluna: 'jan/2024' e 'Março' são mês,
    '2023' é ano, '1976/77' é safra, '1997-01-01 00:00:00' é data (cabeçalho
    de datas do Excel) e '1º trim' é trimestre."""
    # '2023/24 (1)', '2025*': a nota de rodapé não muda o período.
    chave = (strip_footnote_marks(normalize_key(nome)) or "").strip()
    if _SAFRA.fullmatch(chave):
        return "safra"
    if _ANO.fullmatch(chave):
        return "ano"
    if _DATA_ISO.fullmatch(chave):
        return "data"
    if _TRIMESTRE.fullmatch(chave):
        return "trimestre"
    if chave.rstrip(".") in MESES or parse_month_year(nome) is not None:
        return "mes"
    return None


def _periodos(cols: list[str]) -> tuple[str, list[str]] | None:
    """O tipo de período mais comum e as colunas dele (pelo menos 3)."""
    tipos = {c: _periodo(c) for c in cols}
    contagem = Counter(t for t in tipos.values() if t)
    if not contagem:
        return None
    tipo, n = contagem.most_common(1)[0]
    return (tipo, [c for c in cols if tipos[c] == tipo]) if n >= 3 else None


def _e_total(nome: str) -> bool:
    palavras = _nome(nome).split()
    return bool(palavras) and (palavras[0] == "total" or palavras[-1] == "total")


def _numerica(ctx: Contexto, col: str) -> bool:
    if ctx.total.schema[col].is_numeric():
        return True
    if ctx.total.schema[col] != pl.String or col not in ctx.df.columns:
        return False
    valores = _uteis(ctx, col)
    if not valores:
        return False
    decimal = decimal_provavel(valores)
    numeros = sum(v in SINAIS_IBGE or parse_number_br(v, decimal=decimal) is not None for v in valores)
    return numeros / len(valores) >= TAXA


def _numeros(ctx: Contexto, col: str) -> list[float | None]:
    """A coluna inteira como número; '-' do IBGE é zero."""
    s = ctx.total[col]
    if s.dtype.is_numeric():
        return [None if v is None else float(v) for v in s.to_list()]
    valores = s.to_list()
    decimal = decimal_provavel(valores)
    return [
        0.0 if isinstance(v, str) and v.strip() == "-" else parse_number_br(v, decimal=decimal)
        for v in valores
    ]


def _nome_livre(nome: str, existentes: list[str]) -> str:
    novo, i = nome, 2
    while novo in existentes:
        novo, i = f"{nome}_{i}", i + 1
    return novo


def _despivotar(
    regra: str,
    valores: list[str],
    totais: list[str],
    ctx: Contexto,
    variavel: str,
    motivo: str,
    confianca: float,
) -> Suggestion:
    """Tira as colunas de total (são a soma das outras) e despivota."""
    fora = set(valores) | set(totais)
    index = [c for c in ctx.total.columns if c not in fora]
    passos: list[dict] = []
    if totais:
        passos.append({"op": "drop_cols", "cols": totais})
        motivo += f" A coluna {_lista(totais)} sai antes: é a soma das outras."
    passos.append(
        {
            "op": "unpivot",
            "index": index,
            "variable_name": _nome_livre(variavel, index),
            "value_name": _nome_livre("valor", index),
        }
    )
    return Suggestion(regra, tuple(passos), confianca, motivo, tuple(valores), order=FORMA)


@rule
def meses_lado_a_lado(ctx: Contexto) -> Iterator[Suggestion]:
    """Períodos lado a lado (meses, anos, safras, datas, trimestres): uma
    linha por período."""
    achado = _periodos(ctx.total.columns)
    if not achado:
        return
    tipo, periodos = achado
    totais = [c for c in ctx.total.columns if c not in periodos and _e_total(c)]
    yield _despivotar(
        "meses_lado_a_lado",
        periodos,
        totais,
        ctx,
        _VARIAVEL[tipo],
        f"{len(periodos)} períodos em colunas ({_lista(periodos)}): "
        "uma linha por período facilita filtro, gráfico e soma.",
        0.8,
    )


def _radical(nome: str) -> tuple[str, str] | None:
    """'1º Decêndio' -> ('decendio', '1'); None sem número ou sem palavra."""
    palavras = _nome(nome).replace("º", "o").replace("ª", "a").split()
    numeros = [p for p in palavras if re.fullmatch(r"\d{1,2}(o|a)?", p)]
    resto = [p for p in palavras if p not in numeros]
    if len(numeros) != 1 or not resto:
        return None
    return " ".join(resto), numeros[0]


@rule
def series_lado_a_lado(ctx: Contexto) -> Iterator[Suggestion]:
    """Colunas numeradas da mesma coisa ('1º Decêndio', '2º Decêndio',
    '3º Decêndio'; 'Parcela 1', 'Parcela 2'…): uma linha por número."""
    if _periodos(ctx.total.columns):
        return
    grupos: dict[str, list[str]] = {}
    for c in ctx.total.columns:
        if (r := _radical(c)) and _numerica(ctx, c):
            grupos.setdefault(r[0], []).append(c)
    for radical, cols in grupos.items():
        if len(cols) < 3:
            continue
        totais = [c for c in ctx.total.columns if c not in cols and _e_total(c)]
        yield _despivotar(
            "series_lado_a_lado",
            cols,
            totais,
            ctx,
            radical.replace(" ", "_"),
            f"{len(cols)} colunas numeradas de '{radical}' ({_lista(cols)}): uma linha por número.",
            0.75,
        )


def _soma_bate(total: list[float | None], partes: list[list[float | None]]) -> bool:
    linhas = [(t, sum(p[i] or 0.0 for p in partes)) for i, t in enumerate(total) if t is not None]
    if len(linhas) < 2:
        return False
    batem = sum(abs(t - s) <= max(0.01, abs(t) * 0.001) for t, s in linhas)
    return batem / len(linhas) >= TAXA


@rule
def categorias_com_total(ctx: Contexto) -> Iterator[Suggestion]:
    """Coluna de total que é a soma de outras colunas: as outras são
    categorias da mesma medida (tipos de veículo, dependência
    administrativa…) e cabem numa coluna só."""
    if not any(map(_e_total, ctx.total.columns)) or _periodos(ctx.total.columns) or ctx.total.height < 2:
        return
    numericas = [c for c in ctx.total.columns if not _e_total(c) and _numerica(ctx, c)]
    totais, partes = [], []
    for t in ctx.total.columns:
        if not _e_total(t) or not _numerica(ctx, t):
            continue
        prefixo = " ".join(p for p in _nome(t).split() if p != "total")
        candidatas = [c for c in numericas if c not in partes and _nome(c).startswith(prefixo)]
        if len(candidatas) >= 2 and _soma_bate(_numeros(ctx, t), [_numeros(ctx, c) for c in candidatas]):
            totais.append(t)
            partes += candidatas
    if totais:
        yield _despivotar(
            "categorias_com_total",
            partes,
            totais,
            ctx,
            "categoria",
            f"{_lista(partes)}: categorias da mesma medida, somadas em {_lista(totais)}. "
            "Uma linha por categoria.",
            0.75,
        )


@rule
def niveis_de_cabecalho(ctx: Contexto) -> Iterator[Suggestion]:
    """Cabeçalho em vários níveis ('Matrícula_Pré-escolar_Federal',
    'Matrícula_Pré-escolar_Estadual'): as colunas do mesmo grupo de cima são
    categorias da mesma medida."""
    juntar = next(
        (
            p.get("separator") or "_"
            for p in reversed(ctx.passos)
            if p.get("op") == "header_rows" and p.get("n", 1) > 1
        ),
        None,
    )
    if juntar is None or _periodos(ctx.total.columns) or any(_e_total(c) for c in ctx.total.columns):
        return
    grupos: dict[str, list[str]] = {}
    for c in ctx.total.columns:
        if juntar in c and _numerica(ctx, c):
            grupos.setdefault(c.rsplit(juntar, 1)[0], []).append(c)
    grupos = {g: cols for g, cols in grupos.items() if len(cols) >= 2}
    if len(grupos) == 1:
        grupo, cols = next(iter(grupos.items()))
        yield _despivotar(
            "niveis_de_cabecalho",
            cols,
            [],
            ctx,
            "categoria",
            f"{_lista(cols)}: categorias de '{grupo.replace(juntar, ' / ')}' no cabeçalho de cima. "
            "Uma linha por categoria.",
            0.7,
        )


# ---------------------------------------------------------------------------
# Verificações (F2.F2): o que vale hoje passa a ser conferido no próximo arquivo
# ---------------------------------------------------------------------------


def _ja_verificadas(ctx: Contexto, check: str) -> set[str]:
    return {
        c
        for p in ctx.passos
        if p.get("op") == "assert" and p.get("check") == check
        for c in p.get("cols", [])
    }


@rule
def verificar_preenchidas(ctx: Contexto) -> Iterator[Suggestion]:
    """Colunas 100% preenchidas hoje viram ``assert not_null``: se o arquivo
    do mês seguinte vier com buraco nelas, a receita avisa em vez de seguir."""
    if not ctx.passos or ctx.total.height == 0:
        return
    ja = _ja_verificadas(ctx, "not_null")
    vazias = ctx.total.select(
        (pl.col(c).is_null() | (pl.col(c).cast(pl.String).str.strip_chars() == "")).any().alias(c)
        for c in ctx.total.columns
    ).row(0)
    cols = [
        c for c, tem_vazia in zip(ctx.total.columns, vazias, strict=True) if not tem_vazia and c not in ja
    ]
    if cols:
        yield Suggestion(
            "verificar_preenchidas",
            ({"op": "assert", "check": "not_null", "cols": cols},),
            0.7,
            f"{_lista(cols)}: nenhuma célula vazia hoje. Verificar isso faz a receita parar, com aviso, "
            "se o arquivo do mês seguinte vier com buraco.",
            tuple(cols),
            order=VERIFICACAO,
        )


@rule
def verificar_unicos(ctx: Contexto) -> Iterator[Suggestion]:
    """Código ou documento sem repetição (CPF, CNPJ, código IBGE, ID) vira
    ``assert unique``: uma linha duplicada no próximo arquivo é avisada."""
    if not ctx.passos or ctx.total.height < 2:
        return
    ja = _ja_verificadas(ctx, "unique")
    for c in ctx.total.columns:
        if c in ja or not _NOME_DE_CODIGO.search(_nome(c)):
            continue
        s = ctx.total[c]
        if s.null_count() == 0 and s.n_unique() == ctx.total.height:
            yield Suggestion(
                "verificar_unicos",
                ({"op": "assert", "check": "unique", "cols": [c]},),
                0.7,
                f"'{c}' não se repete hoje. Verificar isso avisa se o próximo arquivo "
                "vier com linha duplicada.",
                (c,),
                order=VERIFICACAO,
            )

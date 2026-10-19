"""As regras de sugestão (F2.E2). Uma função por regra; o nome da função é o
nome da regra, que aparece na interface e na lista de rejeitadas.

Cada regra só olha colunas que ainda são texto: depois que o passo
sugerido entra na receita, a coluna muda de tipo (ou de forma) e a
sugestão some sozinha.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from wolfz.br.constants import MESES
from wolfz.br.datas import parse_date_br, parse_month_year
from wolfz.br.documentos import clean_cep, clean_cnpj, clean_cpf, cnpj_is_valid, cpf_is_valid
from wolfz.br.numeros import decimal_provavel, parse_number_br
from wolfz.core.suggest import CONVERSAO, DOCUMENTO, FORMA, LIMPEZA, Contexto, Suggestion, rule
from wolfz.core.text import fix_mojibake, is_null_token, normalize_key, normalize_spaces

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


@rule
def decimal_br(ctx: Contexto) -> Iterator[Suggestion]:
    yield from _conversao(
        ctx, "decimal_br", "numero", "parse_decimal_br", "número escrito como texto", decimal="auto"
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


@rule
def duplicadas(ctx: Contexto) -> Iterator[Suggestion]:
    if ctx.total.height < 2:
        return
    repetidas = ctx.total.height - ctx.total.n_unique()
    if repetidas:
        yield Suggestion(
            "duplicadas",
            ({"op": "dedupe"},),
            0.8,
            f"{repetidas} {'linha repetida' if repetidas == 1 else 'linhas repetidas'} "
            "(todas as colunas iguais a outra linha).",
            order=FORMA,
        )


def _e_mes(nome: str) -> bool:
    chave = normalize_key(nome).rstrip(".")
    return chave in MESES or parse_month_year(nome) is not None


@rule
def meses_lado_a_lado(ctx: Contexto) -> Iterator[Suggestion]:
    meses = [c for c in ctx.df.columns if _e_mes(c)]
    if len(meses) < 3:
        return
    index = [c for c in ctx.df.columns if c not in meses]
    yield Suggestion(
        "meses_lado_a_lado",
        ({"op": "unpivot", "index": index, "variable_name": "mes", "value_name": "valor"},),
        0.8,
        f"{len(meses)} meses em colunas ({_lista(meses)}): "
        "uma linha por mês facilita filtro, gráfico e soma.",
        tuple(meses),
        order=FORMA,
    )

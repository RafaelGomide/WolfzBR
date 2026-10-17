# ruff: noqa: E501  (código M: quebrar as linhas atrapalha mais do que ajuda)
"""Funções M auxiliares dos padrões brasileiros.

Cada uma traduz uma função de ``wolfz.br`` para Power Query M, que não tem
expressão regular: as regras são as mesmas, escritas com as funções de
texto do M. Toda conversão de texto para número passa a cultura
explicitamente ("pt-BR" ou "en-US"), para o resultado não depender da
máquina de quem faz o refresh.

A equivalência com o Polars é verificada nos exemplos de cada operação pelo
parser oficial de M (sintaxe) e, a cada release, à mão no Power BI Desktop
(F2.A7). Diferenças conhecidas ficam anotadas em cada função.
"""

from __future__ import annotations

from wolfz.br.booleanos import _FALSE, _TRUE
from wolfz.br.constants import MESES, NULL_TOKENS, UFS
from wolfz.core.text import normalize_key
from wolfz.export.m import m_list, m_text
from wolfz.ops.texto import ACENTOS, ESPACOS, INVISIVEIS


def _registro(mapa: dict[str, object]) -> str:
    """Record M a partir de um dict (chaves de texto qualquer)."""
    valores = "{" + ", ".join(m_text(v) if isinstance(v, str) else str(v) for v in mapa.values()) + "}"
    return f"Record.FromList({valores}, {m_list(mapa.keys())})"


SEM_ACENTO = f"""
(t as text) as text =>
    let mapa = {_registro(ACENTOS)}
    in Text.Combine(List.Transform(Text.ToList(t), each Record.FieldOrDefault(mapa, _, _)))
"""

# normalize_key: sem invisíveis, espaços colapsados, sem acento, minúsculo.
CHAVE = f"""
(v as any) as text =>
    if v = null then "" else
    let
        semInvisiveis = Text.Remove(Text.From(v, "en-US"), {m_list(INVISIVEIS)}),
        partes = List.Select(Text.SplitAny(semInvisiveis, {m_text(ESPACOS)}), each _ <> "")
    in
        Text.Lower(WolfzSemAcento(Text.Combine(partes, " ")))
"""

NULO = f"""
(v as any) as logical => v = null or List.Contains({m_list(sorted(NULL_TOKENS))}, WolfzChave(v))
"""

# parse_number_br. Diferença conhecida: número no padrão americano com
# decimal="," ('1,234.56') vira null no M; no Python vira 1234.56.
NUMERO_BR = """
(valor as any, tracoZero as logical, debitoNegativo as logical, cultura as text) as nullable number =>
    if valor is number then valor
    else if valor = null or valor is logical then null
    else
    let
        semMoeda = List.Accumulate(
            {"US$", "U$", "R$", "€", "BRL", "USD", "EUR", "$"},
            Text.From(valor),
            (texto, simbolo) => Text.Replace(texto, simbolo, " ")
        ),
        t0 = WolfzEspacos(semMoeda),
        ultimo = Text.Upper(Text.End(t0, 1)),
        temDC = Text.Length(t0) > 1 and (ultimo = "D" or ultimo = "C")
            and List.Contains({"0".."9"}, Text.End(Text.Trim(Text.Start(t0, Text.Length(t0) - 1)), 1)),
        t1 = if temDC then Text.Trim(Text.Start(t0, Text.Length(t0) - 1)) else t0,
        parenteses = Text.StartsWith(t1, "(") and Text.EndsWith(t1, ")"),
        t2 = if parenteses then Text.Trim(Text.Middle(t1, 1, Text.Length(t1) - 2)) else t1,
        menosNoFim = Text.Length(t2) > 1 and Text.EndsWith(t2, "-"),
        t3 = if menosNoFim then Text.Trim(Text.Start(t2, Text.Length(t2) - 1)) else t2,
        menosNoInicio = Text.Length(t3) > 1 and List.Contains({"-", "#(2013)", "#(2014)"}, Text.Start(t3, 1)),
        t4 = Text.Remove(
            if menosNoInicio then Text.Range(t3, 1) else if Text.StartsWith(t3, "+") then Text.Range(t3, 1) else t3,
            {" "}
        ),
        sinais = List.Count(List.Select(
            {temDC and ultimo = "D" and debitoNegativo, parenteses, menosNoFim, menosNoInicio}, each _ = true
        )),
        numero =
            if Text.Contains(Text.From(valor), "%") then null
            else if List.Contains({"-", "#(2013)", "#(2014)"}, t0) then (if tracoZero then 0 else null)
            else if WolfzNulo(t0) or t4 = "" then null
            else if List.ContainsAny(Text.ToList(t4), {"0".."9"}) = false then null
            else try Number.FromText(t4, cultura) otherwise null
    in
        if numero = null then null else if Number.IsOdd(sinais) then -numero else numero
"""

ESPACOS_M = f"""
(t as text) as text =>
    Text.Combine(
        List.Select(Text.SplitAny(Text.Remove(t, {m_list(INVISIVEIS)}), {m_text(ESPACOS)}), each _ <> ""), " "
    )
"""

PERCENTUAL = """
(v as any, pontos as logical) as nullable number =>
    if v = null then null
    else
    let t = WolfzEspacos(Text.From(v, "en-US"))
    in
        if Text.Contains(t, "%") then
            let n = WolfzNumeroBr(Text.Replace(t, "%", ""), false, false, "pt-BR")
            in if n = null then null else n / 100
        else
            let n = WolfzNumeroBr(t, false, false, "pt-BR")
            in if n = null then null else if pontos then n / 100 else n
"""

DATA_BR = f"""
(v as any, oito as text, pivo as number, serial as logical) as nullable date =>
    if v = null then null
    else if v is date then v
    else if v is datetime then Date.From(v)
    else if WolfzNulo(v) then null
    else
    let
        t0 = WolfzChave(v),
        posHora = Text.PositionOfAny(t0, {{" ", "t"}}, Occurrence.Last),
        t1 = if posHora > 0 and Text.Contains(Text.Range(t0, posHora), ":") then Text.Start(t0, posHora) else t0,
        // DDMMAAAA sem o zero do dia (passou pelo Excel como número): '1032021'.
        t = if oito <> "ymd" and Text.Length(t1) = 7 and digitos(t1) then "0" & t1 else t1,
        digitos = (s as text) as logical => Text.Length(s) > 0 and Text.Select(s, {{"0".."9"}}) = s,
        ano = (a as text) as number =>
            if Text.Length(a) = 4 then Number.From(a)
            else let yy = Number.From(a) in if yy < pivo then 2000 + yy else 1900 + yy,
        faz = (y as number, m as number, d as number) as nullable date =>
            if y < 1800 or y >= 9999 then null else try #date(y, m, d) otherwise null,
        meses = {_registro(MESES)},
        partes = Text.SplitAny(t, "/-."),
        extenso = List.Select(Text.SplitAny(Text.Replace(t, " de ", " "), " /-."), each _ <> ""),
        resultado =
            if List.Count(partes) = 3 and List.AllTrue(List.Transform(partes, digitos)) then
                if Text.Length(partes{{0}}) = 4 and Text.Length(partes{{1}}) <= 2 and Text.Length(partes{{2}}) <= 2
                then faz(Number.From(partes{{0}}), Number.From(partes{{1}}), Number.From(partes{{2}}))
                else if Text.Length(partes{{0}}) <= 2 and Text.Length(partes{{1}}) <= 2
                    and (Text.Length(partes{{2}}) = 4 or Text.Length(partes{{2}}) = 2)
                then faz(ano(partes{{2}}), Number.From(partes{{1}}), Number.From(partes{{0}}))
                else null
            else if List.Count(extenso) = 3 and digitos(extenso{{0}}) and Text.Length(extenso{{0}}) <= 2
                and not digitos(extenso{{1}}) and digitos(extenso{{2}})
                and (Text.Length(extenso{{2}}) = 4 or Text.Length(extenso{{2}}) = 2)
            then
                let m = Record.FieldOrDefault(meses, extenso{{1}}, null)
                in if m = null then null else faz(ano(extenso{{2}}), m, Number.From(extenso{{0}}))
            else if Text.Length(t) = 8 and digitos(t) then
                let
                    ymd = faz(Number.From(Text.Start(t, 4)), Number.From(Text.Middle(t, 4, 2)), Number.From(Text.End(t, 2))),
                    dmy = faz(Number.From(Text.End(t, 4)), Number.From(Text.Middle(t, 2, 2)), Number.From(Text.Start(t, 2)))
                in
                    if oito = "ymd" then ymd else if oito = "dmy" then dmy else if ymd <> null then ymd else dmy
            else if serial and Text.Length(t) >= 5 and digitos(Text.Start(t, 5))
                and (Text.Length(t) = 5 or (List.Contains({{".", ","}}, Text.Middle(t, 5, 1)) and digitos(Text.Range(t, 6))))
            then
                let n = Number.From(Text.Start(t, 5))
                in if n >= 20000 and n <= 80000 then Date.AddDays(#date(1899, 12, 30), n) else null
            else null
    in
        resultado
"""

MES_ANO = f"""
(v as any, pivo as number) as nullable date =>
    if v = null then null
    else if v is date then Date.StartOfMonth(v)
    else
    let
        k0 = WolfzChave(v),
        prefixo = List.First(
            List.Select({{"competencia", "comp.", "comp", "ref.", "ref", "mes"}}, each Text.StartsWith(k0, _)), ""
        ),
        k = Text.Trim(Text.TrimStart(Text.Trim(Text.Range(k0, Text.Length(prefixo))), ":")),
        digitos = (s as text) as logical => Text.Length(s) > 0 and Text.Select(s, {{"0".."9"}}) = s,
        ano = (a as text) as number =>
            if Text.Length(a) = 4 then Number.From(a)
            else let yy = Number.From(a) in if yy < pivo then 2000 + yy else 1900 + yy,
        meses = {_registro(MESES)},
        pos = Text.PositionOfAny(k, {{"0".."9"}}),
        nome = Text.Trim(Text.TrimEnd(Text.Trim(Text.TrimEnd(Text.Start(k, if pos < 0 then 0 else pos), "/-. ")), "de")),
        resto = if pos < 0 then "" else Text.Range(k, pos),
        partes = Text.SplitAny(k, "/-."),
        mesAno =
            if pos > 0 and Text.Length(nome) >= 3 and Text.Select(nome, {{"a".."z"}}) = nome
                and digitos(resto) and (Text.Length(resto) = 2 or Text.Length(resto) = 4)
            then {{Record.FieldOrDefault(meses, Text.TrimEnd(nome, "."), null), ano(resto)}}
            else if pos = 0 and List.Count(partes) = 2 and List.AllTrue(List.Transform(partes, digitos)) then
                if Text.Length(partes{{0}}) <= 2 and (Text.Length(partes{{1}}) = 2 or Text.Length(partes{{1}}) = 4)
                then {{Number.From(partes{{0}}), ano(partes{{1}})}}
                else if Text.Length(partes{{0}}) = 4 and Text.Length(partes{{1}}) = 2
                then {{Number.From(partes{{1}}), Number.From(partes{{0}})}}
                else {{null, null}}
            else if pos = 0 and Text.Length(k) = 6 and digitos(k) then
                {{Number.From(Text.End(k, 2)), Number.From(Text.Start(k, 4))}}
            else {{null, null}},
        mes = mesAno{{0}},
        a = mesAno{{1}}
    in
        if mes = null or a = null or mes < 1 or mes > 12 or a < 1800 or a >= 9999 then null else #date(a, mes, 1)
"""

BOOL = f"""
(v as any, vazioFalso as logical) as nullable logical =>
    if v is logical then v
    else
    let k = WolfzChave(v)
    in
        if k = "" then (if vazioFalso then false else null)
        else if List.Contains({m_list(sorted(_TRUE))}, k) then true
        else if List.Contains({m_list(sorted(_FALSE))}, k) then false
        else null
"""

# _prepare_id: tira '.0' de número lido como float; notação científica do
# Excel ('1,23457E+13') é irrecuperável e vira null.
PREP_ID = """
(v as any) as nullable text =>
    if v = null then null
    else if v is number then Number.ToText(v, "0", "en-US")
    else if WolfzNulo(v) then null
    else
    let
        t = WolfzEspacos(Text.From(v)),
        digitos = (s as text) as logical => Text.Length(s) > 0 and Text.Select(s, {"0".."9"}) = s,
        antesPonto = Text.BeforeDelimiter(t, "."),
        depoisPonto = Text.AfterDelimiter(t, "."),
        sufixoZero = Text.Contains(t, ".") and digitos(antesPonto) and Text.Length(depoisPonto) > 0
            and Text.Select(depoisPonto, {"0"}) = depoisPonto,
        mantissa = Text.BeforeDelimiter(Text.Upper(t), "E"),
        expoente = Text.AfterDelimiter(Text.Upper(t), "E"),
        cientifica = Text.Contains(Text.Upper(t), "E") and Text.Length(mantissa) >= 1
            and List.Contains({"0".."9"}, Text.Start(mantissa, 1))
            and (Text.Length(mantissa) = 1 or (List.Contains({".", ","}, Text.Middle(mantissa, 1, 1))
                and digitos(Text.Range(mantissa, 2))))
            and digitos(Text.TrimStart(expoente, {"+", "-"}))
    in
        if sufixoZero then antesPonto else if cientifica then null else t
"""

CPF = """
(v as any, completar as logical) as nullable text =>
    let s = WolfzPrepId(v)
    in
        if s = null then null
        else
        let
            semEspaco = Text.Remove(s, {" "}),
            compacto = Text.Remove(semEspaco, {".", "-"}),
            mascara = {"*", "x", "X"},
            mascarado = Text.Length(compacto) = 11
                and List.AllTrue(List.Transform(Text.ToList(Text.Start(compacto, 3)), each List.Contains(mascara, _)))
                and List.AllTrue(List.Transform(Text.ToList(Text.End(compacto, 2)), each List.Contains(mascara, _)))
                and Text.Select(Text.Middle(compacto, 3, 6), {"0".."9"}) = Text.Middle(compacto, 3, 6),
            d = Text.Select(s, {"0".."9"})
        in
            if mascarado then "***" & Text.Middle(compacto, 3, 6) & "**"
            else if d = "" or Text.Length(d) > 11 or (Text.Length(d) < 11 and not completar) then null
            else Text.PadStart(d, 11, "0")
"""

CPF_VALIDO = """
(cpf as nullable text) as logical =>
    let d = if cpf = null then "" else Text.Select(cpf, {"0".."9"})
    in
        if Text.Length(d) <> 11 or Text.Replace(d, Text.Start(d, 1), "") = "" then false
        else
        let
            n = List.Transform(Text.ToList(d), Number.From),
            dv = (tamanho as number) as number =>
                Number.Mod(Number.Mod(
                    List.Sum(List.Transform({0..tamanho - 1}, (i) => n{i} * (tamanho + 1 - i))) * 10, 11
                ), 10)
        in
            dv(9) = n{9} and dv(10) = n{10}
"""

CNPJ = """
(v as any, completar as logical) as nullable text =>
    let s = WolfzPrepId(v)
    in
        if s = null then null
        else
        let
            c = Text.Upper(Text.Remove(s, {".", "-", "/", " ", "#(tab)", "#(cr)", "#(lf)"})),
            soDigitos = Text.Length(c) > 0 and Text.Select(c, {"0".."9"}) = c,
            alfanumerico = Text.Length(c) = 14
                and Text.Select(Text.Start(c, 12), {"0".."9", "A".."Z"}) = Text.Start(c, 12)
                and Text.Select(Text.End(c, 2), {"0".."9"}) = Text.End(c, 2)
        in
            if soDigitos then
                (if Text.Length(c) > 14 or (Text.Length(c) < 14 and not completar) then null else Text.PadStart(c, 14, "0"))
            else if alfanumerico then c
            else null
"""

CNPJ_VALIDO = """
(cnpj as nullable text) as logical =>
    let
        c = if cnpj = null then "" else Text.Upper(Text.Remove(cnpj, {".", "-", "/", " "})),
        formato = Text.Length(c) = 14
            and Text.Select(Text.Start(c, 12), {"0".."9", "A".."Z"}) = Text.Start(c, 12)
            and Text.Select(Text.End(c, 2), {"0".."9"}) = Text.End(c, 2),
        pesos = {5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2},
        // CNPJ alfanumérico (IN RFB 2.229/2024): cada caractere vale o código menos 48.
        valor = (ch as text) as number => Character.ToNumber(ch) - 48,
        dv = (base as text, p as list) as text =>
            let
                total = List.Sum(List.Transform(List.Positions(p), (i) => valor(Text.Middle(base, i, 1)) * p{i})),
                resto = Number.Mod(total, 11)
            in
                if resto < 2 then "0" else Text.From(11 - resto),
        d1 = dv(Text.Start(c, 12), pesos),
        d2 = dv(Text.Start(c, 12) & d1, {6} & pesos)
    in
        formato and Text.Replace(c, Text.Start(c, 1), "") <> "" and d1 & d2 = Text.End(c, 2)
"""

CEP = """
(v as any) as nullable text =>
    let s = WolfzPrepId(v)
    in
        if s = null then null
        else
        let
            d0 = Text.Select(s, {"0".."9"}),
            d = if Text.Length(d0) = 7 then "0" & d0 else d0
        in
            if Text.Length(d) = 8 and d <> "00000000" then d else null
"""

_UF_POR_CHAVE = {normalize_key(nome): uf for uf, nome in UFS.items()} | {uf.lower(): uf for uf in UFS}

UF = f"""
(v as any) as nullable text =>
    Record.FieldOrDefault({_registro(_UF_POR_CHAVE)}, WolfzChave(v), null)
"""

# Funções de que todas as operações brasileiras dependem.
BASE = {
    "WolfzSemAcento": SEM_ACENTO,
    "WolfzEspacos": ESPACOS_M,
    "WolfzChave": CHAVE,
    "WolfzNulo": NULO,
}

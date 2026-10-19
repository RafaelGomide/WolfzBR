"""Operações de padrões brasileiros: aplicam as funções de ``wolfz.br`` em
colunas."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Literal

import polars as pl
from pydantic import Field, model_validator

from wolfz.br.booleanos import parse_bool_br
from wolfz.br.datas import parse_date_br, parse_month_year
from wolfz.br.documentos import (
    clean_cep,
    clean_cnpj,
    clean_cpf,
    clean_cpf_cnpj,
    clean_phone,
    cnpj_is_valid,
    cpf_is_valid,
)
from wolfz.br.geo import normalize_uf, split_municipio_uf
from wolfz.br.numeros import (
    decimal_provavel,
    parse_brl,
    parse_ibge_value,
    parse_number_br,
    parse_percent_br,
    scale_from_unit,
)
from wolfz.core.recipe import Op, register_op
from wolfz.core.text import fix_mojibake, strip_footnote_marks
from wolfz.export.m import m_field, m_text
from wolfz.ops import m_br


def map_unique(fn: Callable[[Any], Any], dtype: pl.DataType) -> Callable[[pl.Series], pl.Series]:
    """Aplica uma função de valor a uma coluna rodando-a uma vez por valor
    distinto. Colunas de relatório repetem muito (datas, categorias), então
    é bem mais rápido que linha a linha."""

    def apply(s: pl.Series) -> pl.Series:
        uniques = s.drop_nulls().unique()
        mapped = pl.Series([fn(v) for v in uniques], dtype=dtype)
        return s.replace_strict(uniques, mapped, default=None, return_dtype=dtype)

    return apply


# Tradução para M da regra de ``parse_brl``, só para o padrão brasileiro.
# Diferenças conhecidas em relação ao Polars (validadas à mão no Power BI
# Desktop, F2.A): número no padrão americano ('1,234.56') vira null no M,
# e os símbolos de moeda são reconhecidos só em maiúsculas.
_M_PARSE_BRL = """
(valor as any, debitoNegativo as logical) as nullable number =>
    let
        semMoeda = if valor = null then "" else List.Accumulate(
            {"US$", "U$", "R$", "€", "BRL", "USD", "EUR", "$", "#(00A0)"},
            Text.From(valor),
            (texto, simbolo) => Text.Replace(texto, simbolo, " ")
        ),
        t0 = Text.Trim(semMoeda),
        ultimo = Text.Upper(Text.End(t0, 1)),
        temDC = Text.Length(t0) > 1 and (ultimo = "D" or ultimo = "C"),
        t1 = if temDC then Text.Trim(Text.Start(t0, Text.Length(t0) - 1)) else t0,
        parenteses = Text.StartsWith(t1, "(") and Text.EndsWith(t1, ")"),
        t2 = if parenteses then Text.Trim(Text.Middle(t1, 1, Text.Length(t1) - 2)) else t1,
        menosNoFim = Text.Length(t2) > 1 and Text.EndsWith(t2, "-"),
        t3 = Text.Remove(if menosNoFim then Text.Start(t2, Text.Length(t2) - 1) else t2, {" "}),
        sinais = List.Count(List.Select(
            {temDC and ultimo = "D" and debitoNegativo, parenteses, menosNoFim}, each _ = true
        )),
        numero =
            if t3 = "-" or t3 = "#(2013)" or t3 = "#(2014)" then 0
            else if t3 = "" or Text.Contains(t3, "%") then null
            else try Number.FromText(t3, "pt-BR") otherwise null
    in
        if numero = null then null else if Number.IsOdd(sinais) then -numero else numero
"""


@register_op
class ParseBrl(Op):
    """Converte moeda brasileira em número: 'R$ 1.234,56' -> 1234.56.

    Aceita negativo contábil '(1.234,56)', menos no fim (SAP), '-' como zero
    (formato contábil do Excel) e, com ``debit_negative``, sufixo D/C com
    débito negativo. Valor que não é moeda vira nulo, nunca um número
    errado (ver ``wolfz.br.numeros.parse_brl``)."""

    op: Literal["parse_brl"]
    m_label = "Valores em reais convertidos"
    full_checkpoint = True  # função Python por valor
    cols: list[str] = Field(min_length=1)
    debit_negative: bool = False

    python_helpers = (parse_brl,)
    m_helpers = {"WolfzParseBrl": _M_PARSE_BRL}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["valor"]},
            "input": {
                "valor": ["R$ 1.234,56", "(1.234,56)", "1.234,56-", "R$ -", "#N/D", None, "12%", "1,5E+3"],
            },
            "expected": {"valor": [1234.56, -1234.56, -1234.56, 0.0, None, None, None, 1500.0]},
        },
        {
            "step": {"cols": ["debito", "credito"], "debit_negative": True},
            "input": {"debito": ["100,00 D", "50,00 C"], "credito": ["R$ 10", "abc"]},
            "expected": {"debito": [-100.0, 50.0], "credito": [10.0, None]},
        },
    )

    def _fn(self) -> Callable[[Any], float | None]:
        if self.debit_negative:
            return lambda v: parse_brl(v, debit_negative=True)
        return parse_brl

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        apply = map_unique(self._fn(), pl.Float64)
        return lf.with_columns(pl.col(c).map_batches(apply, return_dtype=pl.Float64) for c in self.cols)

    def to_m(self, prev: str, name: str) -> str:
        debit = "true" if self.debit_negative else "false"
        transforms = ", ".join(
            f"{{{m_text(c)}, each WolfzParseBrl(_, {debit}), type nullable number}}" for c in self.cols
        )
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"

    def to_python(self) -> str:
        fn = "lambda v: parse_brl(v, debit_negative=True)" if self.debit_negative else "parse_brl"
        return f"lf = lf.with_columns(pl.col({self.cols!r}).map_elements({fn}, return_dtype=pl.Float64))"


# ---------------------------------------------------------------------------
# Operações que aplicam uma função de wolfz.br a cada coluna
# ---------------------------------------------------------------------------

_DATA = __import__("datetime").date


class _ValorBr(Op):
    """Base: aplica ``funcao`` (de ``wolfz.br``) a cada valor das colunas.
    No motor, a função roda uma vez por valor distinto (``map_unique``); no
    script exportado, ``map_elements``. Valor nulo continua nulo."""

    cols: list[str] = Field(min_length=1)

    # Função Python por valor: o Polars não empurra o recorte da página para
    # dentro dela, então recalcular a cada página custaria a coluna inteira.
    full_checkpoint = True

    funcao: ClassVar[Callable[..., Any]]
    dtype: ClassVar[str]  # nome do tipo Polars: "Float64", "Date"…
    m_tipo: ClassVar[str]

    def _kwargs(self) -> dict[str, Any]:
        return {}

    def _fn(self) -> Callable[[Any], Any]:
        fn, kwargs = type(self).funcao, self._kwargs()
        return (lambda v: fn(v, **kwargs)) if kwargs else fn

    def _fn_python(self) -> str:
        nome, kwargs = type(self).funcao.__name__, self._kwargs()
        if not kwargs:
            return nome
        args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
        return f"lambda v: {nome}(v, {args})"

    def _m(self, valor: str) -> str:
        raise NotImplementedError

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        dtype = getattr(pl, self.dtype)
        aplicar = map_unique(self._fn(), dtype)
        return lf.with_columns(pl.col(c).map_batches(aplicar, return_dtype=dtype).alias(c) for c in self.cols)

    def to_python(self) -> str:
        return (
            f"lf = lf.with_columns(pl.col({self.cols!r}).map_elements({self._fn_python()}, "
            f"return_dtype=pl.{self.dtype}))"
        )

    def to_m(self, prev: str, name: str) -> str:
        transforms = ", ".join(f"{{{m_text(c)}, each {self._m('_')}, {self.m_tipo}}}" for c in self.cols)
        return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"


@register_op
class ParseDecimalBr(_ValorBr):
    """Número em formato brasileiro: '1.234,56' -> 1234.56. Aceita
    negativo contábil '(1,5)', menos no fim (SAP), símbolo de moeda,
    espaço como milhar e notação científica. Valor com '%' vira nulo (use
    ``parse_percent``). ``decimal='.'`` para bases que publicam ponto
    decimal; ``decimal='auto'`` decide pela coluna inteira (ponto quando
    algum valor só faz sentido com ponto decimal, como número do Excel lido
    como texto: '8725.3480')."""

    op: Literal["parse_decimal_br"]
    m_label = "Números convertidos"
    decimal: Literal[",", ".", "auto"] = ","
    dash_is_zero: bool = False
    debit_negative: bool = False

    funcao = parse_number_br
    dtype = "Float64"
    m_tipo = "type nullable number"
    python_helpers = (parse_number_br, decimal_provavel)
    m_helpers = {  # noqa: RUF012
        **m_br.BASE,
        "WolfzNumeroBr": m_br.NUMERO_BR,
        "WolfzDecimalProvavel": m_br.DECIMAL_PROVAVEL,
    }
    examples = (
        {
            "step": {"cols": ["v"]},
            "input": {"v": ["1.234,56", "(1,5)", "10-", "R$ 3", "1 234,5", "12%", "-", "abc", None, "1.234"]},
            "expected": {"v": [1234.56, -1.5, -10.0, 3.0, 1234.5, None, None, None, None, 1234.0]},
        },
        {
            "step": {"cols": ["v"], "decimal": ".", "dash_is_zero": True},
            "input": {"v": ["1.234", "1,234.5", "-"]},
            "expected": {"v": [1.234, 1234.5, 0.0]},
        },
        {
            # "0.125" com decimal="," viraria 125: a coluna tem "8725.3480",
            # que só pode ser ponto decimal. A coluna w é brasileira.
            "step": {"cols": ["v", "w"], "decimal": "auto"},
            "input": {
                "v": ["8725.3480", "0.125", "1", None],
                "w": ["1.234", "2,5", "1.234.567", None],
            },
            "expected": {"v": [8725.348, 0.125, 1.0, None], "w": [1234.0, 2.5, 1234567.0, None]},
        },
        {
            "step": {"cols": ["v"], "debit_negative": True},
            "input": {"v": ["1.234,56 D", "10,00 C", "5,00", "7,5D", None]},
            "expected": {"v": [-1234.56, 10.0, 5.0, -7.5, None]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.decimal == ".":
            kwargs["decimal"] = "."
        if self.dash_is_zero:
            kwargs["dash_is_zero"] = True
        if self.debit_negative:
            kwargs["debit_negative"] = True
        return kwargs

    def _m(self, valor: str, cultura: str | None = None) -> str:
        if cultura is None:
            cultura = '"pt-BR"' if self.decimal == "," else '"en-US"'
        traco, debito = str(self.dash_is_zero).lower(), str(self.debit_negative).lower()
        return f"WolfzNumeroBr({valor}, {traco}, {debito}, {cultura})"

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        if self.decimal != "auto":
            return super().to_polars(lf)
        kwargs = self._kwargs()

        def aplicar(s: pl.Series) -> pl.Series:
            decimal = decimal_provavel(s.drop_nulls().unique().to_list())
            return map_unique(lambda v: parse_number_br(v, decimal=decimal, **kwargs), pl.Float64)(s)

        return lf.with_columns(
            pl.col(c).map_batches(aplicar, return_dtype=pl.Float64).alias(c) for c in self.cols
        )

    def to_python(self) -> str:
        if self.decimal != "auto":
            return super().to_python()
        extra = "".join(f", {k}={v!r}" for k, v in self._kwargs().items())
        # A decisão é pela coluna inteira: decimal_provavel olha todos os
        # valores antes de converter.
        return (
            "lf = lf.with_columns(\n"
            "    pl.col(c).map_batches(\n"
            "        lambda s: (lambda d: s.map_elements(\n"
            f"            lambda v: parse_number_br(v, decimal=d{extra}), return_dtype=pl.Float64\n"
            "        ))(decimal_provavel(s.to_list())),\n"
            "        return_dtype=pl.Float64,\n"
            "    )\n"
            f"    for c in {self.cols!r}\n"
            ")"
        )

    def to_m(self, prev: str, name: str) -> str:
        if self.decimal != "auto":
            return super().to_m(prev, name)
        culturas = ",\n".join(
            f"        cultura{i} = WolfzDecimalProvavel(Table.Column({prev}, {m_text(c)}))"
            for i, c in enumerate(self.cols)
        )
        transforms = ", ".join(
            f"{{{m_text(c)}, each {self._m('_', f'cultura{i}')}, {self.m_tipo}}}"
            for i, c in enumerate(self.cols)
        )
        tabela = f"Table.TransformColumns({prev}, {{{transforms}}})"
        return f"{name} = let\n{culturas}\n    in\n        {tabela}"


@register_op
class ParsePercent(_ValorBr):
    """Percentual para fração: '12,5%' -> 0.125. Sem o '%', ``bare`` diz o
    que o número é: ``fraction`` ('0,125' -> 0.125) ou ``points`` ('12,5' ->
    0.125). A escolha vale para a coluna inteira, nunca valor a valor."""

    op: Literal["parse_percent"]
    m_label = "Percentuais convertidos"
    bare: Literal["fraction", "points"] = "fraction"

    funcao = parse_percent_br
    dtype = "Float64"
    m_tipo = "type nullable number"
    python_helpers = (parse_percent_br,)
    m_helpers = {**m_br.BASE, "WolfzNumeroBr": m_br.NUMERO_BR, "WolfzPercentual": m_br.PERCENTUAL}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["p"]},
            "input": {"p": ["12,5%", "0,125", "100 %", None, "x"]},
            "expected": {"p": [0.125, 0.125, 1.0, None, None]},
        },
        {
            "step": {"cols": ["p"], "bare": "points"},
            "input": {"p": ["12,5", "3%"]},
            "expected": {"p": [0.125, 0.03]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        return {"bare": self.bare} if self.bare != "fraction" else {}

    def _m(self, valor: str) -> str:
        return f"WolfzPercentual({valor}, {str(self.bare == 'points').lower()})"


@register_op
class ParseDateBr(_ValorBr):
    """Data em qualquer formato comum no Brasil: '31/12/2024', '31.12.24',
    '2024-12-31', '31 de dezembro de 2024', 8 dígitos ('20241231',
    '31122024') e serial do Excel. Data impossível, zerada ou o 'sem data
    fim' de ERP (ano 9999) vira nulo. ``eight_digits`` decide como ler 8
    dígitos; ``century_pivot`` decide o século de ano com 2 dígitos."""

    op: Literal["parse_date_br"]
    m_label = "Datas convertidas"
    eight_digits: Literal["auto", "ymd", "dmy"] = "auto"
    century_pivot: int = Field(default=30, ge=0, le=99)
    accept_excel_serial: bool = True

    funcao = parse_date_br
    dtype = "Date"
    m_tipo = "type nullable date"
    python_helpers = (parse_date_br,)
    m_helpers = {**m_br.BASE, "WolfzDataBr": m_br.DATA_BR}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["d"]},
            "input": {
                "d": [
                    "31/12/2024",
                    "31.12.24",
                    "2024-12-31T10:00:00",
                    "31 de dezembro de 2024",
                    "20241231",
                    "45657",
                    "31/02/2024",
                    "31.12.9999",
                    "00/00/0000",
                    None,
                ]
            },
            "expected": {
                "d": [_DATA(2024, 12, 31)] * 6 + [None, None, None, None],
            },
        },
        {
            "step": {"cols": ["d"], "eight_digits": "dmy", "accept_excel_serial": False},
            "input": {"d": ["01022024", "45657", "15/03/29", "15/03/30"]},
            "expected": {"d": [_DATA(2024, 2, 1), None, _DATA(2029, 3, 15), _DATA(1930, 3, 15)]},
        },
        {
            "step": {"cols": ["d"], "eight_digits": "ymd", "century_pivot": 50},
            "input": {"d": ["20240201", "01022024", "15/03/49", "15/03/50"]},
            "expected": {"d": [_DATA(2024, 2, 1), None, _DATA(2049, 3, 15), _DATA(1950, 3, 15)]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.eight_digits != "auto":
            kwargs["eight_digits"] = self.eight_digits
        if self.century_pivot != 30:
            kwargs["century_pivot"] = self.century_pivot
        if not self.accept_excel_serial:
            kwargs["accept_excel_serial"] = False
        return kwargs

    def _m(self, valor: str) -> str:
        serial = str(self.accept_excel_serial).lower()
        return f'WolfzDataBr({valor}, "{self.eight_digits}", {self.century_pivot}, {serial})'


@register_op
class ParseMonthYear(_ValorBr):
    """Mês/ano para o 1º dia do mês: 'jan/24', 'Janeiro de 2024',
    '01/2024', '2024-01', '202401', 'Competência 03/2025'."""

    op: Literal["parse_month_year"]
    m_label = "Meses convertidos"
    century_pivot: int = Field(default=30, ge=0, le=99)

    funcao = parse_month_year
    dtype = "Date"
    m_tipo = "type nullable date"
    python_helpers = (parse_month_year,)
    m_helpers = {**m_br.BASE, "WolfzMesAno": m_br.MES_ANO}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["m"]},
            "input": {
                "m": [
                    "jan/24",
                    "Janeiro de 2024",
                    "01/2024",
                    "2024-01",
                    "202401",
                    "Competência 03/2025",
                    "13/2024",
                    None,
                ]
            },
            "expected": {"m": [_DATA(2024, 1, 1)] * 5 + [_DATA(2025, 3, 1), None, None]},
        },
        {
            "step": {"cols": ["m"], "century_pivot": 50},
            "input": {"m": ["jan/49", "jan/50", "03/2025"]},
            "expected": {"m": [_DATA(2049, 1, 1), _DATA(1950, 1, 1), _DATA(2025, 3, 1)]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        return {"century_pivot": self.century_pivot} if self.century_pivot != 30 else {}

    def _m(self, valor: str) -> str:
        return f"WolfzMesAno({valor}, {self.century_pivot})"


@register_op
class ParseBoolBr(_ValorBr):
    """'Sim'/'S'/'X'/'1' -> verdadeiro; 'Não'/'N'/'0' -> falso. Com
    ``empty_is_false``, célula vazia é falso (colunas de "marque com X")."""

    op: Literal["parse_bool_br"]
    m_label = "Booleanos convertidos"
    empty_is_false: bool = False

    funcao = parse_bool_br
    dtype = "Boolean"
    m_tipo = "type nullable logical"
    python_helpers = (parse_bool_br,)
    m_helpers = {**m_br.BASE, "WolfzBool": m_br.BOOL}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["b"]},
            "input": {"b": ["Sim", "NÃO", "x", "0", "talvez", ""]},
            "expected": {"b": [True, False, True, False, None, None]},
        },
        {
            "step": {"cols": ["b"], "empty_is_false": True},
            "input": {"b": ["X", " ", "s"]},
            "expected": {"b": [True, False, True]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        return {"empty_is_false": True} if self.empty_is_false else {}

    def _m(self, valor: str) -> str:
        return f"WolfzBool({valor}, {str(self.empty_is_false).lower()})"


class _Documento(_ValorBr):
    """Base de CPF e CNPJ: limpa e, com ``flag``, acrescenta a coluna
    ``<coluna>_valido`` com o dígito verificador conferido."""

    pad_zeros: bool = True
    flag: bool = False

    valido: ClassVar[Callable[[str | None], bool]]
    m_valido: ClassVar[str]

    dtype = "String"
    m_tipo = "type nullable text"

    def _kwargs(self) -> dict[str, Any]:
        return {} if self.pad_zeros else {"pad_zeros": False}

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        lf = super().to_polars(lf)
        if not self.flag:
            return lf
        aplicar = map_unique(type(self).valido, pl.Boolean)
        return lf.with_columns(
            pl.col(c).map_batches(aplicar, return_dtype=pl.Boolean).alias(f"{c}_valido") for c in self.cols
        )

    def to_python(self) -> str:
        linhas = super().to_python()
        if self.flag:
            nome = type(self).valido.__name__
            linhas += (
                f"\nlf = lf.with_columns(pl.col(c).map_elements({nome}, return_dtype=pl.Boolean)"
                f".alias(c + '_valido') for c in {self.cols!r})"
            )
        return linhas

    def to_m(self, prev: str, name: str) -> str:
        limpo = super().to_m(prev, name)
        if not self.flag:
            return limpo
        expr = limpo.split(" = ", 1)[1]
        for c in self.cols:
            campo = m_field(c)
            corpo = f"each if {campo} = null then null else {self.m_valido}({campo})"
            expr = f"Table.AddColumn({expr}, {m_text(c + '_valido')}, {corpo}, type nullable logical)"
        return f"{name} = {expr}"


@register_op
class CleanCpf(_Documento):
    """CPF como texto de 11 dígitos, sem máscara: '123.456.789-09' ->
    '12345678909'; '2345678909' -> '02345678909' (zero perdido no Excel).
    CPF mascarado do Portal da Transparência ('***.456.789-**') vira
    '***456789**'. Com ``pad_zeros=False``, CPF curto vira nulo."""

    op: Literal["clean_cpf"]
    m_label = "CPF limpo"

    funcao = clean_cpf
    valido = cpf_is_valid
    m_valido = "WolfzCpfValido"
    python_helpers = (clean_cpf, cpf_is_valid)
    m_helpers = {  # noqa: RUF012
        **m_br.BASE,
        "WolfzPrepId": m_br.PREP_ID,
        "WolfzCpf": m_br.CPF,
        "WolfzCpfValido": m_br.CPF_VALIDO,
    }
    examples = (
        {
            "step": {"cols": ["cpf"], "flag": True},
            "input": {
                "cpf": ["529.982.247-25", "2345678909", "12345678909.0", "***.456.789-**", "1,23E+10", None]
            },
            "expected": {
                "cpf": ["52998224725", "02345678909", "12345678909", "***456789**", None, None],
                "cpf_valido": [True, False, True, False, None, None],
            },
        },
        {
            "step": {"cols": ["cpf"], "pad_zeros": False},
            "input": {"cpf": ["2345678909", "52998224725"]},
            "expected": {"cpf": [None, "52998224725"]},
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzCpf({valor}, {str(self.pad_zeros).lower()})"


@register_op
class CleanCnpj(_Documento):
    """CNPJ como texto de 14 caracteres, sem máscara, letras em maiúscula:
    '12.345.678/0001-95' -> '12345678000195'; '191' -> '00000000000191'.
    Aceita o CNPJ alfanumérico (julho de 2026); a flag confere o dígito
    verificador com a regra nova, que vale também para o numérico."""

    op: Literal["clean_cnpj"]
    m_label = "CNPJ limpo"

    funcao = clean_cnpj
    valido = cnpj_is_valid
    m_valido = "WolfzCnpjValido"
    python_helpers = (clean_cnpj, cnpj_is_valid)
    m_helpers = {  # noqa: RUF012
        **m_br.BASE,
        "WolfzPrepId": m_br.PREP_ID,
        "WolfzCnpj": m_br.CNPJ,
        "WolfzCnpjValido": m_br.CNPJ_VALIDO,
    }
    examples = (
        {
            "step": {"cols": ["c"], "flag": True},
            "input": {
                "c": ["00.000.000/0001-91", "191", "12.abc.345/01de-35", "11.222.333/0001-80", "abc", None]
            },
            "expected": {
                "c": ["00000000000191", "00000000000191", "12ABC34501DE35", "11222333000180", None, None],
                "c_valido": [True, True, True, False, None, None],
            },
        },
        {
            "step": {"cols": ["c"], "pad_zeros": False},
            "input": {"c": ["191", "00.000.000/0001-91", None]},
            "expected": {"c": [None, "00000000000191", None]},
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzCnpj({valor}, {str(self.pad_zeros).lower()})"


@register_op
class CleanCep(_ValorBr):
    """CEP como 8 dígitos: '29100-000' -> '29100000'; '1310100' ->
    '01310100' (zero perdido no Excel). CEP de 5 dígitos é ambíguo e vira
    nulo."""

    op: Literal["clean_cep"]
    m_label = "CEP limpo"

    funcao = clean_cep
    dtype = "String"
    m_tipo = "type nullable text"
    python_helpers = (clean_cep,)
    m_helpers = {**m_br.BASE, "WolfzPrepId": m_br.PREP_ID, "WolfzCep": m_br.CEP}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["cep"]},
            "input": {"cep": ["29100-000", "1310100", "29100", "00000-000", None, "1310100.0"]},
            "expected": {"cep": ["29100000", "01310100", None, None, None, "01310100"]},
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzCep({valor})"


@register_op
class NormalizeUf(_ValorBr):
    """UF como sigla: 'es', 'Espírito Santo', 'ESPIRITO SANTO' -> 'ES'.
    O que não é UF vira nulo."""

    op: Literal["normalize_uf"]
    m_label = "UF normalizada"

    funcao = normalize_uf
    dtype = "String"
    m_tipo = "type nullable text"
    python_helpers = (normalize_uf,)
    m_helpers = {**m_br.BASE, "WolfzUf": m_br.UF}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["uf"]},
            "input": {"uf": ["es", "Espírito Santo", "SAO PAULO", " rj ", "XX", None]},
            "expected": {"uf": ["ES", "ES", "SP", "RJ", None, None]},
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzUf({valor})"


# ---------------------------------------------------------------------------
# Pacote BR completo (F2.C6)
# ---------------------------------------------------------------------------


def map_unique_rows(fn: Callable[..., Any], dtype: pl.DataType) -> Callable[[pl.Series], pl.Series]:
    """Como ``map_unique``, para uma função de várias colunas (recebe uma
    coluna struct): roda uma vez por combinação distinta."""

    def apply(s: pl.Series) -> pl.Series:
        linhas = s.struct.unnest().rows()
        resultados = {linha: fn(*linha) for linha in set(linhas)}
        return pl.Series(s.name, [resultados[linha] for linha in linhas], dtype=dtype)

    return apply


@register_op
class CleanPhone(_ValorBr):
    """Telefone no formato E.164: '(27) 99999-9999' -> '+5527999999999'.
    Trata +55, zero de longa distância, código de operadora e celular
    antigo de 8 dígitos (acrescenta o 9, a não ser com
    ``add_ninth_digit=False``). Número sem DDD usa ``default_ddd``; sem ele,
    vira nulo, como 0800 e DDD que não existe."""

    op: Literal["clean_phone"]
    m_label = "Telefone limpo"
    default_ddd: str | None = Field(default=None, pattern=r"^\d{2}$", description="DDD para número sem DDD")
    add_ninth_digit: bool = True

    funcao = clean_phone
    dtype = "String"
    m_tipo = "type nullable text"
    python_helpers = (clean_phone,)
    m_helpers = {**m_br.BASE, "WolfzPrepId": m_br.PREP_ID, "WolfzTelefone": m_br.TELEFONE}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["tel"]},
            "input": {
                "tel": [
                    "(27) 99999-9999",
                    "+55 27 3333-4444",
                    "027 8888-7777",
                    "0 21 27 99999-9999",
                    "0800 123 4567",
                    "99999-9999",
                    None,
                ]
            },
            "expected": {
                "tel": [
                    "+5527999999999",
                    "+552733334444",
                    "+5527988887777",
                    "+5527999999999",
                    None,
                    None,
                    None,
                ]
            },
        },
        {
            "step": {"cols": ["tel"], "default_ddd": "27", "add_ninth_digit": False},
            "input": {"tel": ["8888-7777", "(11) 8888-7777", "27 1234-5678"]},
            "expected": {"tel": ["+552788887777", "+551188887777", "+552712345678"]},
        },
    )

    def _kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.default_ddd is not None:
            kwargs["default_ddd"] = self.default_ddd
        if not self.add_ninth_digit:
            kwargs["add_ninth_digit"] = False
        return kwargs

    def _m(self, valor: str) -> str:
        ddd = "null" if self.default_ddd is None else m_text(self.default_ddd)
        return f"WolfzTelefone({valor}, {ddd}, {str(self.add_ninth_digit).lower()})"


@register_op
class CleanCpfCnpj(Op):
    """Coluna com CPF ou CNPJ ("CPF OU CNPJ DO SANCIONADO" no CEIS): limpa
    e completa os zeros no tamanho certo. Com ``person_type_col`` (coluna com
    'F'/'J', 'PF'/'PJ', 'Física'/'Jurídica'), o tipo decide; sem ela, o
    tamanho e o dígito verificador. Ambíguo vira nulo."""

    op: Literal["clean_cpf_cnpj"]
    m_label = "CPF ou CNPJ limpo"
    full_checkpoint = True
    col: str
    person_type_col: str | None = None

    python_helpers = (clean_cpf_cnpj,)
    m_helpers = {  # noqa: RUF012
        **m_br.BASE,
        "WolfzPrepId": m_br.PREP_ID,
        "WolfzCpf": m_br.CPF,
        "WolfzCnpj": m_br.CNPJ,
        "WolfzCpfValido": m_br.CPF_VALIDO,
        "WolfzCnpjValido": m_br.CNPJ_VALIDO,
        "WolfzCpfCnpj": m_br.CPF_CNPJ,
    }
    examples = (
        {
            "step": {"col": "doc"},
            "input": {"doc": ["529.982.247-25", "191", "11.222.333/0001-81", "2345678909", "abc", None]},
            "expected": {"doc": ["52998224725", None, "11222333000181", None, None, None]},
        },
        {
            "step": {"col": "doc", "person_type_col": "tipo"},
            "input": {"doc": ["191", "191", "52998224725", None], "tipo": ["J", "F", "Pessoa Física", "J"]},
            "expected": {
                "doc": ["00000000000191", "00000000191", "52998224725", None],
                "tipo": ["J", "F", "Pessoa Física", "J"],
            },
        },
    )

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        if self.person_type_col is None:
            return lf.with_columns(
                pl.col(self.col).map_batches(map_unique(clean_cpf_cnpj, pl.String), return_dtype=pl.String)
            )
        par = pl.struct(pl.col(self.col).cast(pl.String), pl.col(self.person_type_col).cast(pl.String))
        aplicar = map_unique_rows(clean_cpf_cnpj, pl.String)
        return lf.with_columns(par.map_batches(aplicar, return_dtype=pl.String).alias(self.col))

    def to_python(self) -> str:
        if self.person_type_col is None:
            fn = "map_elements(clean_cpf_cnpj, return_dtype=pl.String)"
            return f"lf = lf.with_columns(pl.col({self.col!r}).{fn})"
        return (
            f"lf = lf.with_columns(pl.struct({self.col!r}, {self.person_type_col!r})"
            f".map_elements(lambda r: clean_cpf_cnpj(r[{self.col!r}], r[{self.person_type_col!r}]), "
            f"return_dtype=pl.String).alias({self.col!r}))"
        )

    def to_m(self, prev: str, name: str) -> str:
        if self.person_type_col is None:
            return (
                f"{name} = Table.TransformColumns({prev}, "
                f"{{{{{m_text(self.col)}, each WolfzCpfCnpj(_, null), type nullable text}}}})"
            )
        campo, tipo = m_field(self.col), m_field(self.person_type_col)
        return (
            f"{name} = Table.ReplaceValue({prev}, each {campo}, each WolfzCpfCnpj({campo}, {tipo}), "
            f"Replacer.ReplaceValue, {{{m_text(self.col)}}})"
        )


@register_op
class SplitMunicipioUf(Op):
    """Separa município e UF que vêm no mesmo campo: 'Vitória - ES',
    'Vitória/ES', 'Alta Floresta D'Oeste (RO)'. O município fica em ``col``
    e a UF vai para a coluna nova ``uf_col``. Só separa se o fim for uma UF
    de verdade: 'Embu-Guaçu' continua inteiro (e a UF fica nula)."""

    op: Literal["split_municipio_uf"]
    m_label = "Município e UF separados"
    full_checkpoint = True
    col: str
    uf_col: str = "uf"

    python_helpers = (split_municipio_uf,)
    m_helpers = {**m_br.BASE, "WolfzMunicipioUf": m_br.MUNICIPIO_UF}  # noqa: RUF012
    examples = (
        {
            "step": {"col": "m"},
            "input": {
                "m": [
                    "Vitória - ES",
                    "Vitória/es",
                    "Alta Floresta D'Oeste (RO)",
                    "Embu-Guaçu",
                    "Serra (XX)",
                    None,
                ]
            },
            "expected": {
                "m": ["Vitória", "Vitória", "Alta Floresta D'Oeste", "Embu-Guaçu", "Serra (XX)", None],
                "uf": ["ES", "ES", "RO", None, None, None],
            },
        },
        {
            "step": {"col": "local", "uf_col": "sigla"},
            "input": {"local": ["Serra \u2013 ES", "  Linhares  -  es "]},
            "expected": {"local": ["Serra", "Linhares"], "sigla": ["ES", "ES"]},
        },
    )

    @model_validator(mode="after")
    def _colunas_diferentes(self) -> SplitMunicipioUf:
        if self.uf_col == self.col:
            raise ValueError("uf_col precisa ser diferente de col")
        return self

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        municipio = map_unique(lambda v: split_municipio_uf(v)[0], pl.String)
        uf = map_unique(lambda v: split_municipio_uf(v)[1], pl.String)
        c = pl.col(self.col).cast(pl.String)
        return lf.with_columns(
            c.map_batches(municipio, return_dtype=pl.String).alias(self.col),
            c.map_batches(uf, return_dtype=pl.String).alias(self.uf_col),
        )

    def to_python(self) -> str:
        c = f"pl.col({self.col!r})"
        partes = [
            f"    {c}.map_elements(lambda v: split_municipio_uf(v)[{i}], return_dtype=pl.String)"
            f".alias({nome!r}),"
            for i, nome in enumerate((self.col, self.uf_col))
        ]
        return "\n".join(["lf = lf.with_columns(", *partes, ")"])

    def to_m(self, prev: str, name: str) -> str:
        campo = m_field(self.col)
        uf = f"each WolfzMunicipioUf({campo}){{1}}"
        com_uf = f"Table.AddColumn({prev}, {m_text(self.uf_col)}, {uf}, type nullable text)"
        return (
            f"{name} = Table.TransformColumns({com_uf}, "
            f"{{{{{m_text(self.col)}, each WolfzMunicipioUf(_){{0}}, type nullable text}}}})"
        )


@register_op
class ParseIbgeValue(Op):
    """Valor de tabela do IBGE (SIDRA, Censo, DATASUS) com os sinais
    convencionais: '-' é zero absoluto, '0' é zero arredondado, '..' não se
    aplica, '...' não disponível, 'X' omitido por sigilo. '-' vira 0; os
    outros sinais viram nulo, nunca zero. Com ``status`` (padrão), cria a
    coluna ``<coluna>_situacao`` dizendo qual era o caso de cada célula."""

    op: Literal["parse_ibge_value"]
    m_label = "Valores do IBGE convertidos"
    full_checkpoint = True
    cols: list[str] = Field(min_length=1)
    decimal: Literal[".", ","] = "."
    status: bool = True

    python_helpers = (parse_ibge_value,)
    m_helpers = {  # noqa: RUF012
        **m_br.BASE,
        "WolfzNumeroBr": m_br.NUMERO_BR,
        "WolfzIbge": m_br.IBGE,
    }
    examples = (
        {
            "step": {"cols": ["v"]},
            "input": {"v": ["5556", "-", "..", "...", "X", "0", "1234.5", "abc", None]},
            "expected": {
                "v": [5556.0, 0.0, None, None, None, 0.0, 1234.5, None, None],
                "v_situacao": [
                    "valor",
                    "zero_absoluto",
                    "nao_se_aplica",
                    "nao_disponivel",
                    "omitido_sigilo",
                    "zero_arredondado",
                    "valor",
                    "invalido",
                    "nao_disponivel",
                ],
            },
        },
        {
            "step": {"cols": ["v"], "decimal": ",", "status": False},
            "input": {"v": ["1.234,5", "x", "0,0"]},
            "expected": {"v": [1234.5, None, 0.0]},
        },
    )

    def _fn(self, i: int) -> Callable[[Any], Any]:
        decimal = self.decimal
        return lambda v: parse_ibge_value(v, decimal=decimal)[i]

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        valor = map_unique(self._fn(0), pl.Float64)
        exprs = [
            pl.col(c).cast(pl.String).map_batches(valor, return_dtype=pl.Float64).alias(c) for c in self.cols
        ]
        if self.status:
            situacao = map_unique(self._fn(1), pl.String)
            exprs += [
                pl.col(c)
                .cast(pl.String)
                .map_batches(situacao, return_dtype=pl.String)
                .fill_null("nao_disponivel")
                .alias(f"{c}_situacao")
                for c in self.cols
            ]
        return lf.with_columns(exprs)

    def to_python(self) -> str:
        args = "" if self.decimal == "." else f", decimal={self.decimal!r}"
        linhas = [
            "lf = lf.with_columns(",
            f"    pl.col(c).map_elements(lambda v: parse_ibge_value(v{args})[0], return_dtype=pl.Float64)",
            f"    for c in {self.cols!r}",
            ")",
        ]
        if self.status:
            linhas = [
                "lf = lf.with_columns(",
                f"    pl.col(c).map_elements(lambda v: parse_ibge_value(v{args})[1], return_dtype=pl.String)",
                "    .fill_null('nao_disponivel')",
                "    .alias(c + '_situacao')",
                f"    for c in {self.cols!r}",
                ")",
                *linhas,
            ]
        return "\n".join(linhas)

    def to_m(self, prev: str, name: str) -> str:
        cultura = '"pt-BR"' if self.decimal == "," else '"en-US"'
        expr = prev
        if self.status:
            for c in self.cols:
                corpo = f"each WolfzIbge({m_field(c)}, {cultura}){{1}}"
                expr = f"Table.AddColumn({expr}, {m_text(c + '_situacao')}, {corpo}, type text)"
        transforms = ", ".join(
            f"{{{m_text(c)}, each WolfzIbge(_, {cultura}){{0}}, type nullable number}}" for c in self.cols
        )
        return f"{name} = Table.TransformColumns({expr}, {{{transforms}}})"


@register_op
class ScaleByUnit(Op):
    """Multiplica colunas numéricas pela escala escrita na unidade: 'Mil
    Reais' -> x1.000, 'R$ milhões' -> x1.000.000. A unidade é fixa
    (``unit``, a do título da tabela) ou vem de outra coluna
    (``unit_col``, uma por linha). Use depois de converter o número."""

    op: Literal["scale_by_unit"]
    m_label = "Valores na escala da unidade"
    cols: list[str] = Field(min_length=1)
    unit: str | None = None
    unit_col: str | None = None

    python_helpers = (scale_from_unit,)
    m_helpers = {**m_br.BASE, "WolfzEscala": m_br.ESCALA}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["v"], "unit": "Mil Reais"},
            "input": {"v": [1.5, None, 2.0]},
            "expected": {"v": [1500.0, None, 2000.0]},
        },
        {
            "step": {"cols": ["v", "w"], "unit_col": "u"},
            "input": {
                "v": [1.0, 2.0, 3.0, 4.0],
                "w": [1, 1, 1, None],
                "u": ["R$ milhões", "Toneladas", "bilhões", None],
            },
            "expected": {
                "v": [1000000.0, 2.0, 3000000000.0, 4.0],
                "w": [1000000, 1, 1000000000, None],
                "u": ["R$ milhões", "Toneladas", "bilhões", None],
            },
        },
    )

    @model_validator(mode="after")
    def _uma_unidade(self) -> ScaleByUnit:
        if (self.unit is None) == (self.unit_col is None):
            raise ValueError("informe unit (unidade fixa) ou unit_col (coluna com a unidade), um dos dois")
        return self

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        if self.unit is not None:
            fator: pl.Expr = pl.lit(scale_from_unit(self.unit))
        else:
            escala = map_unique(scale_from_unit, pl.Int64)
            fator = (
                pl.col(self.unit_col).cast(pl.String).map_batches(escala, return_dtype=pl.Int64).fill_null(1)
            )
        return lf.with_columns(pl.col(c) * fator for c in self.cols)

    def to_python(self) -> str:
        if self.unit is not None:
            return f"lf = lf.with_columns(pl.col(c) * scale_from_unit({self.unit!r}) for c in {self.cols!r})"
        fator = f"pl.col({self.unit_col!r}).map_elements(scale_from_unit, return_dtype=pl.Int64).fill_null(1)"
        return f"lf = lf.with_columns(pl.col(c) * {fator} for c in {self.cols!r})"

    def to_m(self, prev: str, name: str) -> str:
        if self.unit is not None:
            fator = scale_from_unit(self.unit)
            transforms = ", ".join(
                f"{{{m_text(c)}, each _ * {fator}, type nullable number}}" for c in self.cols
            )
            return f"{name} = Table.TransformColumns({prev}, {{{transforms}}})"
        expr = prev
        for c in self.cols:
            campo = m_field(c)
            novo = f"each {campo} * WolfzEscala({m_field(self.unit_col)})"
            expr = f"Table.ReplaceValue({expr}, each {campo}, {novo}, Replacer.ReplaceValue, {{{m_text(c)}}})"
        return f"{name} = {expr}"


@register_op
class FixMojibake(_ValorBr):
    """Conserta acento estragado de texto UTF-8 lido como Latin-1:
    'SÃ£o Paulo' -> 'São Paulo'. Desfaz até duas camadas; texto que não
    volta inteiro fica como está."""

    op: Literal["fix_mojibake"]
    m_label = "Acentuação corrigida"

    funcao = fix_mojibake
    dtype = "String"
    m_tipo = "type nullable text"
    python_helpers = (fix_mojibake,)
    m_helpers = {"WolfzMojibake": m_br.MOJIBAKE}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["t"]},
            "input": {"t": ["SÃ£o Paulo", "InformaÃ§Ã£o", "SÃƒÂ£o", "São Paulo", "SÃO PAULO", None]},
            "expected": {"t": ["São Paulo", "Informação", "São", "São Paulo", "SÃO PAULO", None]},
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzMojibake({valor})"


@register_op
class StripFootnotes(_ValorBr):
    """Tira a marca de nota de rodapé do fim do texto: 'Abacaxi*' ->
    'Abacaxi', 'Total²' -> 'Total', 'Receita líquida (1)' -> 'Receita
    líquida'. Sem isso, a mesma categoria aparece com e sem a marca em anos
    diferentes e não agrupa."""

    op: Literal["strip_footnotes"]
    m_label = "Notas de rodapé removidas"

    funcao = strip_footnote_marks
    dtype = "String"
    m_tipo = "type nullable text"
    python_helpers = (strip_footnote_marks,)
    m_helpers = {"WolfzNotaRodape": m_br.NOTA_RODAPE}  # noqa: RUF012
    examples = (
        {
            "step": {"cols": ["t"]},
            "input": {
                "t": [
                    "Abacaxi*",
                    "Abacaxi **",
                    "Total²",
                    "Receita líquida (1)",
                    "Nota (123)",
                    "A* *",
                    "Sem marca ",
                    None,
                ]
            },
            "expected": {
                "t": [
                    "Abacaxi",
                    "Abacaxi",
                    "Total",
                    "Receita líquida",
                    "Nota (123)",
                    "A*",
                    "Sem marca ",
                    None,
                ]
            },
        },
    )

    def _m(self, valor: str) -> str:
        return f"WolfzNotaRodape({valor})"

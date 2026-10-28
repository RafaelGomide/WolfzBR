"""``assert``: verificação que não transforma os dados (F2.F1).

É a garantia da reaplicação: a receita roda no arquivo do mês seguinte e
para com mensagem clara se ele vier diferente do esperado, em vez de gerar
uma tabela errada em silêncio (§4.5 do design). O motor e o script Python
usam a mesma função, ``verificar_lf``; o M gera um ``error`` que faz o
refresh do Power BI falhar com a mesma mensagem.

Verificações:

- ``not_null``: as colunas não têm célula vazia;
- ``unique``: a combinação das colunas não se repete (chave);
- ``in_range``: os valores estão entre ``min`` e ``max`` (número ou data);
- ``matches``: os valores casam inteiro com a expressão regular ``pattern``.
  O M não tem expressão regular: no Power BI esta verificação não roda;
- ``row_count_min``: a tabela tem pelo menos ``min_rows`` linhas.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

import polars as pl
from pydantic import Field, model_validator

from wolfz.core.recipe import Op, register_op
from wolfz.export.m import m_field, m_list, m_text, m_value
from wolfz.ops.estrutura import _M_VAZIA, celula_vazia

Verificacao = Literal["not_null", "unique", "in_range", "matches", "row_count_min"]


def _nomes(cols: list[str]) -> str:
    return ", ".join(f"'{c}'" for c in cols)


def _linhas_br(linhas: list[int], total: int) -> str:
    """[809, 1204] -> '809 e 1.204'; mais de 5: '1, 2, 3, 4, 5 e mais 7'."""
    nums = [f"{n:,}".replace(",", ".") for n in linhas[:5]]
    if total > len(nums):
        resto = f"{total - len(nums):,}".replace(",", ".")
        return f"{', '.join(nums)} e mais {resto}"
    return nums[0] if len(nums) == 1 else f"{', '.join(nums[:-1])} e {nums[-1]}"


def _reprovada(
    mensagem: str, check: str, cols: list[str], quantidade: int, linhas: list[int], valores: list[str]
) -> AssertionError:
    """O erro da verificação. A mensagem diz coluna, quantidade e linhas,
    nunca o valor (S2): ela vai para o terminal, o ``--report`` e o log.
    Os campos estruturados e os valores de exemplo vão à parte; os valores
    só aparecem no terminal com ``--show-values``."""
    erro = AssertionError(mensagem)
    erro.verificacao = {  # type: ignore[attr-defined]
        "verificacao": check,
        "coluna": ", ".join(cols) if cols else None,
        "quantidade": quantidade,
        "linhas": linhas[:5],
    }
    erro.valores = valores  # type: ignore[attr-defined]
    return erro


def verificar_lf(
    lf: pl.LazyFrame,
    check: str,
    cols: list[str],
    minimo: float | date | None = None,
    maximo: float | date | None = None,
    padrao: str | None = None,
    min_linhas: int | None = None,
) -> pl.LazyFrame:
    """Confere a tabela e a devolve sem mudança. Reprovada, levanta
    ``AssertionError`` com o que falhou, quantas linhas e as primeiras
    (1 = primeira linha de dados), sem o valor das células."""
    df = lf.collect()
    if check == "row_count_min":
        if min_linhas is not None and df.height < min_linhas:
            raise _reprovada(
                f"a tabela tem {df.height} linhas; o mínimo é {min_linhas}", check, [], df.height, [], []
            )
        return df.lazy()
    if check == "unique":
        repetidas = df.select(cols).is_duplicated()
        if repetidas.any():
            indices = repetidas.arg_true()
            total = int(repetidas.sum())
            linhas = [int(i) + 1 for i in indices[:5]]
            valores = [", ".join(str(v) for v in df.select(cols).row(int(i))) for i in indices[:5]]
            raise _reprovada(
                f"{_nomes(cols)} se repete em {total} linhas: {_linhas_br(linhas, total)}",
                check,
                cols,
                total,
                linhas,
                valores,
            )
        return df.lazy()
    for c in cols:
        s = df.get_column(c)
        if check == "not_null":
            falhas = df.select(celula_vazia(c)).to_series()
            motivo = "vazia"
        elif check == "in_range":
            if not (s.dtype.is_numeric() or s.dtype.is_temporal()):
                raise ValueError(f"'{c}' é texto; converta para número ou data antes de verificar a faixa")
            falhas = pl.Series([False] * df.height)
            if minimo is not None:
                falhas = falhas | (s < minimo).fill_null(False)
            if maximo is not None:
                falhas = falhas | (s > maximo).fill_null(False)
            de = "…" if minimo is None else minimo
            ate = "…" if maximo is None else maximo
            motivo = f"fora da faixa {de} a {ate}"
        else:  # matches
            texto = s.cast(pl.String)
            falhas = (texto.is_not_null() & ~texto.str.contains(f"^(?:{padrao})$")).fill_null(False)
            motivo = "fora do padrão"
        if falhas.any():
            indices = falhas.arg_true()
            total = int(falhas.sum())
            linhas = [int(i) + 1 for i in indices[:5]]
            if motivo == "vazia":
                motivo = "vazia" if total == 1 else "vazias"
            quantas = f"{total} {'linha' if total == 1 else 'linhas'}"
            raise _reprovada(
                f"'{c}' tem {quantas} {motivo}: {_linhas_br(linhas, total)}",
                check,
                [c],
                total,
                linhas,
                [repr(s[int(i)]) for i in indices[:5]],
            )
    return df.lazy()


@register_op
class Assert(Op):
    """Verificação que não muda os dados: a receita para com mensagem se o
    arquivo vier diferente do esperado. ``not_null`` (sem célula vazia),
    ``unique`` (as colunas juntas não se repetem), ``in_range`` (entre
    ``min`` e ``max``), ``matches`` (casa com a expressão regular
    ``pattern``; não roda no Power BI, que não tem expressão regular) e
    ``row_count_min`` (pelo menos ``min_rows`` linhas)."""

    op: Literal["assert"]
    m_label = "Verificação"
    full_checkpoint = True  # lê a tabela inteira
    check: Verificacao
    cols: list[str] = Field(default_factory=list)
    min: float | date | None = None
    max: float | date | None = None
    pattern: str | None = None
    min_rows: int | None = Field(default=None, ge=1)

    python_helpers = (verificar_lf,)
    m_helpers = {"WolfzVazia": _M_VAZIA}  # noqa: RUF012
    examples = (
        {
            "step": {"check": "not_null", "cols": ["cpf"]},
            "input": {"cpf": ["1", "2"], "nome": ["a", None]},
            "expected": {"cpf": ["1", "2"], "nome": ["a", None]},
        },
        {
            "step": {"check": "unique", "cols": ["uf", "ano"]},
            "input": {"uf": ["ES", "ES", "RJ"], "ano": ["2024", "2025", "2024"]},
            "expected": {"uf": ["ES", "ES", "RJ"], "ano": ["2024", "2025", "2024"]},
        },
        {
            "step": {"check": "in_range", "cols": ["v"], "min": 0, "max": 100},
            "input": {"v": [0.0, 50.5, None, 100.0]},
            "expected": {"v": [0.0, 50.5, None, 100.0]},
        },
        {
            "step": {"check": "matches", "cols": ["cep"], "pattern": r"\d{8}"},
            "input": {"cep": ["29100000", None]},
            "expected": {"cep": ["29100000", None]},
        },
        {
            "step": {"check": "row_count_min", "min_rows": 2},
            "input": {"a": ["x", "y", "z"]},
            "expected": {"a": ["x", "y", "z"]},
        },
    )

    @model_validator(mode="after")
    def _parametros(self) -> Assert:
        if self.check == "row_count_min":
            if self.min_rows is None:
                raise ValueError("row_count_min precisa de min_rows")
            return self
        if not self.cols:
            raise ValueError(f"{self.check} precisa de cols")
        if self.check == "in_range" and self.min is None and self.max is None:
            raise ValueError("in_range precisa de min, max ou os dois")
        if self.check == "matches":
            if not self.pattern:
                raise ValueError("matches precisa de pattern")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"pattern inválida: {exc}") from None
        return self

    def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        return verificar_lf(lf, self.check, self.cols, self.min, self.max, self.pattern, self.min_rows)

    @staticmethod
    def _py_limite(v: float | date | None) -> str:
        # date(...) e não datetime.date(...): no script, ``date`` vem importado.
        return f"date({v.year}, {v.month}, {v.day})" if isinstance(v, date) else repr(v)

    def to_python(self) -> str:
        return (
            f"lf = verificar_lf(lf, {self.check!r}, {self.cols!r}, {self._py_limite(self.min)}, "
            f"{self._py_limite(self.max)}, {self.pattern!r}, {self.min_rows!r})"
        )

    def _m_limite(self, v: float | date) -> str:
        return f"#date({v.year}, {v.month}, {v.day})" if isinstance(v, date) else m_value(v)

    def to_m(self, prev: str, name: str) -> str:
        if self.check == "matches":
            # Sem expressão regular no M: a verificação fica só no WolfzBR e no script.
            return f"{name} = {prev} /* matches não é verificado no Power Query (sem expressão regular) */"
        if self.check == "row_count_min":
            falhas = f"if Table.RowCount({prev}) < {self.min_rows} then 1 else 0"
            mensagem = (
                f'"a tabela tem " & Text.From(Table.RowCount({prev})) & " linhas; o mínimo é {self.min_rows}"'
            )
        elif self.check == "unique":
            distintas = f"Table.RowCount(Table.Distinct(Table.SelectColumns({prev}, {m_list(self.cols)})))"
            falhas = f"Table.RowCount({prev}) - {distintas}"
            mensagem = f'{m_text(", ".join(self.cols))} & " se repete em " & Text.From(falhas) & " linhas"'
        else:
            if self.check == "not_null":
                testes = [f"WolfzVazia({m_field(c)})" for c in self.cols]
                motivo = "vazias"
            else:
                faixa = []
                if self.min is not None:
                    faixa.append(f"v < {self._m_limite(self.min)}")
                if self.max is not None:
                    faixa.append(f"v > {self._m_limite(self.max)}")
                cond = " or ".join(faixa)
                testes = [f"(let v = {m_field(c)} in v <> null and ({cond}))" for c in self.cols]
                motivo = "fora da faixa"
            falhas = f"Table.RowCount(Table.SelectRows({prev}, each List.AnyTrue({{{', '.join(testes)}}})))"
            mensagem = f'{m_text(", ".join(self.cols))} & ": " & Text.From(falhas) & " linhas {motivo}"'
        detalhe = f"[Passo = {m_text(self.id)}, Verificacao = {m_text(self.check)}]"
        return (
            f"{name} = let\n"
            f"        falhas = {falhas},\n"
            f"        mensagem = {mensagem}\n"
            "    in\n"
            '        if falhas > 0 then error Error.Record("WolfzBR: verificação reprovada", '
            f"mensagem, {detalhe})\n"
            f"        else {prev}"
        )

"""Sugestões que faltavam (F7 da 1.1), S1 e o telefone que guarda o original
(ADR-14). Cada sugestão nova diz o que achou, começando pela coluna, e o que
muda ("Muda N células; N viram vazio."), com exemplo de formato, nunca de
valor da planilha. Nenhuma volta depois de aceita.
"""

import json

import polars as pl
import pytest

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.engine import StepError, collect
from wolfz.core.recipe import dumps_recipe, recipe_from_dict
from wolfz.core.suggest import Suggestion, etapa, suggest
from wolfz.export.dados import celulas_formula, neutralizar_formulas


def _df(**cols) -> pl.DataFrame:
    return pl.DataFrame(cols, schema=dict.fromkeys(cols, pl.String))


def _receita(passos, versao="1.1"):
    return recipe_from_dict(
        {
            "wolfz_version": versao,
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )


def _aplica(df, passos):
    return collect(_receita(passos), df.lazy())


def _regra(df, nome, steps=(), **kw) -> list[Suggestion]:
    return [s for s in suggest(df, steps=steps, **kw) if s.rule == nome]


def _aceita_tudo(df, rodadas=6, **kw):
    """O "Aceitar todas" da interface: uma etapa por vez, só as que entram nele."""
    passos: list[dict] = []
    vistas: set[str] = set()
    for _ in range(rodadas):
        sugestoes = [
            s for s in suggest(_aplica(df, passos), steps=passos, **kw) if s.kind == "passo" and s.accept_all
        ]
        if not sugestoes:
            break
        primeira = min(etapa(s.order) for s in sugestoes)
        lote = [s for s in sugestoes if etapa(s.order) == primeira]
        repetidas = {s.id for s in lote} & vistas
        assert not repetidas, f"sugestão voltou depois de aceita: {repetidas}"
        vistas |= {s.id for s in lote}
        passos += [p for s in lote for p in s.steps]
    return passos, _aplica(df, passos)


# ---------------------------------------------------------------------------
# F7.1 Sim/não
# ---------------------------------------------------------------------------


def test_sim_nao():
    df = _df(Ativo=["Sim", "Não", "S", "N", "sim"] * 4)
    [s] = _regra(df, "booleano")
    assert s.steps == ({"op": "parse_bool_br", "cols": ["Ativo"]},)
    assert s.reason.startswith("A coluna Ativo tem só Sim e Não (ou S e N).")
    assert s.reason.endswith("Muda 20 células; nenhuma fica vazia.")


@pytest.mark.parametrize("valores", [["x", "y"] * 5, ["X", None] * 5, ["Sim"] * 10, ["ok", "1"] * 5])
def test_nao_e_sim_nao(valores):
    assert not _regra(_df(c=valores), "booleano")


# ---------------------------------------------------------------------------
# F7.2 UF por extenso
# ---------------------------------------------------------------------------


def test_uf_por_extenso():
    df = _df(Estado=["SP", "São Paulo", "sao paulo", "RJ", "Rio de Janeiro", "ES"] * 4)
    [s] = _regra(df, "uf")
    assert s.steps == ({"op": "normalize_uf", "cols": ["Estado"]},)
    assert "(SP, São Paulo, sao paulo)" in s.reason and s.reason.endswith("nenhuma fica vazia.")
    assert not _regra(df, "variacao_categoria")  # não sugere caixa na coluna de UF
    _, saida = _aceita_tudo(df)
    assert set(saida["Estado"]) == {"SP", "RJ", "ES"}


def test_uf_com_valor_que_nao_e_uf():
    estados = ["SP", "São Paulo", "RJ", "Rio de Janeiro", "ES", "Bahia", "MG", "Pará", "RS", "PR"]
    df = _df(UF=[*estados * 3, "Exterior"])  # 1 de 11 distintos: 91%, abaixo de 95%
    assert not _regra(df, "uf")
    df = _df(
        UF=[
            *[e for e in estados for _ in range(3)] * 2,
            *[
                "AC",
                "AL",
                "AP",
                "AM",
                "CE",
                "DF",
                "GO",
                "MA",
                "MT",
                "MS",
                "PB",
                "PE",
                "PI",
                "RN",
                "RO",
                "RR",
                "SC",
                "SE",
                "TO",
            ],
            "Exterior",
        ]
    )
    [s] = _regra(df, "uf")
    assert s.reason.endswith("1 vira vazio porque não são UF.")
    assert "Exterior" not in s.reason


def test_uf_ja_em_sigla_nao_sugere():
    assert not _regra(_df(uf=["SP", "RJ", "ES"] * 5), "uf")


# ---------------------------------------------------------------------------
# F7.3 Telefone, ADR-14
# ---------------------------------------------------------------------------


def test_telefone_sem_invalido_nao_cria_coluna():
    df = _df(Telefone=["(27) 99999-0000", "27999990000", "+55 21 98888-7777"] * 4)
    [s] = _regra(df, "telefone")
    assert s.steps == ({"op": "clean_phone", "cols": ["Telefone"]},)
    assert s.reason.endswith("nenhuma fica vazia.")
    _, saida = _aceita_tudo(df)
    assert "Telefone_original" not in saida.columns


def test_telefone_com_invalido_guarda_o_original_so_nas_anuladas():
    df = _df(Celular=["(27) 99999-0000", "(20) 3333-4444", "27999990000", "21988887777"] * 3)
    [s] = _regra(df, "telefone")
    assert s.steps == ({"op": "clean_phone", "cols": ["Celular"], "add_original_col": True},)
    assert "3 números têm DDD que não existe" in s.reason and "coluna Celular_original" in s.reason
    assert "3333" not in s.reason  # o exemplo é de formato, não valor
    passos, saida = _aceita_tudo(df)
    assert saida["Celular_original"].to_list() == [None, "(20) 3333-4444", None, None] * 3
    assert saida["Celular"].null_count() == 3
    assert sum(p["op"] == "clean_phone" for p in passos) == 1  # nem a coluna nova é sugerida de novo


def test_coluna_de_telefone_nao_vira_numero():
    df = _df(fone=["27999990000", "21988887777", "11977776666"] * 4)
    assert not [s for s in suggest(df) if s.rule in ("inteiro", "decimal_br")]


def test_add_original_col_ja_existente_e_erro():
    df = _df(tel=["(20) 3333-4444"], tel_original=["x"])
    with pytest.raises(StepError, match="tel_original"):
        _aplica(df, [{"op": "clean_phone", "cols": ["tel"], "add_original_col": True}])


def test_add_original_col_grava_1_1_e_sem_ele_continua_1_0():
    com = json.loads(dumps_recipe(_receita([{"op": "clean_phone", "cols": ["t"], "add_original_col": True}])))
    sem = json.loads(dumps_recipe(_receita([{"op": "clean_phone", "cols": ["t"]}], versao="1.0")))
    assert com["wolfz_version"] == "1.1" and com["steps"][0]["add_original_col"] is True
    assert sem["wolfz_version"] == "1.0" and "add_original_col" not in sem["steps"][0]


# ---------------------------------------------------------------------------
# F7.4 Telefone não é fórmula (R7, D10)
# ---------------------------------------------------------------------------


def test_e164_nao_conta_como_formula():
    df = pl.DataFrame(
        {"tel": ["+5521987654321", "+55 (21) 98765-4321", "\t+5521"], "x": ['+HYPERLINK("x")', "=1+1", "ok"]}
    )
    assert celulas_formula(df) == 4  # todas menos o E.164 puro
    neutro = neutralizar_formulas(df)
    assert neutro["tel"][0] == "'+5521987654321"  # o neutralizador não muda (byte a byte igual ao de antes)


# ---------------------------------------------------------------------------
# F7.5 Município do IBGE (R11: sem rede)
# ---------------------------------------------------------------------------


def test_municipio_do_ibge_sem_rede(monkeypatch):
    import socket

    def proibido(*_a, **_k):
        raise AssertionError("tentou usar a rede")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "getaddrinfo", proibido)
    df = _df(
        Cidade=[
            "Vitória",
            "Serra",
            "Vila Velha",
            "Cariacica",
            "Serrra",
            "Linhares",
            "Colatina",
            "Guarapari",
            "Aracruzz",
            "Viana",
        ]
        * 2,
        UF=["ES"] * 20,
    )
    [s] = _regra(df, "municipio")
    assert s.steps == ({"op": "normalize_municipio", "col": "Cidade", "uf_col": "UF"},)
    assert s.reason.endswith("4 precisam da sua revisão.")  # 2 grafias, 2 vezes cada
    passos, _ = _aceita_tudo(df)
    assert sum(p["op"] == "normalize_municipio" for p in passos) == 1  # sem loop pelas colunas novas


def test_municipio_com_pouco_casamento_nao_sugere():
    assert not _regra(_df(cidade=["Xyz", "Abc", "Vitória"] * 5), "municipio")


# ---------------------------------------------------------------------------
# F7.6 "Mil Reais"
# ---------------------------------------------------------------------------


def test_mil_reais_no_titulo():
    df = pl.DataFrame({"Conta": ["a", "b"], "Receita": [1.5, 2.0], "Ano": [2024, 2025]})
    [s] = _regra(df, "unidade", titulos=[("Valores em Mil Reais", "A2")])
    assert s.steps == ({"op": "scale_by_unit", "cols": ["Receita"], "unit": "Valores em Mil Reais"},)
    assert '"Valores em Mil Reais" (célula A2)' in s.reason
    assert s.reason.endswith("Muda 2 células nas colunas Receita; nenhuma fica vazia.")
    assert _aplica(df, list(s.steps))["Receita"].to_list() == [1500.0, 2000.0]
    assert not _regra(df, "unidade", steps=list(s.steps), titulos=[("Valores em Mil Reais", "A2")])


def test_mil_reais_no_nome_da_coluna():
    df = pl.DataFrame({"Receita (R$ mil)": [1.5], "Custo": [2.0]})
    [s] = _regra(df, "unidade")
    assert s.steps == ({"op": "scale_by_unit", "cols": ["Receita (R$ mil)"], "unit": "Receita (R$ mil)"},)


def test_sem_unidade_nao_sugere():
    df = pl.DataFrame({"Receita": [1.5]})
    assert not _regra(df, "unidade", titulos=[("Vendas 2025", "A1")])


# ---------------------------------------------------------------------------
# F7.7 fill_down
# ---------------------------------------------------------------------------


def _dre():
    cc_col, g_col, conta = [], [], []
    for cc in ("CC1", "CC2"):
        primeiro_cc = True
        for g, contas in (("Receita", ["Vendas", "Serviços"]), ("Custos", ["CMV", "Pessoal"])):
            primeiro = True
            for c in contas:
                cc_col.append(cc if primeiro_cc else None)
                g_col.append(g if primeiro else None)
                conta.append(c)
                primeiro = primeiro_cc = False
    n = len(conta)
    return _df(
        **{
            "Centro de Custo": cc_col,
            "Grupo": g_col,
            "Conta": conta,
            "Jan": [str(i) for i in range(n)],
            "Fev": [str(i) for i in range(n)],
            "Obs": [None] * (n - 1) + ["x"],
        }
    )


def test_fill_down_nas_colunas_de_grupo():
    [s] = _regra(_dre(), "hierarquia")
    assert s.steps == ({"op": "fill_down", "cols": ["Centro de Custo", "Grupo"]},)
    assert s.reason.startswith("As colunas Centro de Custo e Grupo só estão preenchidas na primeira linha")


def test_fill_down_vem_antes_de_despivotar_e_de_dedupe():
    """O "Aceitar todas" vai uma etapa por vez: o preencher para baixo está
    na de limpeza, antes da etapa que despivota ou tira duplicadas."""
    from wolfz.core.suggest import FORMA

    [s] = _regra(_dre(), "hierarquia")
    assert etapa(s.order) < etapa(FORMA)
    _, saida = _aceita_tudo(_dre())
    assert saida["Centro de Custo"].null_count() == 0


@pytest.mark.parametrize("op", ["unpivot", "dedupe"])
def test_fill_down_nao_vem_depois_de_unpivot_ou_dedupe(op):
    passo = {"op": op, "index": ["Conta"]} if op == "unpivot" else {"op": op}
    assert not _regra(_dre(), "hierarquia", steps=[{"id": "s1", **passo}])


def test_coluna_de_observacao_nao_e_hierarquia():
    df = _df(Conta=["a", "b", "c", "d"], Valor=["1", "2", "3", "4"], Obs=["x", None, None, None])
    assert not _regra(df, "hierarquia")


# ---------------------------------------------------------------------------
# F7.8 NULL e N/A
# ---------------------------------------------------------------------------


def test_marcadores_de_nulo():
    df = _df(
        pedido=[str(i) for i in range(14)], coupon=["BEMVINDO10", "NULL", "N/A", "", "PROMO", "NULL", "-"] * 2
    )
    [s] = _regra(df, "marcador_nulo")
    assert {p["old"] for p in s.steps} == {"NULL", "N/A"}  # o '-' não
    assert all(
        p == {"op": "replace", "cols": ["coupon"], "old": p["old"], "new": None, "whole": True}
        for p in s.steps
    )
    assert s.reason.endswith("6 células viram vazio.")
    _, saida = _aceita_tudo(df)
    assert "NULL" not in saida["coupon"].to_list() and "-" in saida["coupon"].to_list()


# ---------------------------------------------------------------------------
# F7.9 Data que faltou (base 27)
# ---------------------------------------------------------------------------


def test_data_com_serial_misturado():
    datas = [
        "31/01/2024",
        "2024-02-15",
        "15-jan-2024",
        "01/03/24",
        "45300",
        "12/04/2024",
        "2024-05-01",
        "45400",
        "20/06/2024",
        "21/07/2024",
    ]
    df = _df(**{"Data Ocorrência": datas * 3, "Código": ["45300"] * 30})
    [s] = _regra(df, "data")
    assert "Data Ocorrência" in s.steps[0]["cols"] and "Código" not in s.steps[0]["cols"]


# ---------------------------------------------------------------------------
# S1 dedupe sem chave
# ---------------------------------------------------------------------------


def test_dedupe_sem_chave_fica_fora_do_aceitar_todas():
    df = _df(
        data=["01/01/2025", "01/01/2025", "02/01/2025"] * 4,
        produto=["A", "A", "B"] * 4,
        valor=["10,00", "10,00", "5,00"] * 4,
    )
    [s] = _regra(df, "duplicadas")
    assert s.accept_all is False and s.to_dict()["accept_all"] is False
    assert s.reason.startswith("Encontramos 10 linhas repetidas (83%).")
    assert 'Esta sugestão não entra no "Aceitar todas".' in s.reason
    passos, _ = _aceita_tudo(df)
    assert "dedupe" not in [p["op"] for p in passos]


def test_dedupe_com_chave_continua_no_aceitar_todas():
    df = _df(ID=["1", "1", "2"], valor=["10", "10", "5"])
    [s] = _regra(df, "duplicadas")
    assert s.accept_all is True

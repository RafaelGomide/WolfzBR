"""Sugestões corrigidas na 1.0.1, a partir do teste de fogo com 30 bases de
empresa: cada teste é um caso em que o "aceitar todas" estragava dado bom."""

import polars as pl

import wolfz.ops  # noqa: F401  (registra o catálogo)
from wolfz.core.engine import collect
from wolfz.core.recipe import recipe_from_dict
from wolfz.core.suggest import Suggestion, suggest


def _df(**cols) -> pl.DataFrame:
    return pl.DataFrame(cols, schema=dict.fromkeys(cols, pl.String))


def _regra(df: pl.DataFrame, nome: str, steps=()) -> list[Suggestion]:
    return [s for s in suggest(df, steps=steps) if s.rule == nome]


def _aplica(df: pl.DataFrame, passos: list[dict]) -> pl.DataFrame:
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "csv"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )
    return collect(receita, df.lazy())


def _aceita_tudo(df: pl.DataFrame, rodadas: int = 5) -> tuple[list[dict], pl.DataFrame]:
    """O "aceitar todas" da interface, uma etapa por vez, até não sobrar sugestão."""
    from wolfz.core.suggest import etapa

    passos: list[dict] = []
    for _ in range(rodadas):
        sugestoes = [s for s in suggest(_aplica(df, passos), steps=passos) if s.kind == "passo"]
        if not sugestoes:
            break
        primeira = min(etapa(s.order) for s in sugestoes)
        passos += [p for s in sugestoes if etapa(s.order) == primeira for p in s.steps]
    return passos, _aplica(df, passos)


def test_acento_e_consertado_antes_de_tirar_os_espacos():
    """'Thaís' estragado tem um hífen suave invisível ('ThaÃ\\xads'); o trim
    tirava o invisível antes do conserto, e o nome ficava 'ThaÃs'."""
    estragado = "Thaís Assunção ".encode().decode("latin-1")
    df = _df(nome=[estragado, "Ana  Silva", "Íris"])
    passos, saida = _aceita_tudo(df)
    assert [p["op"] for p in passos][:2] == ["fix_mojibake", "trim"]
    assert saida["nome"].to_list() == ["Thaís Assunção", "Ana Silva", "Íris"]


def test_99999_numa_coluna_de_identificador_nao_e_sentinela():
    df = _df(resposta=[str(i) for i in range(99_970, 100_000)], nota=["3"] * 30)
    assert not _regra(df, "sentinela")


def test_sugestao_de_cpf_e_cnpj_nao_volta_depois_de_aceita():
    df = _df(doc=["529.982.247-25", "11.222.333/0001-81", "52998224725", "11222333000181", "529.982.247-25"])
    passos, _ = _aceita_tudo(df)
    assert [p["op"] for p in passos].count("clean_cpf_cnpj") == 1


def test_numero_com_forma_de_reais_sem_r_cifrao_nao_vira_moeda():
    """'0,09' num Score e '7,62' em Horas viravam R$ no Power BI."""
    df = _df(score=["0,09", "0,45", "1,00"], horas=["7,62", "8,00", "9,15"], valor=["1,50", "2,00", "3,99"])
    (moeda,) = _regra(df, "moeda")
    assert moeda.steps[0]["cols"] == ["valor"]
    (numero,) = _regra(df, "decimal_br")
    assert numero.steps[0]["cols"] == ["score", "horas"]


def test_r_cifrao_no_valor_e_moeda_qualquer_que_seja_o_nome():
    (s,) = _regra(_df(x=["R$ 1,50", "R$ 2,00"]), "moeda")
    assert s.steps[0]["cols"] == ["x"]


def test_traco_sozinho_nao_e_sinal_do_ibge():
    """Numa planilha de transferências, '-' é sem valor, não zero absoluto."""
    valores = ["1.234,56", "-", *(f"{i},50" for i in range(20)), "N/D"]
    df = _df(transferencia=valores)
    assert not _regra(df, "sinais_ibge")
    (s,) = _regra(df, "decimal_br")
    saida = _aplica(df, list(s.steps))["transferencia"].to_list()
    assert saida[:3] == [1234.56, None, 0.5] and saida[-1] is None


def test_traco_numa_tabela_com_sinais_do_ibge_continua_zero():
    df = _df(area=["10", "-", "..."], producao=["5", "X", "-"])
    (s,) = _regra(df, "sinais_ibge")
    assert s.steps[0]["cols"] == ["area", "producao"]


def test_numero_longo_que_veio_do_excel_ganha_aviso():
    """Chave de NF-e de 44 dígitos guardada como número: os dígitos do fim
    já não são os da fonte."""
    perdida = str(int(float("81811799688286203076440255313807307084462398")))
    df = _df(chave=[perdida, "33151871418247924951336892331571800099824487"])
    (s,) = _regra(df, "precisao_perdida")
    assert s.kind == "aviso" and perdida in s.reason
    assert not _regra(_df(chave=["33151871418247924951336892331571800099824487"]), "precisao_perdida")


def test_exemplo_do_codigo_com_zero_tem_o_zero():
    df = _df(cod=["5703", "0123", "0456"])
    (s,) = _regra(df, "codigo_zero_esquerda")
    assert "'0123'" in s.reason


def test_cpf_com_matricula_na_tabela_nao_vira_verificacao_de_unico():
    df = _df(
        matricula=["001", "002", "003"],
        cpf=["52998224725", "11144477735", "12345678909"],
        cep=["1", "2", "3"],
    )
    regras = _regra(df, "verificar_unicos", steps=[{"op": "trim", "cols": ["matricula"]}])
    assert [s.cols for s in regras] == [("matricula",)]


def test_duas_medidas_na_mesma_numeracao_nao_despivotam():
    """Meta e Realizado por trimestre: despivotar uma deixava a outra repetida,
    e a segunda despivotada multiplicava as linhas por 4."""
    df = _df(
        vendedor=["Ana", "Bia"],
        **{f"{t}º Trimestre_{m}": ["10", "20"] for t in range(1, 5) for m in ("Meta", "Realizado")},
    )
    assert not _regra(df, "series_lado_a_lado")
    _, saida = _aceita_tudo(df)
    assert saida.height == 2


def test_tabela_despivotada_nao_e_despivotada_de_novo_nem_deduplicada():
    """DRE já despivotada, com centro de custo vazio: linhas iguais vêm da
    forma da tabela, não de duplicação (a deduplicação apagava lançamentos)."""
    passos = [{"op": "unpivot", "index": ["conta"], "variable_name": "mes", "value_name": "valor"}]
    df = _df(conta=["Pessoal", "Pessoal"], mes=["jan", "jan"], valor=["1", "1"], **{"1º Lote": ["1", "2"]})
    df = df.with_columns(pl.lit("1").alias("2º Lote"), pl.lit("1").alias("3º Lote"))
    nomes = {s.rule for s in suggest(df, steps=passos)}
    assert "duplicadas" not in nomes and "series_lado_a_lado" not in nomes


def test_coluna_constante_com_hora_ou_numero_fica():
    df = _df(saida_almoco=["12:00"] * 10, moeda=["BRL"] * 10, v=[str(i) for i in range(10)])
    (s,) = _regra(df, "coluna_constante")
    assert s.steps == ({"op": "drop_cols", "cols": ["moeda"]},)

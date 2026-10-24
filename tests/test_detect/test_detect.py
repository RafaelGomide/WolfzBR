import polars as pl
import pytest

from wolfz.core.detect import classify, detect_structure, row_metrics
from wolfz.core.detect.metrics import TEXTO, VALOR, VAZIO
from wolfz.core.ingest.cells import CellType
from wolfz.core.ingest.structure import MergedRange, SheetStructure, sample_windows


def grade(linhas: list[list], primeira_coluna: str = "A") -> pl.DataFrame:
    """Grade no formato do ``raw``: colunas com letra, tudo texto."""
    from wolfz.core.ingest.cells import column_index, column_letter

    largura = max(len(r) for r in linhas)
    inicio = column_index(primeira_coluna)
    cols = [column_letter(inicio + j) for j in range(largura)]
    dados = {c: [(r[j] if j < len(r) else None) for r in linhas] for j, c in enumerate(cols)}
    return pl.DataFrame(dados, schema=dict.fromkeys(cols, pl.String))


RELATORIO = [
    ["Prefeitura de Santa Luzia"],
    ["Receita 2025"],
    [None],
    ["Código", "Descrição", "Previsto", "Arrecadado"],
    ["1.1", "IPTU", "1.234,56", "1.000,00"],
    ["1.2", "ISS", "R$ 10,00", "(5,00)"],
    ["1.3", "ITBI", "-", "2.500"],
    ["Total", None, "1.244,56", "3.495,00"],
    [None],
    ["Fonte: sistema de contabilidade"],
    ["Emitido em 05/01/2026"],
]


# ---------------------------------------------------------------------------
# Métricas por linha (F1.C1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, VAZIO),
        ("  ", VAZIO),
        ("12", VALOR),
        ("1.234,56", VALOR),
        ("95 626 753", VALOR),
        ("R$ 1.234,56", VALOR),
        ("R$ -", VALOR),
        ("(10,00)", VALOR),
        ("1.234,56-", VALOR),
        ("10.234,56 D", VALOR),
        ("12,5%", VALOR),
        ("31/12/2024", VALOR),
        ("31.12.9999", VALOR),
        ("2024-01-31 00:00:00", VALOR),
        ("20210315", VALOR),
        ("-", VALOR),
        ("...", VALOR),
        ("X", VALOR),
        ("#N/D", VALOR),
        ("São Paulo", TEXTO),
        ("jan/2024", TEXTO),
        ("123.456.789-09", TEXTO),
        ("Total", TEXTO),
    ],
)
def test_classify(valor, esperado):
    assert classify(grade([[valor]]))["A"][0] == esperado


def test_tipo_do_arquivo_so_promove_a_valor():
    df = grade([["texto", "1.5"], ["abc", "X"]])
    estrutura = SheetStructure("x", types={(0, 0): CellType.NUMBER, (1, 1): CellType.TEXT})
    kinds = classify(df, estrutura)
    assert kinds.row(0) == (VALOR, VALOR)  # número gravado como número
    assert kinds.row(1) == (TEXTO, VALOR)  # 'X' gravado como texto continua sinal do IBGE


def test_tipo_do_arquivo_nao_preenche_celula_vazia():
    df = grade([[None]])
    assert classify(df, SheetStructure("x", types={(0, 0): CellType.NUMBER}))["A"][0] == VAZIO


def test_row_metrics():
    df = grade([[None, "Total", "1.234,56", None], ["a", "b", "c", "d"]], primeira_coluna="B")
    estrutura = SheetStructure("x", bold=[(0, 2)], merged=[MergedRange(1, 1, 1, 4)])
    m0, m1 = row_metrics(df, estrutura)
    assert (m0.filled, m0.values, m0.texts, m0.bold, m0.merged) == (2, 1, 1, True, False)
    assert (m0.first_col, m0.last_col) == (2, 3)  # C e D (a grade começa em B)
    assert m0.filled_pct == 0.5 and m0.value_pct == 0.5 and m0.text_pct == 0.5
    assert (m1.texts, m1.merged, m1.bold) == (4, True, False)


def test_row_metrics_grade_vazia():
    assert row_metrics(pl.DataFrame()) == []
    vazia = row_metrics(grade([[None]]))[0]
    assert (vazia.filled, vazia.value_pct, vazia.text_pct, vazia.first_col) == (0, 0.0, 0.0, None)


# ---------------------------------------------------------------------------
# Região, cabeçalho, totais, notas (F1.C2–C5)
# ---------------------------------------------------------------------------


def test_relatorio_completo():
    det = detect_structure(grade(RELATORIO))
    d = det.to_dict()
    assert d["cabecalho"] == [4, 4]
    assert d["dados"] == [5, 8]
    assert d["colunas"] == ["A", "D"]
    assert d["totais"] == [8]
    assert d["titulo"] == ["Prefeitura de Santa Luzia", "Receita 2025"]
    assert d["notas"] == ["Fonte: sistema de contabilidade", "Emitido em 05/01/2026"]
    assert det.labels[2] == "Previsto"


def test_tabela_so_de_texto_usa_a_primeira_linha():
    det = detect_structure(grade([["Nome", "Cidade"], ["Ana", "Vitória"], ["Bia", "Serra"]]))
    assert (det.header_row, det.first_row, det.last_row) == (0, 1, 2)


def test_tabela_sem_cabecalho():
    df = grade([["001", "20210315", "10"], ["002", "20200101", "20"]])
    det = detect_structure(df)
    assert det.header_row is None
    assert (det.first_row, det.last_row) == (0, 1)
    assert det.to_dict()["cabecalho"] is None
    assert det.to_steps() == [{"op": "select_range", "start": "A1", "end_detect": "auto"}]


def test_cabecalho_esparso_acima_dos_dados():
    # Cabeçalho com menos da metade das colunas: fica fora do bloco denso,
    # mas é a linha de texto logo acima dos dados.
    df = grade([["Município", None, None, None], ["Vitória", "1", "2", "3"], ["Serra", "4", "5", "6"]])
    det = detect_structure(df)
    assert (det.header_row, det.first_row) == (0, 1)


def test_ano_como_rotulo_de_coluna():
    df = grade([["Município", "2019", "2020"], ["Vitória", "10", "-"], ["Serra", "3", "4"]])
    assert detect_structure(df).header_row == 0


@pytest.mark.parametrize("mes", ["1997-01-01 00:00:00", "1997-01-01", "1997-01-01 00:00"])
def test_data_como_rotulo_de_coluna(mes):
    # Série com meses nas colunas: o Excel entrega a célula de data como ISO.
    linhas = [
        ["Tabela 1.1. Resultado primário"],
        ["Discriminação", mes, "1997-02-01 00:00:00", "1997-03-01 00:00:00"],
        ["1. Receita total", "12290.48", "11596.25", "13069.05"],
        ["1.1 Receita administrada", "7771.68", "7412.76", "8772.09"],
        ["2. Transferências", "1520.3", "1622.8", "1700.1"],
    ]
    det = detect_structure(grade(linhas))
    assert (det.header_row, det.first_row) == (1, 2)


def test_coluna_de_datas_nao_vira_cabecalho():
    linhas = [["2024-01-01", "10"], ["2024-02-01", "12"], ["2024-03-01", "9"]]
    assert detect_structure(grade(linhas)).first_row == 0


def test_bloco_maior_vence():
    linhas = [["A", "B"], ["1", "2"], [None], [None], ["C", "D"], ["1", "2"], ["3", "4"], ["5", "6"]]
    det = detect_structure(grade(linhas))
    assert (det.header_row, det.first_row, det.last_row) == (4, 5, 7)


def test_linha_vazia_isolada_nao_quebra_a_regiao():
    linhas = [["Ano", "Valor"], ["2020", "1,5"], ["2021", "2,5"], [None], ["2022", "3,5"]]
    det = detect_structure(grade(linhas))
    assert (det.first_row, det.last_row) == (1, 4)


def test_linhas_de_secao_nao_quebram_a_regiao():
    linhas = [
        ["Item", "Qtd", "Valor"],
        ["Bovino", "10", "1,5"],
        ["Produtos", None, None],
        ["Leite", "3", "2,5"],
        ["Ovos", "4", "1,0"],
    ]
    det = detect_structure(grade(linhas))
    assert (det.first_row, det.last_row) == (1, 4)


@pytest.mark.parametrize(
    "rotulo", ["Total", "TOTAL GERAL", "Subtotal Saúde", "Sub-total", "Soma", "MILHO - TOTAL", "total"]
)
def test_totais_por_palavra_chave(rotulo):
    linhas = [["Item", "Valor"], ["a", "1"], ["b", "2"], [rotulo, "3"], ["c", "4"]]
    det = detect_structure(grade(linhas))
    assert det.totals == [3]


@pytest.mark.parametrize("rotulo", ["Totalmente novo", "Custo total do projeto"])
def test_texto_que_nao_e_total(rotulo):
    det = detect_structure(grade([["Item", "Valor"], ["a", "1"], [rotulo, "3"], ["c", "4"]]))
    assert det.totals == []


def test_totais_por_negrito_raro():
    linhas = [
        ["Função", "Valor"],
        ["10 - Saúde", "3"],
        ["301", "1"],
        ["302", "2"],
        ["303", "0"],
        ["304", "0"],
    ]
    df = grade(linhas)
    estrutura = SheetStructure(
        "x", formatting=True, bold=[(0, 0), (1, 0)], sampled_rows=sample_windows(df.height)
    )
    assert detect_structure(df, estrutura).totals == [1]


def test_negrito_frequente_nao_marca_total():
    linhas = [["Item", "Valor"], ["a", "1"], ["b", "2"], ["c", "3"]]
    df = grade(linhas)
    estrutura = SheetStructure(
        "x", formatting=True, bold=[(1, 0), (2, 0)], sampled_rows=sample_windows(df.height)
    )
    assert detect_structure(df, estrutura).totals == []


def test_negrito_sem_formatacao_lida_e_ignorado():
    df = grade([["Item", "Valor"], ["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"]])
    estrutura = SheetStructure("x", formatting=False, bold=[(2, 0)], sampled_rows=sample_windows(df.height))
    assert detect_structure(df, estrutura).totals == []


def test_nada_detectado():
    assert detect_structure(grade([[None, None]])) is None
    assert detect_structure(grade([["sozinho"]])) is not None


# ---------------------------------------------------------------------------
# Mesclagem vertical (F1.C6) e passos (F1.C7)
# ---------------------------------------------------------------------------


def _vendas():
    linhas = [
        ["Região", "UF", "Vendas"],
        ["Sudeste", "ES", "10"],
        [None, "MG", "20"],
        ["Sul", "PR", "30"],
        [None, "SC", "40"],
        ["Total", None, "100"],
    ]
    df = grade(linhas)
    # A2:A3 e A4:A5 mescladas; A1 mesclada com A0 seria cabeçalho e não conta.
    estrutura = SheetStructure("x", merged=[MergedRange(1, 0, 2, 0), MergedRange(3, 0, 4, 0)])
    return df, estrutura


def test_mesclagem_vertical_sugere_fill_down():
    df, estrutura = _vendas()
    det = detect_structure(df, estrutura)
    assert det.fill_down == [0]
    assert det.to_dict()["fill_down"] == ["A"]


def test_mesclagem_no_cabecalho_nao_sugere_fill_down():
    df = grade([["Município", "Área"], [None, "2022"], ["Vitória", "1"], ["Serra", "2"]])
    estrutura = SheetStructure("x", merged=[MergedRange(0, 0, 1, 0)])
    assert detect_structure(df, estrutura).fill_down == []


def test_passos_da_receita_inicial():
    df, estrutura = _vendas()
    passos = detect_structure(df, estrutura).to_steps()
    assert passos == [
        {"op": "select_range", "start": "A1", "end_detect": "auto"},
        {"op": "header_rows", "n": 1},
        {"op": "drop_rows_where", "col": "Região", "match": "in", "value": ["Total"]},
        {"op": "fill_down", "cols": ["Região"]},
    ]


def test_passo_de_total_usa_a_celula_que_tem_a_palavra_chave():
    # O rótulo do total está na 2ª coluna; a 1ª tem um código. O passo tem
    # de remover pelo rótulo, não pelo código.
    linhas = [
        [None, "Item", "Valor"],
        ["1", "a", "1"],
        ["2", "Total parcial", "1"],
        ["3", "b", "2"],
        ["4", "Total parcial", "3"],
        [None, "TOTAL GERAL", "4"],
    ]
    det = detect_structure(grade(linhas))
    assert det.totals == [2, 4, 5]
    assert det.label(0) == "A"  # coluna sem rótulo no cabeçalho usa a letra
    assert det.to_steps()[2:] == [
        {"op": "drop_rows_where", "col": "Item", "match": "in", "value": ["Total parcial", "TOTAL GERAL"]}
    ]


def test_passo_de_total_por_negrito_usa_a_primeira_celula():
    linhas = [
        [None, "Item", "Valor"],
        ["10", "Saúde", "3"],
        [None, "a", "1"],
        [None, "b", "2"],
        [None, "c", "0"],
    ]
    df = grade(linhas)
    estrutura = SheetStructure("x", formatting=True, bold=[(1, 0)], sampled_rows=sample_windows(df.height))
    det = detect_structure(df, estrutura)
    assert det.totals == [1]
    assert det.to_steps()[2] == {"op": "drop_rows_where", "col": "A", "match": "in", "value": ["10"]}


# ---------------------------------------------------------------------------
# Detecção v2: cabeçalho multinível (F2.D1)
# ---------------------------------------------------------------------------

MULTINIVEL = [
    ["Casos notificados"],
    [None],
    ["Região", "Janeiro", None, "Fevereiro", None],
    [None, "Masculino", "Feminino", "Masculino", "Feminino"],
    ["Central", "802", "751", "592", "622"],
    ["Norte", "103", "610", "470", "855"],
    ["Sul", "50", "60", "70", "80"],
]


def test_cabecalho_multinivel():
    det = detect_structure(grade(MULTINIVEL))
    assert det.to_dict()["cabecalho"] == [3, 4]
    assert det.to_dict()["dados"] == [5, 7]
    assert det.title == ["Casos notificados"]
    passos = det.to_steps()
    assert passos[0] == {"op": "select_range", "start": "A3", "end_detect": "auto"}
    assert passos[1] == {"op": "header_rows", "n": 2, "separator": "_"}
    assert list(det.labels.values()) == [
        "Região",
        "Janeiro_Masculino",
        "Janeiro_Feminino",
        "Fevereiro_Masculino",
        "Fevereiro_Feminino",
    ]


def test_rotulos_iguais_aos_da_operacao():
    """Os nomes que a detecção calcula são os que o header_rows produz: os
    passos seguintes (drop_rows_where, fill_down) citam essas colunas."""
    import wolfz.ops  # noqa: F401
    from wolfz.core.recipe import recipe_from_dict

    df = grade(MULTINIVEL)
    det = detect_structure(df)
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(det.to_steps(), 1)],
        }
    )
    lf = df.lazy()
    for passo in receita.steps:
        lf = passo.to_polars(lf)
    assert lf.collect_schema().names() == list(det.labels.values())


def test_metadado_chave_valor_nao_e_nivel_de_cabecalho():
    linhas = [
        ["ESTAÇÃO:", "BRASILIA"],
        ["DATA DE FUNDAÇÃO:", "2000-05-07"],
        ["DATA", "HORA", "CHUVA", "PRESSÃO", "TEMPERATURA", "UMIDADE"],
        ["2001-01-01", "00:00", "0,8", "886", "20,1", "80"],
        ["2001-01-01", "01:00", "3,4", "886,1", "19,8", "82"],
    ]
    assert detect_structure(grade(linhas)).to_dict()["cabecalho"] == [3, 3]


def test_titulo_de_uma_celula_nao_e_nivel_de_cabecalho():
    assert detect_structure(grade(RELATORIO)).to_dict()["cabecalho"] == [4, 4]


# ---------------------------------------------------------------------------
# Verificação de total pela soma (F2.D2)
# ---------------------------------------------------------------------------


def test_subtotal_antes_dos_componentes_e_total_geral():
    """Como o IBGE publica: Brasil, depois cada região seguida dos estados."""
    linhas = [
        ["Unidade", "População"],
        ["Brasil", "1.000"],
        ["Norte", "300"],
        ["Acre", "100"],
        ["Pará", "200"],
        ["Sul", "700"],
        ["Paraná", "400"],
        ["Santa Catarina", "300"],
    ]
    det = detect_structure(grade(linhas))
    assert det.to_dict()["totais"] == [2, 3, 6]
    assert det.to_steps()[-1] == {
        "op": "drop_rows_where",
        "col": "Unidade",
        "match": "in",
        "value": ["Brasil", "Norte", "Sul"],
    }


def test_subtotal_depois_dos_componentes():
    linhas = [
        ["Item", "Valor"],
        ["a", "10"],
        ["b", "20"],
        ["Grupo 1", "30"],
        ["c", "5"],
        ["d", "7"],
        ["e", "1"],
        ["Grupo 2", "13"],
    ]
    assert detect_structure(grade(linhas)).to_dict()["totais"] == [4, 8]


def test_soma_por_acaso_nao_e_total():
    """'3' = '1' + '2' numa coluna de IDs: a soma fecha, mas os grupos não
    cobrem a coluna e uma soma isolada não basta."""
    linhas = [["ID", "Nome"], *([str(i), f"n{i}"] for i in range(1, 9))]
    assert detect_structure(grade(linhas)).totals == []
    numeros = [["Rua", "Número"], *([f"r{i}", n] for i, n in enumerate(["12", "30", "42", "8", "101", "77"]))]
    assert detect_structure(grade(numeros)).totals == []


def test_secao_sem_numero_separa_os_grupos():
    linhas = [
        ["Item", "Qtd"],
        ["Animais", None],
        ["Grande porte", "30"],
        ["Bovino", "20"],
        ["Bubalino", "10"],
        ["Pequeno porte", "9"],
        ["Galinhas", "5"],
        ["Codornas", "4"],
        ["Produtos", None],
        ["Leite", "100"],
        ["Ovos", "50"],
    ]
    assert detect_structure(grade(linhas)).to_dict()["totais"] == [3, 6]


# ---------------------------------------------------------------------------
# Várias tabelas na aba (F2.D3)
# ---------------------------------------------------------------------------


def test_tabelas_empilhadas():
    from wolfz.core.detect import detect_tables

    linhas = [
        ["Tabela 1"],
        ["Município", "Área"],
        ["Vitória", "93"],
        ["Serra", "547"],
        ["Fonte: IBGE"],
        [None],
        [None],
        ["Tabela 2"],
        ["Município", "População", "Densidade"],
        ["Vitória", "322869", "3471"],
        ["Serra", "520649", "951"],
        ["Linhares", "166786", "47"],
    ]
    tabelas = detect_tables(grade(linhas))
    assert [(t.to_dict()["dados"], t.to_dict()["colunas"]) for t in tabelas] == [
        ([3, 4], ["A", "B"]),
        ([10, 12], ["A", "C"]),
    ]
    assert tabelas[0].notes == ["Fonte: IBGE"]
    # A principal é a de mais linhas de dados.
    assert detect_structure(grade(linhas)).to_dict()["dados"] == [10, 12]


def test_tabelas_lado_a_lado():
    from wolfz.core.detect import detect_tables

    linhas = [
        ["Matrículas", None, None, None, "Docentes"],
        ["Município", "Urbana", "Rural", None, "Município", "Docentes"],
        ["Vitória", "100", "10", None, "Vitória", "50"],
        ["Serra", "200", "20", None, "Serra", "60"],
    ]
    tabelas = detect_tables(grade(linhas))
    assert [t.to_dict()["colunas"] for t in tabelas] == [["A", "C"], ["E", "F"]]
    assert [t.to_steps()[0] for t in tabelas] == [
        # A da esquerda tem colunas à direita: o automático pegaria a outra tabela.
        {"op": "select_range", "start": "A2", "end": "C4"},
        {"op": "select_range", "start": "E2", "end_detect": "auto"},
    ]


def test_coluna_vazia_dentro_da_tabela_nao_separa():
    """Coluna vazia com uma coluna só de um lado (rótulo e valor afastados,
    como na estimativa do IBGE) é a mesma tabela."""
    from wolfz.core.detect import detect_tables

    linhas = [["UF", None, "População"], ["Acre", None, "906876"], ["Pará", None, "8777124"]]
    tabelas = detect_tables(grade(linhas))
    assert len(tabelas) == 1
    assert tabelas[0].to_dict()["colunas"] == ["A", "C"]


def test_uma_linha_vazia_nao_separa_tabelas():
    from wolfz.core.detect import detect_tables

    linhas = [["Item", "Valor"], ["a", "1"], [None], ["b", "2"], ["c", "3"]]
    assert len(detect_tables(grade(linhas))) == 1


@pytest.mark.parametrize("ligado", [True, False])
def test_deteccao_devolve_o_coletor_como_estava(ligado):
    """A detecção pausa o coletor de ciclos (FH.B2) e o devolve como achou."""
    import gc

    grade = pl.DataFrame({"A": ["Nome", "Ana", "Bia"], "B": ["Valor", "1", "2"]})
    antes = gc.isenabled()
    (gc.enable if ligado else gc.disable)()
    try:
        assert detect_structure(grade) is not None
        assert gc.isenabled() is ligado
    finally:
        (gc.enable if antes else gc.disable)()


# ---------------------------------------------------------------------------
# Fim da área na receita inicial: o arquivo do mês seguinte vem inteiro
# ---------------------------------------------------------------------------


def _receita_inicial(df):
    from wolfz.core.detect import detect_tables, main_table
    from wolfz.core.engine import collect
    from wolfz.core.recipe import recipe_from_dict

    passos = main_table(detect_tables(df)).to_steps()
    receita = recipe_from_dict(
        {
            "wolfz_version": "1.0",
            "name": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "source": {"type": "excel"},
            "steps": [{"id": f"s{i}", **p} for i, p in enumerate(passos, 1)],
        }
    )
    return passos, lambda grade_nova: collect(receita, grade_nova.lazy())


def test_mes_seguinte_com_mais_linhas_vem_inteiro():
    """A receita feita em janeiro (3 linhas) aplicada a fevereiro (6 linhas,
    mesmo layout, rodapé depois de uma linha vazia) não corta a tabela."""
    janeiro = [["Relatório"], ["Nome", "Valor"], ["Ana", "1"], ["Bia", "2"], ["Caio", "3"], [], ["Fonte: X"]]
    passos, aplicar = _receita_inicial(grade(janeiro))
    assert passos[0] == {"op": "select_range", "start": "A2", "end_detect": "auto"}
    fevereiro = [*janeiro[:5], ["Davi", "4"], ["Eva", "5"], ["Fábio", "6"], [], ["Fonte: X"]]
    assert aplicar(grade(fevereiro))["Nome"].to_list() == ["Ana", "Bia", "Caio", "Davi", "Eva", "Fábio"]


def test_rodape_colado_mantem_o_fim_fixo():
    """Sem linha vazia entre os dados e a nota, o automático levaria a nota
    junto: a célula final fica fixa."""
    linhas = [["Nome", "Valor"], ["Ana", "1"], ["Bia", "2"], ["Fonte: IBGE, 2024. Elaboração própria."]]
    det = detect_structure(grade(linhas))
    assert det.last_row == 2
    assert det.to_steps()[0] == {"op": "select_range", "start": "A1", "end": "B3"}

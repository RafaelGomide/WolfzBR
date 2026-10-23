"""Arquivos públicos reais do corpus de testes (F1.B3).

Para cada arquivo, guarda de onde ele veio e como chegar à tabela limpa. O
gabarito (``saida_esperada.parquet``) é montado aqui, com regras escritas à
mão para aquele arquivo e lendo os valores tipados direto do
``python-calamine`` — não passa pelos parsers do WolfzBR, senão o teste
compararia o código com ele mesmo.

Dois passos:

    python scripts/corpus_publico.py baixar              # baixa os originais
    python scripts/corpus_publico.py gabarito            # gera saída, receita e FONTE.md

``baixar`` grava ``original.*`` (recortado, se preciso, para caber em 1 MB)
ou, para arquivo grande demais, ``externo.json`` + ``.gitignore`` e o original
ignorado pelo Git (depois, ``scripts/baixar_corpus.py`` busca de novo). As
fontes podem publicar versões novas no mesmo endereço; o original versionado
é o que vale, e ``FONTE.md`` registra a data do download.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from python_calamine import CalamineWorkbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerar_sinteticos import est, estrutura_json

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "tests" / "corpus"
BAIXADO_EM = "2026-10-16"
CRIADO_EM = "2026-10-16T00:00:00Z"

IBGE = "https://ftp.ibge.gov.br"
LICENCA_IBGE = "uso livre com citação da fonte (termos de uso do IBGE)"
LICENCA_GOV = "dados abertos do governo federal (Decreto 8.777/2016), uso livre com citação da fonte"
LICENCA_CAMARA = "dados abertos da Câmara dos Deputados, uso livre com citação da fonte"

TXT, NUM, INT, DATA = pl.String, pl.Float64, pl.Int64, pl.Date
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


@dataclass
class Saida:
    tabela: pl.DataFrame
    passos: list[dict]
    aba: str | None = None
    estrutura: dict | None = None  # gabarito da detecção (estrutura_esperada.json)


@dataclass
class Publico:
    nome: str
    url: str
    extensao: str
    categorias: tuple[str, ...]
    licenca: str
    descricao: str
    gabarito: Callable[[Path], list[Saida]]
    membro_zip: str | None = None
    recorte: Callable[[bytes], bytes] | None = None
    recorte_desc: str | None = None
    externo: bool = False


PUBLICOS: dict[str, Publico] = {}


def publico(**kwargs: Any) -> Callable[[Callable[[Path], list[Saida]]], Callable[[Path], list[Saida]]]:
    def registrar(fn: Callable[[Path], list[Saida]]) -> Callable[[Path], list[Saida]]:
        PUBLICOS[fn.__name__] = Publico(nome=fn.__name__, gabarito=fn, **kwargs)
        return fn

    return registrar


# --------------------------------------------------------------------------
# Leitura e conversões explícitas usadas pelos gabaritos
# --------------------------------------------------------------------------


def grade(path: Path, aba: str | None = None) -> list[list[Any]]:
    with CalamineWorkbook.from_path(str(path)) as wb:
        ws = wb.get_sheet_by_name(aba) if aba else wb.get_sheet_by_index(0)
        return ws.to_python(skip_empty_area=False)


def vazio(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def texto(v: Any) -> str | None:
    if vazio(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def inteiro(v: Any) -> int:
    if isinstance(v, int | float):
        assert float(v).is_integer(), v
        return int(v)
    s = str(v).strip()
    assert re.fullmatch(r"\d{1,3}([. ]\d{3})*|\d+", s), f"inteiro inesperado: {v!r}"
    return int(re.sub(r"[. ]", "", s))


def tabela(*colunas: tuple[str, pl.DataType, list]) -> pl.DataFrame:
    return pl.DataFrame({n: v for n, _, v in colunas}, schema={n: t for n, t, _ in colunas})


def colunas(nomes_tipos: list[tuple[str, pl.DataType]], linhas: list[tuple]) -> pl.DataFrame:
    return tabela(*((n, t, [x[i] for x in linhas]) for i, (n, t) in enumerate(nomes_tipos)))


# --------------------------------------------------------------------------
# IBGE: estimativas de população (relatório com subtotais e notas)
# --------------------------------------------------------------------------

REGIOES = ["Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"]
NOTA = re.compile(r"\(\d+\)$")


def _populacao_uf(path: Path, aba: str, col_valor: int) -> tuple[list[tuple[str, int]], list[int], int]:
    """UFs da aba 'Brasil e UFs': pula Brasil e as regiões (subtotais) e
    tira a marca de nota do valor ('3.289.290(1)'). Devolve também as
    linhas (do Excel) dos subtotais e a última linha da tabela."""
    linhas = grade(path, aba)
    assert str(linhas[1][col_valor]).strip() == "POPULAÇÃO ESTIMADA"
    ufs, subtotais, ultima = [], [], 0
    for i, linha in enumerate(linhas[2:], start=2):
        nome = texto(linha[0])
        if nome is None:
            break
        ultima = i + 1
        if nome == "Brasil" or nome in REGIOES or nome.removeprefix("Região ") in REGIOES:
            subtotais.append(i + 1)
            continue
        valor = linha[col_valor]
        if isinstance(valor, str):
            valor = NOTA.sub("", valor.strip())
        ufs.append((nome, inteiro(valor)))
    assert len(ufs) == 27 and len(subtotais) == 6, (len(ufs), subtotais)
    return ufs, subtotais, ultima


def _passos_populacao(regioes: list[str]) -> list[dict]:
    return [
        {"op": "select_range", "start": "A2", "end_detect": "auto"},
        {"op": "header_rows", "n": 1},
        {"op": "drop_empty_cols"},
        {
            "op": "rename",
            "mapping": {"BRASIL E UNIDADES DA FEDERAÇÃO": "uf", "POPULAÇÃO ESTIMADA": "populacao"},
        },
        {"op": "drop_rows_where", "col": "uf", "match": "in", "value": ["Brasil", *regioes]},
        {"op": "strip_footnotes", "cols": ["populacao"]},
        {"op": "parse_decimal_br", "cols": ["populacao"]},
        {"op": "cast", "types": {"populacao": "int"}},
    ]


@publico(
    url=f"{IBGE}/Estimativas_de_Populacao/Estimativas_2021/estimativa_dou_2021.xls",
    extensao="xls",
    categorias=("xls_antigo", "subtotais", "relatorio_rodape"),
    licenca=LICENCA_IBGE,
    descricao="Estimativas da população residente em 1º/07/2021 publicadas no DOU. Aba 'BRASIL E UFs': "
    "Brasil e regiões (subtotais) no meio das UFs, nome mesclado em A:B, valores com nota de rodapé "
    "grudada ('3.289.290(1)') e notas explicativas no fim.",
)
def ibge_estimativa_populacao_2021(path: Path) -> list[Saida]:
    ufs, subtotais, ultima = _populacao_uf(path, "BRASIL E UFs", 2)
    saida = tabela(("uf", TXT, [u for u, _ in ufs]), ("populacao", INT, [p for _, p in ufs]))
    regioes = [f"Região {r}" for r in REGIOES]
    estrutura = est(2, (3, ultima), "AC", totais=subtotais)
    return [Saida(saida, _passos_populacao(regioes), "BRASIL E UFs", estrutura)]


@publico(
    url=f"{IBGE}/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.ods",
    extensao="ods",
    categorias=("ods", "subtotais", "relatorio_rodape"),
    licenca=LICENCA_IBGE,
    descricao="Estimativas da população residente em 1º/07/2024 (DOU), em .ods. Aba 'BRASIL_E_UFs': "
    "Brasil e regiões (só o nome, sem 'Região') como subtotais no meio das UFs; fonte no fim.",
)
def ibge_estimativa_populacao_2024(path: Path) -> list[Saida]:
    ufs, subtotais, ultima = _populacao_uf(path, "BRASIL_E_UFs", 1)
    saida = tabela(("uf", TXT, [u for u, _ in ufs]), ("populacao", INT, [p for _, p in ufs]))
    estrutura = est(2, (3, ultima), "AB", totais=subtotais)
    return [Saida(saida, _passos_populacao(REGIOES), "BRASIL_E_UFs", estrutura)]


# --------------------------------------------------------------------------
# IBGE: série histórica do IPCA (cabeçalho em 4 linhas, ano só no 1º mês)
# --------------------------------------------------------------------------


@publico(
    url=f"{IBGE}/Precos_Indices_de_Precos_ao_Consumidor/IPCA/Serie_Historica/ipca_SerieHist.zip",
    extensao="xls",
    membro_zip="ipca_202609SerieHist.xls",
    categorias=("cabecalho_multinivel", "mesclagem_vertical", "xls_antigo"),
    licenca=LICENCA_IBGE,
    descricao="Série histórica do IPCA desde 1994 (versão de setembro de 2026). Cabeçalho em quatro "
    "linhas com palavras quebradas ('NO' / 'MÊS'), ano só na linha de janeiro, e o bloco de título e "
    "cabeçalho repetido a cada página com '(continuação)'.",
)
def ibge_ipca_serie_historica(path: Path) -> list[Saida]:
    linhas, ano, primeira, ultima = [], None, 0, 0
    for i, linha in enumerate(grade(path)):
        if isinstance(linha[0], int | float) and not vazio(linha[0]):
            ano = int(linha[0])
        mes = texto(linha[1])
        if mes not in MESES or not isinstance(linha[2], int | float):
            continue
        valores = [None if vazio(v) else float(v) for v in linha[2:8]]
        linhas.append((date(ano, MESES.index(mes) + 1, 1), *valores))
        primeira, ultima = primeira or i + 1, i + 1
    assert linhas[0][0] == date(1994, 1, 1) and len(linhas) > 380 and primeira == 9
    nomes = ["data", "numero_indice", "var_mes", "var_3_meses", "var_6_meses", "var_ano", "var_12_meses"]
    saida = colunas([(nomes[0], DATA), *((n, NUM) for n in nomes[1:])], linhas)
    passos = [
        {"op": "select_range", "start": "A9"},  # até o fim: há linha em branco entre os anos
        {"op": "header_rows", "n": 0, "names": ["ano", "mes", *nomes[1:]]},
        {"op": "filter", "col": "mes", "match": "in", "value": MESES},
        {"op": "fill_down", "cols": ["ano"]},
        {"op": "merge_cols", "cols": ["mes", "ano"], "separator": "/", "into": "data"},
        {"op": "parse_month_year", "cols": ["data"]},
        {"op": "reorder", "cols": nomes},
        {"op": "cast", "types": dict.fromkeys(nomes[1:], "float")},
    ]
    # Cabeçalho nas linhas 4 a 7; o título e o cabeçalho que se repetem a
    # cada página ficam dentro da área de dados e não são totais.
    return [Saida(saida, passos, "Série Histórica IPCA", est((4, 7), (9, ultima), "AH"))]


# --------------------------------------------------------------------------
# IBGE: LSPA (cabeçalho multinível mesclado, linhas "- TOTAL" no meio)
# --------------------------------------------------------------------------


def _lspa_numero(v: Any, decimal: bool) -> float | int | None:
    s = str(v).strip()
    if s == "--":
        return None
    if decimal:
        assert re.fullmatch(r"-?\d+\.\d", s), s
        return float(s)
    return inteiro(s)


@publico(
    url=f"{IBGE}/Producao_Agricola/Levantamento_Sistematico_da_Producao_Agricola_%5bmensal%5d/Tabelas_xls/2025/lspa_202501_01.xls",
    extensao="xls",
    categorias=("cabecalho_multinivel", "subtotais", "xls_antigo"),
    licenca=LICENCA_IBGE,
    descricao="LSPA, janeiro de 2025, tabela 1 (Brasil). Área, produção e rendimento mesclados sobre "
    "'3º Prognóstico', 'Janeiro' e 'Var %'; linha TOTAL e linhas '<produto> - TOTAL' antes das safras; "
    "milhar separado por espaço ('95 626 753') e '--' para dado inexistente.",
)
def ibge_lspa_2025_01(path: Path) -> list[Saida]:
    g = grade(path)
    assert texto(g[5][0]) == "TOTAL"
    linhas, totais, ultima = [], [6], 0
    for i, linha in enumerate(g[6:], start=6):
        produto = texto(linha[0])
        if produto is None:
            break
        ultima = i + 1
        if produto.endswith(" - TOTAL"):
            totais.append(i + 1)
            continue
        valores = [_lspa_numero(v, decimal=j % 3 == 2) for j, v in enumerate(linha[1:10])]
        linhas.append((produto, *valores))
    grupos = ["area", "producao", "rendimento"]
    sufixos = [("3o_prognostico", INT), ("janeiro", INT), ("var_pct", NUM)]
    nomes = [("produto", TXT)] + [(f"{g}_{s}", t) for g in grupos for s, t in sufixos]
    saida = colunas(nomes, linhas)
    rotulos = {"area": "Área (ha)", "producao": "Produção (t)", "rendimento": "Rendimento Médio (kg/ha)"}
    sub = {"3o_prognostico": "3º Prognóstico", "janeiro": "Janeiro", "var_pct": "Var %"}
    mapping = {"Produtos Agrícolas": "produto"}
    mapping |= {f"{rotulos[g]} {sub[s]}": f"{g}_{s}" for g in grupos for s, _ in sufixos}
    passos = [
        {"op": "select_range", "start": "A4", "end_detect": "auto"},
        {"op": "header_rows", "n": 2, "separator": " "},
        {"op": "rename", "mapping": mapping},
        {"op": "drop_rows_where", "col": "produto", "match": "equals", "value": "TOTAL"},
        {"op": "drop_rows_where", "col": "produto", "match": "contains", "value": " - TOTAL"},
        {"op": "trim", "cols": ["produto"]},  # "BATATA-INGLESA 1ª safra " vem com espaço no fim
        {"op": "replace", "cols": [n for n, _ in nomes[1:]], "old": "--", "new": None},
        {"op": "replace", "cols": [n for n, t in nomes[1:] if t is INT], "old": " ", "new": ""},
        {"op": "cast", "types": {n: "int" if t is INT else "float" for n, t in nomes[1:]}},
    ]
    return [Saida(saida, passos, "Var mensal área", est((4, 5), (6, ultima), "AJ", totais=totais))]


# --------------------------------------------------------------------------
# IBGE: PPM 2012, perfil municipal (sinais, seções e subtotais por porte)
# --------------------------------------------------------------------------


def _ibge_valor(v: Any) -> float | None:
    if isinstance(v, int | float):
        return float(v)
    s = str(v).strip()
    if s == "-":
        return 0.0
    assert s in ("...", "..", "X"), f"sinal inesperado: {v!r}"
    return None


@publico(
    url=f"{IBGE}/Producao_Pecuaria/Producao_da_Pecuaria_Municipal/2012/xls/espirito_santo.zip",
    extensao="xls",
    membro_zip="Tabela 36 - Linhares - ES.xls",
    categorias=("sinais_ibge", "cabecalho_multinivel", "subtotais", "xls_antigo"),
    licenca=LICENCA_IBGE,
    descricao="PPM 2012, tabela 36 (perfil da pecuária) de Linhares/ES, um dos arquivos do zip do estado. "
    "Cabeçalho em duas linhas com 'Participação (%)' mesclado, linhas de seção ('Categorias', "
    "'Produtos'), subtotais por porte do rebanho, '-' para zero e '...' para não pesquisado.",
)
def ibge_ppm_2012_linhares(path: Path) -> list[Saida]:
    secoes = {"Efetivo dos rebanhos em 31.12", "Categorias", "Produção animal", "Produtos"}
    portes = {"Grande porte", "Médio porte", "Pequeno porte"}
    linhas, totais, ultima = [], [], 0
    for i, linha in enumerate(grade(path)[5:], start=5):
        nome = texto(linha[0])
        if nome is None:
            break
        ultima = i + 1
        nome = re.sub(r"\s+", " ", nome)
        if nome in portes:
            totais.append(i + 1)
        if nome in secoes or nome in portes:
            continue
        linhas.append((nome, *(_ibge_valor(v) for v in linha[1:6])))
    nomes = [
        "especificacao",
        "quantidade",
        "part_estadual",
        "part_mesorregional",
        "part_microrregional",
        "valor",
    ]
    saida = colunas([(nomes[0], TXT), *((n, NUM) for n in nomes[1:])], linhas)
    passos = [
        {"op": "select_range", "start": "A6", "end_detect": "auto"},
        {"op": "header_rows", "n": 0, "names": nomes},
        {"op": "trim", "cols": ["especificacao"]},
        {"op": "drop_rows_where", "col": "especificacao", "match": "in", "value": sorted(secoes | portes)},
        {"op": "parse_ibge_value", "cols": nomes[1:], "add_status_col": False},
    ]
    # Linhas de seção ('Categorias', 'Produtos') ficam na área; só os portes
    # do rebanho são subtotais.
    return [Saida(saida, passos, "Tabela 36", est((4, 5), (6, ultima), "AF", totais=totais))]


# --------------------------------------------------------------------------
# IBGE: Censo 2022, população por município (relatório que começa em B2)
# --------------------------------------------------------------------------


@publico(
    url=f"{IBGE}/Censos/Censo_Demografico_2022/Populacao_e_domicilios_Primeiros_resultados/"
    "Resultados_da_2a_apuracao_20231027/CD2022_Populacao_Coletada_Imputada_e_Total_Municipio_e_UF_20231222.xlsx",
    extensao="xlsx",
    categorias=("relatorio_rodape",),
    licenca=LICENCA_IBGE,
    descricao="Censo 2022, população coletada, imputada e total por município. Tabela começa em B2 "
    "(coluna A vazia), título mesclado, código do município com zeros à esquerda como texto e fonte "
    "mesclada no fim. Segunda aba com as UFs.",
)
def ibge_censo_2022_populacao(path: Path) -> list[Saida]:
    g = grade(path, "Municípios")
    assert [texto(v) for v in g[2][1:8]][:3] == ["UF", "COD. UF", "COD. MUNIC"]
    linhas = []
    for linha in g[3:]:
        if vazio(linha[1]):
            break
        cod_munic = linha[3] if isinstance(linha[3], str) else f"{int(linha[3]):05d}"
        linhas.append(
            (texto(linha[1]), texto(linha[2]), cod_munic, texto(linha[4]), *map(inteiro, linha[5:8]))
        )
    assert len(linhas) == 5570, len(linhas)
    nomes = [
        ("uf", TXT),
        ("cod_uf", TXT),
        ("cod_munic", TXT),
        ("nome_municipio", TXT),
        ("pop_coletada", INT),
        ("pop_imputada", INT),
        ("pop_total", INT),
    ]
    rotulos = [
        "UF",
        "COD. UF",
        "COD. MUNIC",
        "NOME DO MUNICÍPIO",
        "POP. COLETADA",
        "POP. IMPUTADA",
        "POP. TOTAL",
    ]
    passos = [
        {"op": "select_range", "start": "B3", "end_detect": "auto"},
        {"op": "header_rows", "n": 1},
        {"op": "rename", "mapping": dict(zip(rotulos, [n for n, _ in nomes], strict=True))},
        {"op": "cast", "types": {"pop_coletada": "int", "pop_imputada": "int", "pop_total": "int"}},
    ]
    estrutura = est(3, (4, 3 + len(linhas)), "BH")
    return [Saida(colunas(nomes, linhas), passos, "Municípios", estrutura)]


# --------------------------------------------------------------------------
# IBGE: áreas territoriais 2022 (.xls acima de 1 MB: externo)
# --------------------------------------------------------------------------


@publico(
    url="https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/areas_territoriais/2022/"
    "AR_BR_RG_UF_RGINT_MES_MIC_MUN_2022.xls",
    extensao="xls",
    categorias=("xls_antigo",),
    licenca=LICENCA_IBGE,
    descricao="Áreas territoriais 2022, nove abas (município, microrregião, … Brasil) e um dicionário. "
    "Aba 'AR_BR_MUN_2022': tabela limpa seguida de observação mesclada depois de duas linhas em branco. "
    "Tem mais de 1 MB, então o original não é versionado (externo.json).",
    externo=True,
)
def ibge_areas_territoriais_2022(path: Path) -> list[Saida]:
    g = grade(path, "AR_BR_MUN_2022")
    assert [texto(v) for v in g[0]] == [
        "ID",
        "CD_UF",
        "NM_UF",
        "NM_UF_SIGLA",
        "CD_MUN",
        "NM_MUN",
        "AR_MUN_2022",
    ]
    linhas = []
    for linha in g[1:]:
        if vazio(linha[0]):
            break
        linhas.append((inteiro(linha[0]), *(texto(v) for v in linha[1:6]), float(linha[6])))
    # 5.570 municípios + Lagoa Mirim e Lagoa dos Patos (4300001 e 4300002).
    assert len(linhas) == 5572, len(linhas)
    nomes = [
        ("id", INT),
        ("cd_uf", TXT),
        ("nm_uf", TXT),
        ("sigla_uf", TXT),
        ("cd_mun", TXT),
        ("nm_mun", TXT),
        ("area_km2", NUM),
    ]
    rotulos = ["ID", "CD_UF", "NM_UF", "NM_UF_SIGLA", "CD_MUN", "NM_MUN", "AR_MUN_2022"]
    passos = [
        {"op": "select_range", "start": "A1", "end_detect": "auto"},
        {"op": "header_rows", "n": 1},
        {"op": "rename", "mapping": dict(zip(rotulos, [n for n, _ in nomes], strict=True))},
        {"op": "cast", "types": {"id": "int", "area_km2": "float"}},
    ]
    estrutura = est(1, (2, 1 + len(linhas)), "AG")
    return [Saida(colunas(nomes, linhas), passos, "AR_BR_MUN_2022", estrutura)]


# --------------------------------------------------------------------------
# ANP: preços de GLP (CSV UTF-8 com BOM, recortado)
# --------------------------------------------------------------------------

LINHAS_ANP = 5000


def _recorte_csv(dados: bytes) -> bytes:
    """Cabeçalho + os primeiros ``LINHAS_ANP`` registros, como vieram. Conta
    registros, não linhas: um campo entre aspas pode ter quebra de linha
    dentro, e o corte não pode cair no meio dele."""
    saida, registro, registros = [], [], 0
    for linha in dados.split(b"\n"):
        registro.append(linha)
        if b"\n".join(registro).count(b'"') % 2:
            continue  # aspas abertas: o registro continua na próxima linha
        saida.extend(registro)
        registro = []
        registros += 1
        if registros > LINHAS_ANP:
            break
    return b"\n".join(saida) + b"\n"


@publico(
    url="https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/glp/glp-2024-02.csv",
    extensao="csv",
    categorias=("csv_utf8_bom",),
    licenca=LICENCA_GOV,
    descricao="Série histórica de preços de GLP da ANP, 2º semestre de 2024. UTF-8 com BOM e ';', "
    "CNPJ com espaço na frente, decimal com vírgula, 'Valor de Compra' vazio e complemento de "
    "endereço entre aspas com o próprio separador dentro ('\"LOJA: A;\"').",
    recorte=_recorte_csv,
    recorte_desc=f"cabeçalho e os primeiros {LINHAS_ANP} registros do arquivo original (6,5 MB)",
)
def anp_glp_2024_s2(path: Path) -> list[Saida]:
    leitor = csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"), newline=""), delimiter=";")
    cab, *registros = list(leitor)
    assert cab[0] == "Regiao - Sigla" and len(cab) == 16, cab
    assert len(registros) == LINHAS_ANP, len(registros)
    linhas = []
    for c in registros:
        assert len(c) == 16, c
        cnpj = re.sub(r"\D", "", c[4])
        assert len(cnpj) == 14, c[4]
        d, m, a = c[11].split("/")
        venda = float(c[12].replace(",", "."))
        compra = float(c[13].replace(",", ".")) if c[13].strip() else None
        linhas.append(
            (c[0], c[1], c[2], c[3], cnpj, c[10], date(int(a), int(m), int(d)), venda, compra, c[14], c[15])
        )
    nomes = [
        ("regiao", TXT),
        ("uf", TXT),
        ("municipio", TXT),
        ("revenda", TXT),
        ("cnpj", TXT),
        ("produto", TXT),
        ("data_coleta", DATA),
        ("valor_venda", NUM),
        ("valor_compra", NUM),
        ("unidade", TXT),
        ("bandeira", TXT),
    ]
    passos = [
        {"op": "drop_cols", "cols": ["Nome da Rua", "Numero Rua", "Complemento", "Bairro", "Cep"]},
        {
            "op": "rename",
            "mapping": {
                "Regiao - Sigla": "regiao",
                "Estado - Sigla": "uf",
                "Municipio": "municipio",
                "Revenda": "revenda",
                "CNPJ da Revenda": "cnpj",
                "Produto": "produto",
                "Data da Coleta": "data_coleta",
                "Valor de Venda": "valor_venda",
                "Valor de Compra": "valor_compra",
                "Unidade de Medida": "unidade",
                "Bandeira": "bandeira",
            },
        },
        {"op": "clean_cnpj", "cols": ["cnpj"]},
        {"op": "parse_date_br", "cols": ["data_coleta"]},
        {"op": "parse_decimal_br", "cols": ["valor_venda", "valor_compra"]},
    ]
    return [Saida(colunas(nomes, linhas), passos, estrutura=est(1, (2, 1 + len(linhas)), "AP"))]


# --------------------------------------------------------------------------
# Câmara dos Deputados: órgãos (.ods)
# --------------------------------------------------------------------------


def _data_iso(v: Any) -> date | None:
    if vazio(v):
        return None
    if isinstance(v, date):
        return v if type(v) is date else v.date()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(T[\d:]+)?", str(v).strip())
    assert m, v
    return date(int(m[1]), int(m[2]), int(m[3]))


@publico(
    url="https://dadosabertos.camara.leg.br/arquivos/orgaos/ods/orgaos.ods",
    extensao="ods",
    categorias=("ods",),
    licenca=LICENCA_CAMARA,
    descricao="Órgãos da Câmara dos Deputados (comissões, frentes, conselhos) do portal de dados abertos, "
    "em .ods. Tabela limpa, mas com código numérico gravado como decimal ('1.0'), datas ISO com hora "
    "e muitas colunas vazias.",
)
def camara_orgaos(path: Path) -> list[Saida]:
    g = grade(path)
    cab = [texto(v) for v in g[0]]
    assert cab[:4] == ["uri", "sigla", "apelido", "nome"], cab
    idx = {n: cab.index(n) for n in cab}
    assert len(cab) == 16, cab
    linhas, ultima = [], 0
    for i, linha in enumerate(g[1:], start=1):
        if vazio(linha[0]):
            continue
        ultima = i + 1
        cod = linha[idx["codTipoOrgao"]]
        linhas.append(
            (
                texto(linha[idx["sigla"]]),
                texto(linha[idx["nome"]]),
                None if vazio(cod) else inteiro(cod),
                texto(linha[idx["tipoOrgao"]]),
                _data_iso(linha[idx["dataInicio"]]),
                _data_iso(linha[idx["dataFim"]]),
                texto(linha[idx["descricaoSituacao"]]),
                texto(linha[idx["casa"]]),
            )
        )
    nomes = [
        ("sigla", TXT),
        ("nome", TXT),
        ("cod_tipo_orgao", INT),
        ("tipo_orgao", TXT),
        ("data_inicio", DATA),
        ("data_fim", DATA),
        ("situacao", TXT),
        ("casa", TXT),
    ]
    descartadas = ["uri", "apelido", "nomePublicacao", "dataInstalacao", "dataFimOriginal", "codSituacao"]
    descartadas += ["sala", "urlWebsite"]
    passos = [
        {"op": "header_rows", "n": 1},
        {"op": "drop_cols", "cols": descartadas},
        {
            "op": "rename",
            "mapping": {
                "sigla": "sigla",
                "nome": "nome",
                "codTipoOrgao": "cod_tipo_orgao",
                "tipoOrgao": "tipo_orgao",
                "dataInicio": "data_inicio",
                "dataFim": "data_fim",
                "descricaoSituacao": "situacao",
                "casa": "casa",
            },
        },
        {"op": "cast", "types": {"cod_tipo_orgao": "int", "data_inicio": "date", "data_fim": "date"}},
    ]
    return [Saida(colunas(nomes, linhas), passos, estrutura=est(1, (2, ultima), "AP"))]


# --------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------


def _receita(p: Publico, saida: Saida) -> str:
    tipo = {"xlsx": "excel", "xls": "excel", "ods": "ods", "csv": "csv"}[p.extensao]
    source: dict[str, Any] = {"type": tipo}
    if saida.aba:
        source["sheet"] = saida.aba
    receita = {
        "wolfz_version": "1.0",
        "name": p.nome.replace("_", " "),
        "created_at": CRIADO_EM,
        "source": source,
        "steps": [{"id": f"s{i}", **passo} for i, passo in enumerate(saida.passos, 1)],
    }
    return json.dumps(receita, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def fonte_md(p: Publico) -> str:
    linhas = ["---", "origem: publico", f"url: {p.url}"]
    if p.membro_zip:
        linhas.append(f"membro_zip: {p.membro_zip}")
    linhas += [f"baixado_em: {BAIXADO_EM}", f"licenca: {p.licenca}", f"categorias: {', '.join(p.categorias)}"]
    if p.recorte_desc:
        linhas.append(f"recorte: {p.recorte_desc}")
    linhas += ["---", "", f"# {p.nome}", "", p.descricao, ""]
    return "\n".join(linhas)


def baixar(p: Publico, destino: Path = CORPUS) -> str:
    pasta = destino / p.nome
    pasta.mkdir(parents=True, exist_ok=True)
    pedido = urllib.request.Request(p.url, headers={"User-Agent": "WolfzBR-corpus/1.0"})
    with urllib.request.urlopen(pedido, timeout=300) as resposta:
        dados = resposta.read()
    if p.membro_zip:
        with zipfile.ZipFile(io.BytesIO(dados)) as zf:
            dados = zf.read(p.membro_zip)
    if p.recorte:
        dados = p.recorte(dados)
    original = pasta / f"original.{p.extensao}"
    original.write_bytes(dados)
    if p.externo:
        meta = {"url": p.url, "sha256": hashlib.sha256(dados).hexdigest(), "arquivo": original.name}
        if p.membro_zip:
            meta["membro_zip"] = p.membro_zip
        (pasta / "externo.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        (pasta / ".gitignore").write_text("original.*\n", encoding="utf-8")
    return f"{len(dados) / 1_048_576:.2f} MB"


def gerar_gabarito(p: Publico, destino: Path = CORPUS) -> Path:
    pasta = destino / p.nome
    original = pasta / f"original.{p.extensao}"
    for antigo in [*pasta.glob("saida_esperada*"), *pasta.glob("receita_esperada*")]:
        antigo.unlink()
    saidas = p.gabarito(original)
    (pasta / "estrutura_esperada.json").write_text(estrutura_json(saidas), encoding="utf-8")
    for i, saida in enumerate(saidas):
        sufixo = "" if i == 0 else f"_{i + 1}"
        saida.tabela.write_parquet(pasta / f"saida_esperada{sufixo}.parquet")
        (pasta / f"receita_esperada{sufixo}.wolfz.json").write_text(_receita(p, saida), encoding="utf-8")
    (pasta / "FONTE.md").write_text(fonte_md(p), encoding="utf-8")
    return pasta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("comando", choices=["baixar", "gabarito", "listar"])
    parser.add_argument("nomes", nargs="*", help="Arquivos (padrão: todos).")
    args = parser.parse_args(argv)
    desconhecidos = set(args.nomes) - set(PUBLICOS)
    if desconhecidos:
        print(f"Desconhecidos: {', '.join(sorted(desconhecidos))}", file=sys.stderr)
        return 2
    for nome in args.nomes or PUBLICOS:
        p = PUBLICOS[nome]
        if args.comando == "listar":
            print(f"{nome:34} {p.extensao:5} {', '.join(p.categorias)}")
        elif args.comando == "baixar":
            print(f"{nome}: {baixar(p)}")
        else:
            print(f"{nome}: {gerar_gabarito(p).relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

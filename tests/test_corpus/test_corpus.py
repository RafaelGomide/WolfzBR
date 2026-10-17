"""Corpus de testes (F1.B): estrutura, tamanho, cobertura e regressão.

As receitas que só usam operações já implementadas, sobre CSV, rodam de
ponta a ponta e são comparadas com a saída esperada. As demais ficam
puladas com o motivo (operação que falta, leitura de Excel no ``wolfz.run``)
e passam a rodar sozinhas quando a peça que falta entrar.
"""

import importlib.util
import zipfile
from collections import Counter

import polars as pl
import pytest
from corpus_lib import (
    ARQUIVOS_PERMITIDOS,
    ARQUIVOS_VALIDACAO,
    CAMPOS_FONTE,
    CATEGORIAS,
    CORPUS,
    FORMATOS,
    MAX_BYTES,
    MINIMO_ARQUIVOS,
    MINIMO_POR_CATEGORIA,
    OPERACOES_PLANEJADAS,
    SOLTOS,
    VALIDACAO,
    entradas,
    gerador,
    ler_fonte,
    pares,
    publicos,
)
from polars.testing import assert_frame_equal

import wolfz
import wolfz.ops  # registra as operações no catálogo
from wolfz.core.ingest import detect_format, list_sheets, read_sheet
from wolfz.core.ingest.csv import open_csv_lazy
from wolfz.core.recipe import load_recipe, registered_ops

ENTRADAS = entradas()
PARES = pares()
TEM_XLWT = importlib.util.find_spec("xlwt") is not None


def _ids(itens):
    return [getattr(i, "id", None) or i.nome for i in itens]


# --------------------------------------------------------------------------
# Estrutura (F1.B1)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entrada", ENTRADAS, ids=_ids(ENTRADAS))
def test_estrutura(entrada):
    fonte = entrada.fonte
    origem = fonte.get("origem")
    assert origem in CAMPOS_FONTE, f"origem deve ser uma de {sorted(CAMPOS_FONTE)}"
    faltando = CAMPOS_FONTE[origem] - fonte.keys()
    assert not faltando, f"FONTE.md sem: {sorted(faltando)}"
    assert fonte["categorias"], "FONTE.md sem categorias"
    desconhecidas = set(fonte["categorias"]) - CATEGORIAS.keys()
    assert not desconhecidas, f"categorias desconhecidas: {sorted(desconhecidas)}"

    assert len(entrada.originais) <= 1, "mais de um original.*"
    if entrada.externo is None:
        assert entrada.original is not None, "falta o original.*"
    if entrada.original is not None:
        assert entrada.original.suffix in FORMATOS

    assert entrada.pares, "falta receita_esperada.wolfz.json"
    _confere_estrutura(entrada)
    for par in entrada.pares:
        assert par.saida.exists(), f"falta {par.saida.name}"
    saidas = {p.name for p in entrada.pasta.glob("saida_esperada*.parquet")}
    assert saidas == {p.saida.name for p in entrada.pares}, "saida_esperada sem receita"

    esperados = ARQUIVOS_PERMITIDOS | {p.name for p in entrada.originais} | saidas
    esperados |= {p.receita.name for p in entrada.pares}
    extras = {p.name for p in entrada.pasta.iterdir()} - esperados
    assert not extras, f"arquivos fora do padrão: {sorted(extras)}"

    if origem == "sintetico":
        assert fonte["gerador"] == "scripts/gerar_sinteticos.py"
        assert entrada.nome in gerador().SINTETICOS, "sintético que o gerador não conhece"
    else:
        assert entrada.nome in publicos().PUBLICOS, (
            "arquivo público sem gabarito em scripts/corpus_publico.py"
        )


def _confere_estrutura(entrada):
    estrutura = entrada.estrutura
    assert estrutura.keys() == {"aba", "tabelas"}
    assert len(estrutura["tabelas"]) == len(entrada.pares), "uma estrutura por receita esperada"
    for tabela in estrutura["tabelas"]:
        assert tabela.keys() == {"cabecalho", "dados", "colunas", "totais", "fill_down"}
        primeira, ultima = tabela["dados"]
        assert 1 <= primeira <= ultima
        if tabela["cabecalho"] is not None:
            topo, base = tabela["cabecalho"]
            assert 1 <= topo <= base < primeira, "cabeçalho acima dos dados"
        assert all(primeira <= r <= ultima for r in tabela["totais"]), "total fora da área de dados"
        assert tabela["totais"] == sorted(set(tabela["totais"]))
        assert len(tabela["colunas"]) == 2


@pytest.mark.parametrize("entrada", [e for e in ENTRADAS if e.externo], ids=lambda e: e.nome)
def test_externo(entrada):
    meta = entrada.externo
    assert {"url", "sha256", "arquivo"} <= meta.keys()
    assert meta["arquivo"].startswith("original.")
    ignorados = (entrada.pasta / ".gitignore").read_text(encoding="utf-8").split()
    assert "original.*" in ignorados, "o original baixado precisa estar no .gitignore da pasta"


def test_raiz_do_corpus_so_tem_pastas():
    soltos = {p.name for p in CORPUS.iterdir() if p.is_file()}
    assert soltos <= SOLTOS, f"arquivo solto na raiz do corpus: {sorted(soltos - SOLTOS)}"


def test_ler_fonte(tmp_path):
    path = tmp_path / "FONTE.md"
    texto = "---\norigem: publico\ncategorias: ods, mojibake\nurl: https://x/y\n---\n\ntexto"
    path.write_text(texto, encoding="utf-8")
    assert ler_fonte(path) == {"origem": "publico", "categorias": ["ods", "mojibake"], "url": "https://x/y"}
    for ruim in ["sem cabeçalho", "---\nsem dois pontos\n---", "---\norigem: x\n"]:
        path.write_text(ruim, encoding="utf-8")
        with pytest.raises(ValueError):
            ler_fonte(path)


# --------------------------------------------------------------------------
# Tamanho (F1.B2)
# --------------------------------------------------------------------------


def test_nenhum_arquivo_acima_de_1_mb():
    baixados = {e.original for e in ENTRADAS if e.externo and e.original}
    grandes = [
        f"{p.relative_to(CORPUS)} ({p.stat().st_size / 1_048_576:.1f} MB)"
        for p in CORPUS.rglob("*")
        if p.is_file() and p not in baixados and p.stat().st_size > MAX_BYTES
    ]
    assert not grandes, "acima de 1 MB: recorte ou use externo.json (scripts/baixar_corpus.py)"


# --------------------------------------------------------------------------
# Cobertura (F1.B3) e conjunto de validação (F1.B5)
# --------------------------------------------------------------------------


def test_cobertura_das_categorias():
    desenvolvimento = [e for e in ENTRADAS if e.conjunto == "desenvolvimento"]
    assert len(desenvolvimento) >= MINIMO_ARQUIVOS
    contagem = Counter(c for e in desenvolvimento for c in e.fonte["categorias"])
    poucas = {c: contagem[c] for c in CATEGORIAS if contagem[c] < MINIMO_POR_CATEGORIA}
    assert not poucas, f"categorias com menos de {MINIMO_POR_CATEGORIA} arquivos: {poucas}"


def test_conjunto_de_validacao():
    validacao = [e for e in ENTRADAS if e.conjunto == "validacao"]
    if len(validacao) < ARQUIVOS_VALIDACAO:
        pytest.skip(
            f"F1.B5: {len(validacao)} de {ARQUIVOS_VALIDACAO} arquivos de validação em "
            f"{VALIDACAO.relative_to(CORPUS.parent)}/"
        )
    nomes = {e.nome for e in ENTRADAS if e.conjunto == "desenvolvimento"}
    assert not nomes & {e.nome for e in validacao}, "o mesmo arquivo nos dois conjuntos"


# --------------------------------------------------------------------------
# Receitas e saídas esperadas
# --------------------------------------------------------------------------


@pytest.mark.parametrize("par", PARES, ids=_ids(PARES))
def test_receita_cita_operacoes_conhecidas(par):
    dados = par.json()
    assert {"wolfz_version", "name", "created_at", "source", "steps"} <= dados.keys()
    ids = [p.get("id") for p in dados["steps"]]
    assert ids == [f"s{i}" for i in range(1, len(ids) + 1)]
    desconhecidas = set(par.operacoes()) - registered_ops().keys() - OPERACOES_PLANEJADAS
    assert not desconhecidas, f"operações fora do catálogo e do planejamento: {sorted(desconhecidas)}"
    if set(par.operacoes()) <= registered_ops().keys():
        load_recipe(par.receita)  # tudo implementado: a receita tem de validar


@pytest.mark.parametrize("par", PARES, ids=_ids(PARES))
def test_saida_esperada(par):
    faltam = sorted(set(par.operacoes()) - registered_ops().keys())
    if faltam:
        pytest.skip(f"aguardando operações: {', '.join(faltam)}")
    if par.entrada.original is None:
        pytest.skip("original não baixado (scripts/baixar_corpus.py)")
    if par.json()["source"]["type"] != "csv":
        pytest.skip("wolfz.run ainda lê só CSV")
    esperado = pl.read_parquet(par.saida)
    assert_frame_equal(wolfz.run(load_recipe(par.receita), par.entrada.original), esperado)


# --------------------------------------------------------------------------
# Ingestão: todo original do corpus abre
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entrada", ENTRADAS, ids=_ids(ENTRADAS))
def test_original_abre(entrada):
    if entrada.original is None:
        pytest.skip("original não baixado (scripts/baixar_corpus.py)")
    fmt = detect_format(entrada.original)
    assert f".{fmt}" == entrada.original.suffix
    if fmt == "csv":
        with open_csv_lazy(entrada.original, has_header=False) as lf:
            assert lf.collect().height > 0
        return
    abas = {s.name for s in list_sheets(entrada.original)}
    for par in entrada.pares:
        aba = par.json()["source"].get("sheet")
        assert aba is None or aba in abas, f"a receita cita a aba {aba!r}, que não existe"
        assert read_sheet(entrada.original, aba).frame.height > 0


# --------------------------------------------------------------------------
# Sintéticos em dia com o gerador
# --------------------------------------------------------------------------

SINTETICOS = [e for e in ENTRADAS if e.fonte.get("origem") == "sintetico"]


def _conteudo(path):
    """O que importa de um original: bytes para CSV; conteúdo de cada entrada
    do zip para ODS (o cabeçalho do zip e a compressão variam com o SO e a
    zlib); valores e estrutura de cada aba para .xlsx/.xls, cujo zip carrega
    data de gravação."""
    if path.suffix == ".csv":
        return path.read_bytes()
    if path.suffix == ".ods":
        with zipfile.ZipFile(path) as zf:
            return b"".join(n.encode() + b"\0" + zf.read(n) for n in zf.namelist())
    return [(s.name, read_sheet(path, s.name)) for s in list_sheets(path)]


@pytest.mark.parametrize("entrada", SINTETICOS, ids=_ids(SINTETICOS))
def test_sintetico_em_dia_com_o_gerador(entrada, tmp_path):
    if entrada.original.suffix == ".xls" and not TEM_XLWT:
        pytest.skip("gerar .xls precisa do xlwt")
    novo = gerador().gravar(gerador().SINTETICOS[entrada.nome](), tmp_path)
    for nome in ["FONTE.md", "estrutura_esperada.json", *(p.receita.name for p in entrada.pares)]:
        assert (novo / nome).read_text(encoding="utf-8") == (entrada.pasta / nome).read_text(encoding="utf-8")
    for par in entrada.pares:
        assert_frame_equal(pl.read_parquet(novo / par.saida.name), pl.read_parquet(par.saida))
    gerado, versionado = _conteudo(novo / entrada.original.name), _conteudo(entrada.original)
    if isinstance(gerado, bytes):
        assert gerado == versionado
    else:
        assert [n for n, _ in gerado] == [n for n, _ in versionado]
        for (_, a), (_, b) in zip(gerado, versionado, strict=True):
            assert_frame_equal(a.frame, b.frame)
            assert a.structure == b.structure


# --------------------------------------------------------------------------
# Públicos: gabarito em dia com scripts/corpus_publico.py
# --------------------------------------------------------------------------

PUBLICOS = [e for e in ENTRADAS if e.fonte.get("origem") == "publico"]


@pytest.mark.parametrize("entrada", PUBLICOS, ids=_ids(PUBLICOS))
def test_publico_em_dia_com_o_gabarito(entrada, tmp_path):
    if entrada.original is None:
        pytest.skip("original não baixado (scripts/baixar_corpus.py)")
    script = publicos()
    p = script.PUBLICOS[entrada.nome]
    assert (entrada.pasta / "FONTE.md").read_text(encoding="utf-8") == script.fonte_md(p)
    saidas = p.gabarito(entrada.original)
    gravada = (entrada.pasta / "estrutura_esperada.json").read_text(encoding="utf-8")
    assert gravada == script.estrutura_json(saidas)
    assert len(saidas) == len(entrada.pares)
    for saida, par in zip(saidas, entrada.pares, strict=True):
        assert_frame_equal(saida.tabela, pl.read_parquet(par.saida))
        assert script._receita(p, saida) == par.receita.read_text(encoding="utf-8")

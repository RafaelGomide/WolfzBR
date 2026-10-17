# Corpus de testes

O corpus é o que mede a detecção e impede regressões (§12 e §13.5 do design). Cada arquivo é uma planilha suja com a resposta certa ao lado.

## Estrutura

Uma pasta por arquivo:

```
tests/corpus/<nome>/
├── original.xlsx                  # a planilha como veio (.xlsx, .xls, .ods ou .csv)
├── receita_esperada.wolfz.json    # os passos que a limpam
├── saida_esperada.parquet         # a tabela limpa (o gabarito)
├── estrutura_esperada.json        # onde estão cabeçalho, dados e totais (gabarito da detecção)
└── FONTE.md                       # origem, licença e categorias
```

Arquivo com duas tabelas tem também `receita_esperada_2.wolfz.json` e `saida_esperada_2.parquet`, e duas entradas em `estrutura_esperada.json`.

### `estrutura_esperada.json`

Linhas e colunas como aparecem no Excel (linha 1 é a primeira), uma entrada por tabela:

```json
{
  "aba": "Receita",
  "tabelas": [
    {"cabecalho": [4, 4], "dados": [5, 16], "colunas": ["A", "D"], "totais": [16], "fill_down": []}
  ]
}
```

- `cabecalho`: primeira e última linha do cabeçalho (`null` se a tabela não tem).
- `dados`: primeira e última linha de dados, incluindo totais e linhas de seção que estejam no meio ou no fim.
- `totais`: linhas que saem da tabela por serem total, subtotal ou saldo.
- `fill_down`: colunas com categoria mesclada na vertical.

`python scripts/medir_deteccao.py` compara a detecção com esse gabarito e imprime uma tabela em Markdown. Rode a cada PR que mexer em `wolfz/core/detect/` e cole o resultado no PR. O teste `test_deteccao_corpus.py` reprova o build se algum arquivo passar a errar; as falhas conhecidas da versão atual ficam listadas nele, com o motivo.

Pastas que começam com `_` não são do corpus: `_fixtures/` guarda arquivos usados por testes específicos. `minimo.csv`, solto na raiz, é o exemplo do README.

### `FONTE.md`

Começa com um cabeçalho `chave: valor`:

```markdown
---
origem: publico
url: https://dados.gov.br/...
baixado_em: 2026-10-16
licenca: CC-BY 4.0
categorias: sinais_ibge, cabecalho_multinivel
---

Descrição livre: o que o arquivo tem de difícil.
```

- `origem`: `publico` (baixado de uma fonte aberta) ou `sintetico` (gerado por `scripts/gerar_sinteticos.py`).
- Público exige `url`, `baixado_em` e `licenca`. Sintético exige `gerador` e `licenca`.
- `categorias`: uma ou mais da tabela abaixo, separadas por vírgula.

### Receitas esperadas

Toda receita esperada roda de ponta a ponta com `wolfz.run` sobre o `original.*`, e o resultado é comparado com a `saida_esperada.parquet`. A receita pode citar uma operação que ainda não existe (hoje: `parse_ibge`, `clean_cpf_cnpj`, `fix_mojibake`, `strip_footnote_marks`): o teste confere que o nome está no catálogo planejado (pega erro de digitação) e pula a execução com o motivo. Quando a operação entra, o teste passa a executar a receita sozinho.

Planilha é lida como grade (colunas `A`, `B`, …; linha 1 é a primeira linha da aba), então a receita começa recortando a tabela com `select_range` e promovendo o cabeçalho com `header_rows`. CSV é lido com cabeçalho, a não ser que a receita comece por um desses dois passos.

## Política de tamanho

- Nenhum arquivo acima de **1 MB** no Git. O teste e o hook `check-added-large-files` do pre-commit conferem.
- Arquivo público maior: recorte as linhas que mostram o problema, ou não versione o original. Nesse caso a pasta leva um `externo.json` (`url`, `sha256`, `arquivo` e, se a fonte é um `.zip`, `membro_zip`) e um `.gitignore` com `original.*`; o original vem de `python scripts/baixar_corpus.py`.

## Dados de cliente: nunca

Nenhum dado de cliente ou de pessoa real entra no corpus. Arquivos no formato de sistemas corporativos (ERP, cadastros, folha) são sintéticos: imitam a estrutura, não o conteúdo. CPFs e CNPJs dos sintéticos têm dígito verificador válido, mas são aleatórios.

Para gerar ou atualizar os sintéticos:

```bash
python scripts/gerar_sinteticos.py
```

O teste `test_sintetico_em_dia_com_o_gerador` falha se o gerador mudar e os arquivos não forem gerados de novo. Os `.xls` precisam do pacote `xlwt`, que não é dependência do projeto; sem ele, o teste desses arquivos é pulado.

## Arquivos públicos reais

Ficam em `scripts/corpus_publico.py`: de onde cada um veio, como foi recortado e as regras do gabarito, escritas à mão para aquele arquivo e lendo os valores tipados direto do `python-calamine` (o gabarito nunca passa pelos parsers do WolfzBR, senão o teste compararia o código com ele mesmo).

```bash
python scripts/corpus_publico.py baixar     # baixa (e recorta) os originais
python scripts/corpus_publico.py gabarito   # gera saida_esperada, receita_esperada e FONTE.md
```

As fontes podem publicar versões novas no mesmo endereço (a série do IPCA é atualizada todo mês). O original versionado é o que vale; `FONTE.md` registra a data do download. O teste `test_publico_em_dia_com_o_gabarito` confere que a saída esperada é a que o gabarito produz a partir do original.

Fontes que bloqueiam download automatizado (Portal da Transparência, gerador de tabelas do SIDRA) ficaram de fora; um arquivo delas só entra baixado à mão.

## Categorias

Mínimo de 2 arquivos por categoria e 30 no total.

| Categoria | O que exercita |
|---|---|
| `relatorio_rodape` | detecção de área, rodapé "Fonte:" |
| `cabecalho_multinivel` | `header_rows` com mais de uma linha, mesclagem horizontal |
| `subtotais` | linhas de total no meio dos dados |
| `mesclagem_vertical` | `fill_down` |
| `csv_cp1252` | encoding, nulos textuais |
| `csv_utf8_bom` | BOM no nome da primeira coluna |
| `sinais_ibge` | `-`, `..`, `...`, `X` |
| `datas_8_digitos` | `AAAAMMDD` × `DDMMAAAA` |
| `zeros_perdidos` | CPF, CNPJ, CEP e datas sem o zero à esquerda |
| `meses_lado_a_lado` | `unpivot` |
| `exportacao_erp` | menos no fim, D/C, datas sentinela (`31.12.9999`) |
| `xls_antigo` | ingestão binária |
| `ods` | ingestão ODS |
| `duas_tabelas` | duas áreas na mesma aba |
| `mojibake` | `fix_mojibake` |

## Conjunto de validação

`tests/corpus/validacao/` guarda os **10 arquivos que não são olhados durante o desenvolvimento** (F1.B5). São eles que medem o critério do MVP (F1.K1): planilha inédita até a tabela limpa em menos de 3 minutos, sem código.

- Mesma estrutura de pasta do resto do corpus.
- Escolha arquivos públicos reais, de fontes diferentes das usadas no desenvolvimento.
- Não ajuste heurística de detecção olhando para eles. Se um deles revelar um problema, o caso vai para o conjunto de desenvolvimento como arquivo *novo*, e outro entra na validação no lugar.

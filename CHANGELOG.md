# Changelog

Todas as mudanças relevantes do WolfzBR ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/). Mudança incompatível no formato da receita é versão *major*.

## [Não publicado]

### Adicionado

- Ingestão de `.xlsx` (`fastexcel`), `.xls` e `.ods` (`python-calamine`): todos os valores como texto, na posição original da planilha (colunas `A`, `B`, …; linha *i* = linha *i* + 1 do Excel).
- Metadados estruturais (`structure.json`): mesclagens, negrito, fórmulas e tipos, lidos só nas primeiras 50 e nas últimas 20 linhas, com `openpyxl` em modo `read_only`. No `.xls` e no `.ods` só há tipos (e mesclagens no `.xls`); a importação avisa.
- `CellMatrix` (valor, tipo, mesclada, negrito) para a detecção.
- Listagem de abas com dimensão estimada e visibilidade (oculta e muito oculta).
- CSV acima de 50 MB lido em streaming, sem carregar o arquivo inteiro na memória.
- Limites na importação: 100 MB por arquivo, tamanho descompactado de `.xlsx`/`.ods` (zip bomb) e 200 abas.
- Erros de importação com mensagem para o usuário (`IngestError`, Problem Details): arquivo aberto no Excel, arquivo temporário `~$` do Excel, protegido por senha, corrompido, vazio, extensão que não bate com o conteúdo (inclusive HTML salvo como `.xls`) e formato não suportado.
- `import_file`: grava `project.json`, `raw.parquet` e `structure.json` em `~/.wolfz/projects/<ulid>/` (ou em `WOLFZ_HOME`) e reaproveita o `raw.parquet` de um projeto anterior quando o arquivo, pelo hash, e a aba são os mesmos.
- Corpus de testes em `tests/corpus/`: uma pasta por arquivo com `original.*`, `receita_esperada.wolfz.json`, `saida_esperada.parquet` e `FONTE.md`, mais um `README.md` com as regras.
- 30 arquivos sintéticos cobrindo as 15 categorias do corpus (`.xlsx`, `.xls`, `.ods` e `.csv`), gerados por `scripts/gerar_sinteticos.py`. Imitam a estrutura de fontes públicas e de ERPs; os dados são inventados.
- Testes do corpus: estrutura das pastas, limite de 1 MB, cobertura mínima por categoria, ingestão de todo original, sintéticos em dia com o gerador e execução das receitas que já têm todas as operações implementadas.
- `scripts/baixar_corpus.py` para arquivos públicos acima de 1 MB, que ficam fora do Git e são baixados com conferência de hash.
- 9 arquivos públicos reais no corpus (IBGE, ANP e Câmara dos Deputados): estimativas de população 2021 (`.xls`) e 2024 (`.ods`), série histórica do IPCA, LSPA, perfil municipal da PPM, população do Censo 2022, áreas territoriais 2022 (externo, acima de 1 MB), preços de GLP da ANP (recortado) e órgãos da Câmara (`.ods`). Origem, recorte e gabarito de cada um em `scripts/corpus_publico.py`.

- Perfil de coluna (`ColumnProfile`, `profile_table`): tipo brasileiro inferido, % de nulos, % de marcadores de nulo, distintos, formas mais comuns, exemplos e mínimo/máximo convertidos para número, moeda, percentual e data. Tabelas grandes são perfiladas numa amostra determinística de até 10 mil linhas, e o perfil diz quando é amostra.
- Comando `wolfz inspect ARQUIVO [--sheet] [--header-row] [--sample] [--json]`: perfil das colunas de CSV, `.xlsx`, `.xls` ou `.ods` numa tabela no terminal, ou em JSON.

### Alterado

- Hook `check-added-large-files` do pre-commit passou de 2 MB para 1 MB, o limite do corpus.

## [0.1.0] - 2026-10-16

Primeira versão: receita, três operações e `wolfz run`. Ainda não publicada no PyPI.

### Adicionado

- Pacote `wolfzbr` (`src/wolfz/`) com parsers e validadores brasileiros: moeda, percentual, datas, CPF, CNPJ (inclusive alfanumérico), CEP, telefone, UF, município e código IBGE.
- Receita `.wolfz.json`: modelo validado, serialização estável (mesmos bytes ao carregar e salvar), mensagens de erro com o passo e o campo, migração de versão e JSON Schema (`wolfz schema`).
- Operações `rename`, `drop_rows_where` e `parse_brl`, cada uma com tradução para Polars, Power Query M e script Python.
- Exportação mínima para Power Query M e para script Python autônomo, com teste de equivalência Polars × Python para todas as operações e validação do M pelo parser oficial da Microsoft.
- Motor que aplica a receita e aponta o passo que falhou (`StepError`, no formato Problem Details).
- `wolfz.run(receita, arquivo)` para uso em notebook.
- CLI `wolfz run RECEITA ARQUIVO -o SAIDA` com saída CSV ou Parquet e códigos de saída documentados.
- CI no GitHub Actions (Linux e Windows, Python 3.12 e 3.13), ruff, pre-commit e import-linter.
- Receita e CSV de exemplo (`exemplo.wolfz.json`, `tests/corpus/minimo.csv`).

### Corrigido

- `clean_cnpj` descartava CNPJ alfanumérico válido que parecia notação científica (ex.: `00.000.000/000E-20`).

[Não publicado]: https://github.com/RafaelGomide/WolfzBR/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RafaelGomide/WolfzBR/releases/tag/v0.1.0

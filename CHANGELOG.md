# Changelog

Todas as mudanças relevantes do WolfzBR ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/). Mudança incompatível no formato da receita é versão *major*.

## [Não publicado]

### Adicionado

- API local (`wolfz.api`, FastAPI) com prefixo `/api` e a interface compilada servida na raiz:
  - `POST /projects` (upload: importa, detecta a estrutura e grava a receita inicial), `GET /projects`, `GET /projects/{id}`, `DELETE /projects/{id}`;
  - `GET /projects/{id}/structure`, `GET /projects/{id}/profile`, `GET /projects/{id}/preview` (página após qualquer passo, com cache);
  - `GET`/`PUT /projects/{id}/recipe` com `ETag`/`If-Match` (`409` se a receita mudou em outra aba, `428` sem `If-Match`), gravação atômica a cada edição;
  - `POST /projects/{id}/exports` (CSV, Parquet, Power Query M e script Python; falha se o arquivo já existe, a não ser com `overwrite`);
  - `GET /ops`: catálogo de operações com o JSON Schema de cada uma.
- Segurança da API (§11 do design): bind só em `127.0.0.1` com porta livre aleatória, token de sessão novo a cada start no header `Authorization: Bearer` (na URL de abertura ele vai no fragmento, que o navegador não envia ao servidor), validação do header `Host` contra DNS rebinding, sem CORS (só a origem do Vite com `WOLFZ_DEV=1`) e limite de upload. A documentação interativa da API (`/api/docs`) só existe com `WOLFZ_DEV=1`.
- Erros da API no formato Problem Details (RFC 9457), com `step_id` e `available_columns` quando o erro é de um passo; erro inesperado responde `500` sem detalhe, para não vazar valor de célula.
- Lock por projeto (lock de arquivo do sistema operacional): projeto aberto em outra instância do WolfzBR responde `423` com o endereço dela; o lock é liberado ao fechar o projeto ou encerrar o processo.
- Handlers pesados em threadpool e um preview por projeto por vez.
- Interface web (`frontend/`, React + Vite + Glide Data Grid), servida pela API local:
  - tela inicial com área para arrastar o arquivo e projetos recentes; planilha com mais de uma aba pergunta qual importar;
  - visão bruta da planilha com a estrutura em cores (título, cabeçalho, dados, totais, rodapé) e ajuste da área clicando e arrastando, que atualiza o passo `select_range`;
  - grades antes e depois de cada passo, com rolagem virtualizada e páginas pedidas sob demanda (debounce e cancelamento dos pedidos que ficaram para trás);
  - painel da receita: adicionar, editar, remover, reordenar (arrastando ou com setas) e desativar passos; o formulário de cada passo é gerado do JSON Schema da operação;
  - passo que falha fica destacado, com a mensagem e as colunas disponíveis naquele ponto;
  - perfil da coluna ao clicar no cabeçalho do grid;
  - exportação (CSV, Parquet, Power Query M e script Python) com pasta de saída e confirmação antes de sobrescrever;
  - salvamento automático a cada edição, com aviso quando a receita mudou em outra aba;
  - todos os textos em português, num arquivo só (`frontend/src/textos.ts`).
- O token de sessão é lido do fragmento da URL e fica só na memória da página (nada de `localStorage` ou cookie).
- Passo desativado (`"enabled": false`): fica na receita, mas não roda no motor, no preview nem nas exportações. Receita sem passo desativado continua com os mesmos bytes.
- `POST /sheets`: lista as abas de uma planilha sem criar projeto.
- Respostas da API tipadas no OpenAPI; o cliente TypeScript da interface é gerado dele (`scripts/gerar_openapi.py` e `npm run api`).
- Testes de ponta a ponta com Playwright: importar, editar e exportar; erro de passo; reabrir projeto; escolher aba; ajustar a área.

### Alterado

- `httpx` entra nas dependências de desenvolvimento (cliente de teste do FastAPI).
- O wheel e o sdist levam a interface compilada (`src/wolfz/static/`); o build do pacote falha se ela não tiver sido compilada (`hatch_build.py`). O usuário final não precisa de Node.
- CI ganha o job "Interface": ESLint, Prettier, tipos, build e Playwright.

## [0.3.0] - 2026-10-16

Detecção de estrutura, catálogo de 31 operações e preview com cache. O `wolfz run` passa a ler `.xlsx`, `.xls` e `.ods`. Ainda sem interface: ela chega na 0.4.0, junto com a API local.

### Adicionado

- Detecção de estrutura v1 (`wolfz.core.detect`): métricas por linha (% preenchida, % valor, % texto, negrito, mesclagem), região de dados, cabeçalho de uma linha, totais e subtotais (por palavra-chave ou por negrito raro), título e notas de rodapé, e `fill_down` sugerido por mesclagem vertical. O resultado é uma lista de passos (`select_range`, `header_rows`, `drop_rows_where`, `fill_down`) para a receita inicial; nada é aplicado.
- `estrutura_esperada.json` em cada arquivo do corpus: o gabarito da detecção (cabeçalho, área, colunas, totais e `fill_down`).
- `scripts/medir_deteccao.py`: compara a detecção com o gabarito e imprime uma tabela em Markdown para colar no PR. Na v1: área 95%, cabeçalho 87%, totais 90%, `fill_down` 100% e tudo certo em 77% dos 39 arquivos.
- Teste de regressão da detecção: um arquivo que passa a errar reprova o build; as falhas conhecidas ficam listadas com o motivo.
- Catálogo de operações da F1.E, cada uma com Polars, Power Query M, script Python e teste de equivalência:
  - estrutura: `select_range`, `header_rows` (inclusive cabeçalho em várias linhas e arquivo sem cabeçalho), `drop_empty_rows`, `drop_empty_cols`, `fill_down`, `unpivot`;
  - colunas: `drop_cols`, `reorder`, `cast`, `split_col`, `merge_cols`;
  - texto: `trim` (inclui `\xa0` e caracteres invisíveis), `case`, `remove_accents`, `replace` (literal);
  - padrões brasileiros: `parse_decimal_br`, `parse_percent`, `parse_date_br`, `parse_month_year`, `parse_bool_br`, `clean_cpf` e `clean_cnpj` (com coluna opcional de validade do dígito verificador, CNPJ alfanumérico incluído), `clean_cep`, `normalize_uf`;
  - linhas: `filter` (DSL pequena e traduzível para M), `dedupe`, `fill_null`, `sort`.
- `wolfz.run` e `wolfz run` leem `.xlsx`, `.xls` e `.ods` (a aba da receita, ou a primeira que casa com `sheet_name_regex`). Planilha vem como grade (colunas `A`, `B`, …); CSV vem com cabeçalho, ou como grade quando a receita começa por `select_range` ou `header_rows`.
- As receitas esperadas do corpus rodam de ponta a ponta e são comparadas com o gabarito (72 hoje); a receita inicial proposta pela detecção roda em todos os arquivos do corpus.
- Preview paginado com cache (`wolfz.core.engine.preview`): devolve a página `offset..offset+limit` da tabela depois de qualquer passo, materializando só essa página. Checkpoints por passo em `<projeto>/checkpoints/`, endereçados por uma chave encadeada (hash do raw + passos até ali, sem o `id`): editar o passo N invalida de N em diante sem lógica de invalidação.
- Checkpoint completo para passos caros de recalcular (`unpivot`, `dedupe`, `sort` e os que rodam função Python por valor, como `parse_date_br`); os passos seguintes partem dele.
- Limpeza do cache em LRU até 2 GB no workspace inteiro, pulando projetos abertos (lock ativo) e o projeto em edição; `raw.parquet` e receita nunca são recolhidos.
- `scripts/benchmark_preview.py`: 500 mil linhas, receita de 8 passos, edição do último passo. Medido nesta versão: p50 16 ms e p95 26 ms com cache (SLO: p50 ≤ 300 ms, p95 ≤ 1 s); sem cache, p50 de 12,4 s. A abertura, que grava os checkpoints, leva cerca de 6 s.

### Alterado

- `parse_date_br` lê DDMMAAAA sem o zero do dia (`'1032021'` → 01/03/2021), que é como a data fica depois de passar pelo Excel como número.
- O script Python exportado copia constantes do tipo data das funções de `wolfz.br`.

## [0.2.0] - 2026-10-16

Ingestão completa de planilhas, corpus de testes e `wolfz inspect`. Primeira versão no TestPyPI. O `wolfz run` continua lendo só CSV: aplicar receita a planilha depende da detecção de cabeçalho (0.3.0).

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
- Arquivos do corpus ficam fora da conversão de fim de linha do Git (`.gitattributes`) e do hook `end-of-file-fixer`: são comparados byte a byte.

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

[Não publicado]: https://github.com/RafaelGomide/WolfzBR/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RafaelGomide/WolfzBR/releases/tag/v0.1.0

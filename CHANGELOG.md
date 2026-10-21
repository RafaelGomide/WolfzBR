# Changelog

Todas as mudanças relevantes do WolfzBR ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/). Mudança incompatível no formato da receita é versão *major*.

## [Não publicado]

## [0.7.0] - 2026-10-21

Sugestões automáticas e verificações: o WolfzBR propõe os passos com o motivo de cada um (28 regras, "aceitar todas" por etapa), a receita ganha `assert` que para o Power BI quando o arquivo do mês seguinte vem diferente, `wolfz run` processa vários arquivos de uma vez, a aba que muda de nome é achada pelo padrão e receitas de versões anteriores continuam abrindo. Interface com tema escuro.

### Adicionado

- Operação `assert` (verificação): `not_null`, `unique`, `in_range` (número ou data), `matches` (expressão regular) e `row_count_min`. Não muda os dados; reprovada, a receita para com a mensagem e a primeira linha com problema ("Verificação reprovada"). O script Python faz a mesma verificação; no M vira um `error` que derruba o refresh do Power BI com a mensagem (`matches` não roda no M, que não tem expressão regular).
- Sugestões de verificação a cada salvamento da receita: colunas 100% preenchidas viram `assert not_null`, e código ou documento sem repetição vira `assert unique`.
- `wolfz run` em lote: vários arquivos ou um padrão (`"entrada/*.xlsx"`, expandido pelo próprio `wolfz`, inclusive no PowerShell), `-o` como pasta, um arquivo que falha não para os outros, tabela de resultado e `--report` em JSON.
- Aba que muda de nome todo mês: a importação propõe `source.match.sheet_name_regex` quando o nome da aba tem mês ou número (`DEZEMBRO_2025` aceita `JANEIRO_2026`; `Plan1`, `Sheet1` e afins ficam de fora). A interface mostra e edita o padrão. No M, sem expressão regular, vale a aba com o mesmo molde do nome (mês e dígitos trocados).
- Sugestões automáticas (`wolfz.core.suggest`): regras registradas com `@rule` olham a tabela no fim da receita e propõem passos com confiança e motivo. As primeiras catorze regras: moeda, número e data em texto (com a ordem de AAAAMMDD ou DDMMAAAA), percentual, coluna vazia, espaços extras ou invisíveis, linhas duplicadas, meses em colunas (despivotar), categoria com variação de caixa e acento, CPF e CNPJ com máscara misturada ou zeros perdidos (inclusive na mesma coluna, com o tipo de pessoa), CEP com 7 dígitos, sinais do IBGE e mojibake, mais um aviso para código com zero à esquerda que não deve virar número. Código e ID (`Cód.`, `CD_MUN`, CNPJ já limpo) não são sugeridos como número.
- Interface: painel de sugestões na receita, com aceitar, editar, rejeitar e "aceitar todas". A rejeitada fica gravada no projeto e não volta.
- API: `GET /projects/{id}/suggestions` e `POST /projects/{id}/suggestions/rejections`.
- Uma regra que falha vai para o log (`wolfz.suggest`) e é ignorada; as outras continuam.
- Sugestões novas (agora 28 regras):
  - **tabela larga**: além de meses, anos, safras (`2019/20`, inclusive com nota, `2023/24 (1)`), datas (`1997-01-01 00:00:00`, o cabeçalho de datas do Excel) e trimestres em colunas; colunas numeradas da mesma coisa (`1º Decêndio`, `2º Decêndio`…); categorias que a coluna de total soma (tipos de veículo; dependência administrativa, por bloco do cabeçalho); e as categorias de um cabeçalho em vários níveis. A coluna de total sai antes de despivotar;
  - **linhas**: linhas vazias no meio dos dados; linhas de região e do Brasil numa coluna de UF;
  - **conversões**: o separador decimal decidido pela tabela inteira (nenhuma coluna com vírgula e alguma com ponto que só pode ser decimal: `104.000` é cento e quatro); contagem como texto ou como decimal vira inteiro; valor sentinela (`-9999`) vira vazio antes de converter; mês e ano em colunas separadas viram uma data; mês e ano em texto (`jan/2024`); código e nome na mesma célula (`1. Automóvel`) em duas colunas; marca de nota de rodapé no nome; coluna com o mesmo valor em todas as linhas (fora ano, UF e afins, que diferenciam um arquivo do outro).
- "Aceitar todas" uma etapa por vez: limpar e converter; depois mudar a forma da tabela; por último as verificações. Cada etapa é recalculada na tabela que a anterior deixou. Na mesma etapa, uma sugestão que cita uma coluna que outra tira (o `cast` do ano que o mês e ano juntam) espera a próxima rodada.
- `scripts/medir_sugestoes.py`: mede quanto dos passos necessários as sugestões cobrem, nos 10 arquivos de validação e (`--corpus`) no corpus, com a receita esperada como roteiro. Um teste do corpus guarda o piso (85%, sem contar renomear).
- Corpus: cinco arquivos sintéticos novos (`frota_tipos_com_total`, `safras_regioes`, `estacao_sentinela`, `transferencias_decendios`, `frota_codigo_rotulo`).
- Validação do M da 0.7.0: `scripts/validacao_m.py` gera também `verificacoes_aprovadas`, `verificacao_reprovada` (o refresh tem de parar com a mensagem) e `aba_mes_seguinte` (a consulta acha a aba pelo molde do nome).
- Receitas reais de cada versão publicada (0.1.0 a 0.6.0) em `tests/receitas_antigas/`, gravadas pelo código de cada tag com `scripts/receitas_antigas.py`: o teste abre todas com o WolfzBR atual, passando pela migração, e confere que nenhum parâmetro se perde e que a tabela é a mesma.
- Receita de uma versão mais nova que o WolfzBR instalado: erro próprio (`RecipeTooNewError`) com as duas versões e o comando para atualizar. Na CLI sai com código 2; na API, 422 com o título "Receita de uma versão mais nova do WolfzBR", que a tela do projeto mostra.
- Interface: tema escuro. Por padrão segue o sistema; o botão "Tema" na barra troca entre automático, claro e escuro, e a escolha fica guardada no navegador. A grade, a visão bruta (com as cores da detecção), os painéis e os diálogos têm cores próprias para o escuro, com contraste AA nos dois temas.

### Corrigido

- Detecção: uma coluna de mês (1, 2, 3) fazia a linha de março parecer subtotal (`3 = 1 + 2`) e ela era tirada da tabela. Total pela soma agora precisa de rótulo próprio: 'Grande porte' é subtotal, 'Vitória' repetida em janeiro, fevereiro e março não é.
- A exportação do de-para de municípios rodava as verificações da receita: um `assert` que reprovava nos dados do projeto impedia exportar o M. O de-para agora vai só até o último `normalize_municipio` e pula as verificações.
- Receita com `replace` que apaga a célula (`"new": null`) era gravada sem o campo `new` e depois não abria ("campo obrigatório"). Agora `new` ausente vale nulo, e um teste salva e reabre um passo de cada exemplo de cada operação.
- Abrir ou criar um projeto bem no instante em que a listagem conferia o `.lock` dele dava 423 ("aberto em outra janela") sem ninguém ter o projeto aberto. Apareceu no CI do Linux; agora a abertura espera meio segundo antes de concluir que outra instância segura o lock.
- No Windows, apagar um projeto falhava com "o arquivo já está sendo usado por outro processo" (`.lock`) e o projeto ficava marcado como "aberto em outra janela" até fechar o WolfzBR. O lock do projeto era por thread (padrão do `filelock`): aberto numa requisição e fechado em outra, ele não soltava. Agora o lock vale para o processo, e apagar tira primeiro o conteúdo do projeto e tenta de novo por um instante se a listagem estiver lendo os arquivos no mesmo momento.

## [0.6.0] - 2026-10-18

Pacote brasileiro completo: município casado com a lista oficial do IBGE (com revisão na tela e de-para exportado para o Power BI), sete operações novas de padrões brasileiros e a detecção v2, que reconhece cabeçalho em vários níveis, subtotais pela soma e mais de uma tabela na mesma aba.

### Adicionado

- Lista oficial de municípios do IBGE empacotada (`wolfz/br/data/municipios.parquet`: código de 7 e de 6 dígitos, nome oficial, nome normalizado, UF), gerada por `scripts/atualizar_municipios.py` a partir da API de localidades. Fonte e data da extração no `NOTICE`, que passa a ir no pacote.
- `normalize_municipio`: casa o nome digitado com a lista do IBGE (exato, abreviações como `V. Velha`, `Sto.`, `S.`, e parecido com `rapidfuzz`, restrito à UF quando há coluna de UF) e cria `<coluna>_codigo_ibge`, `<coluna>_nome_ibge` e `<coluna>_status`. Abaixo do limiar, ou com o mesmo nome em mais de uma UF, fica `revisar`, sem código: nada é aplicado em silêncio. As decisões da revisão vão para o `manual` do passo.
- Interface: revisão dos municípios ("Revisar municípios" no passo), com sugestões, aceitar, corrigir buscando na lista do IBGE, marcar que não é município e desfazer. API: `GET /projects/{id}/steps/{step}/municipios` e `GET /municipios`.
- Exportação do de-para (`depara_municipios.csv`) junto com o M e o script Python (ADR-7). O M lê o de-para pelo parâmetro `CaminhoDeparaMunicipios` (exportado em `<nome>.CaminhoDeparaMunicipios.pq`) e faz join exato; município que não está no de-para fica com status `fora_do_depara`, a linha não some.
- Operações novas: `clean_phone` (E.164), `clean_cpf_cnpj` (com a coluna de tipo de pessoa), `split_municipio_uf`, `parse_ibge_value` (com a coluna `<coluna>_situacao`), `scale_by_unit`, `fix_mojibake` e `strip_footnotes`, cada uma em Polars, M e script Python.
- Detecção v2: cabeçalho multinível (o nível de cima é preenchido para a direita e junto com `_`: `Janeiro_Masculino`), subtotais reconhecidos pela soma (inclusive antes dos componentes, como o IBGE publica: "Região Norte" e depois os estados; o total geral é a soma dos subtotais) e várias tabelas na mesma aba (`detect_tables`), empilhadas ou lado a lado. No corpus, os arquivos com tudo certo passam de 77% para 95%.
- Interface: aba com mais de uma tabela mostra as tabelas detectadas e troca a receita para a escolhida.
- `scripts/medir_deteccao.py`: critério `tabelas` (número e área de cada tabela da aba).
- `scripts/validacao_m.py`: conjunto complementar para a validação do M no Power BI (sinais do IBGE, mojibake, CPF ou CNPJ e o de-para de municípios, com o parâmetro `CaminhoDeparaMunicipios`).

### Corrigido

- `scripts/medir_deteccao.py` quebrava no console do Windows ao imprimir ✓.
- Receitas do corpus que esperavam estas operações passam a rodar e a bater com o gabarito; as três tabelas sintéticas do SIDRA ganharam fim explícito no recorte, porque a legenda vem logo abaixo dos dados, sem linha em branco.

## [0.5.0] - 2026-10-18

A receita vira Power Query e Python de verdade: o `.pq` exportado é uma consulta que lê o arquivo de origem e roda sozinha no Power BI (validada no Power BI Desktop com 5 arquivos do corpus), e o script Python lê planilha e CSV do mesmo jeito que o WolfzBR, sem depender dele.

### Adicionado

- Exportação Power Query M completa (`.pq`): consulta `let ... in` que lê o arquivo de origem (`Excel.Workbook` para `.xlsx`/`.xls`, `Csv.Document` com `Encoding` e `Delimiter` detectados na importação), refaz a grade crua (colunas `A`, `B`, …, linha 1 é a linha 1 da aba) e aplica os passos ativos, cada um com nome legível e único no estilo do Power Query (`#"Linhas removidas"`) e o comentário `// s3 drop_rows_where` antes.
- Parâmetro `CaminhoArquivo` exportado num arquivo à parte (`<nome>.CaminhoArquivo.pq`), com a instrução de como criá-lo no Power BI Desktop; para reaplicar a receita a outro arquivo, troca-se só o parâmetro.
- Escapes de identificador, texto e lista do M (`m_identifier`, `m_text`, `m_value`, `m_list`), testados com nomes hostis (`"`, `#"`, quebra de linha, emoji) contra o parser oficial da Microsoft.
- Script Python exportado completo: lê a entrada do mesmo jeito que o `wolfz.run` (planilha `.xlsx`/`.xls`/`.ods` como grade de texto, CSV com encoding e separador detectados), grava `.csv` ou `.parquet` e continua sem depender do WolfzBR. Cabeçalho com a versão do WolfzBR, a data da exportação e o nome da receita.
- `scripts/validacao_m.py`, que gera as consultas e os valores de referência de um subconjunto fixo de 5 arquivos do corpus para a validação manual do M no Power BI Desktop, conferida nesta versão.

### Alterado

- O script Python exportado sai formatado e com os imports ordenados pelo ruff, que passa a ser dependência do pacote.
- Exemplos novos em `filter`, `parse_date_br`, `parse_decimal_br`, `parse_month_year` e `clean_cnpj`: o teste de equivalência cobre todo parâmetro e toda opção de cada operação.
- O `.pq` exportado deixa de ser uma função `(Fonte as table) as table => ...` e passa a ser uma consulta que roda sozinha no Power BI.

## [0.4.0] - 2026-10-17

Primeira versão com interface: `wolfz ui` abre o navegador com a API local, e a planilha é limpa na tela, com a estrutura detectada em cores, a receita editável e a tabela antes e depois de cada passo. Exportação para CSV (pronto para o Excel em português), Excel, Parquet, Power Query M e script Python. Primeira versão no PyPI.

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
  - exportação (CSV, Excel, Parquet, Power Query M e script Python) com opções do CSV, pasta de saída e confirmação antes de sobrescrever;
  - salvamento automático a cada edição, com aviso quando a receita mudou em outra aba;
  - todos os textos em português, num arquivo só (`frontend/src/textos.ts`).
- O token de sessão é lido do fragmento da URL e fica só na memória da página (nada de `localStorage` ou cookie).
- Passo desativado (`"enabled": false`): fica na receita, mas não roda no motor, no preview nem nas exportações. Receita sem passo desativado continua com os mesmos bytes.
- `POST /sheets`: lista as abas de uma planilha sem criar projeto.
- Respostas da API tipadas no OpenAPI; o cliente TypeScript da interface é gerado dele (`scripts/gerar_openapi.py` e `npm run api`).
- Exportação de dados (`wolfz.export.dados`), usada pela API, pela interface e pelo `wolfz run`:
  - CSV sempre em UTF-8 com BOM, com separador (`,`, `;` ou tabulação) e vírgula decimal opcionais. Na interface, o padrão é `;` com vírgula decimal, que abre direto no Excel em português;
  - Excel limpo (`.xlsx`) com os tipos da tabela: data como data (`DD/MM/AAAA`), número como número, sim/não como booleano, cabeçalho em negrito e congelado. Texto é sempre célula de texto, então `=SOMA(...)` nunca vira fórmula. Tabela acima do limite do Excel (linhas, colunas ou texto por célula) dá erro claro, sem gerar arquivo;
  - Parquet com compressão zstd;
  - opção de neutralizar fórmulas no CSV (F0.A9), desligada por padrão: prefixa com `'` o texto que começa com `=`, `+`, `-`, `@`, tabulação ou `\r`. A exportação conta essas células, e a interface e a CLI avisam quando a opção está desligada;
  - build-then-swap para qualquer combinação de arquivos: tudo é gerado numa pasta temporária e só movido no fim. Se algum formato falhar, nenhum arquivo existente é tocado.
- `parse_decimal_br` com `decimal: "auto"`: decide vírgula ou ponto pela coluna inteira. Ponto quando algum valor só faz sentido com ponto decimal, como número do Excel lido como texto (`8725.3480`); senão, vírgula. Mesma regra no motor, no Power Query M e no script Python. É o padrão para passo novo criado na interface; o padrão da operação continua `,`, para receitas antigas não mudarem.
- Interface: "Adicionar todas" e "Limpar" nas listas de colunas dos formulários de passo.
- README com instalação, uso da interface, da CLI e do Python, tabela de formatos e um GIF provisório (`docs/demo.gif`, gerado por `frontend/scripts/capturar_demo.mjs` e `scripts/montar_gif.py`).
- `wolfz ui [--port] [--no-browser]`: sobe a API local e abre a interface no navegador, com a chave de acesso no endereço. Sem `--port`, usa uma porta livre; porta ocupada dá erro claro (código 2).
- `wolfz run --format xlsx`, `--sep`, `--decimal-comma` e `--neutralize-formulas`.
- Testes de ponta a ponta com Playwright: importar, editar e exportar; erro de passo; reabrir projeto; escolher aba; ajustar a área.

### Corrigido

- No Windows, o salvamento automático da receita falhava às vezes ("acesso negado") quando um preview lia o arquivo no mesmo instante. Renomear por cima agora tenta de novo por até 1 s.
- Detecção: cabeçalho de série com datas nas colunas (`1997-01-01 00:00:00`, como o Excel entrega uma célula de data) não era reconhecido. Data ISO passa a contar como rótulo, como o ano já contava. Sem mudança nas métricas do corpus.
- Interface: coluna numérica com nome longo ficava com os valores fora da área visível do grid. A largura inicial vai até 180 px.
- Interface: digitar vários valores num campo de lista ("NORTE, NORDESTE, SUL") criava um item só com o texto inteiro, e o "Remover linhas" com `in` não removia nada. Vírgula, ponto e vírgula e quebra de linha agora separam os itens (colchetes e aspas em volta são ignorados), e o nome exato de uma coluna com vírgula continua inteiro. Achado na cronometragem dos arquivos de validação.
- Interface: texto digitado num campo de lista sem clicar em "Adicionar" se perdia ao aplicar o passo. Agora entra junto.
- Interface: o painel da receita pode ser alargado, para mapas com nomes de coluna longos.
- O sdist levava o `README.md` do corpus de testes: os padrões de `include` agora são ancorados na raiz do repositório.

### Alterado

- O CSV exportado (API e `wolfz run`) passa a ter BOM UTF-8, para o Excel reconhecer a acentuação.
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

[Não publicado]: https://github.com/RafaelGomide/WolfzBR/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/RafaelGomide/WolfzBR/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RafaelGomide/WolfzBR/releases/tag/v0.1.0

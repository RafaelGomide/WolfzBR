# WolfzBR

[![CI](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml/badge.svg)](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml)

**O que é:** um programa que limpa planilhas brasileiras (título, cabeçalho no meio, linha de total, `1.234,56`, `R$`, `31/12/2024`, CPF sem zero) e guarda o passo a passo como uma **receita** reproduzível.
**Para quem:** quem recebe todo mês a mesma planilha suja de um sistema, de uma prefeitura ou do IBGE e precisa dela limpa no Excel, no Power BI ou no Tableau.
**Que problema resolve:** em vez de refazer a limpeza à mão todo mês, você monta a receita uma vez, olhando a tabela, e reaplica no arquivo seguinte, inclusive dentro do Power BI.

Tudo roda na sua máquina. Nenhum dado sai do seu computador.

> **Status:** 1.0. O formato da receita e a API pública em Python seguem o versionamento semântico: o que funciona numa `1.x` continua funcionando nas seguintes.

![Importar a planilha, aceitar as sugestões e exportar o projeto do Power BI](https://raw.githubusercontent.com/RafaelGomide/WolfzBR/main/docs/demo.gif)

## Instalação

Requer Python 3.12 ou mais novo, no Windows ou no Linux (no macOS funciona, mas não é testado). Recomendado com [pipx](https://pipx.pypa.io/), que isola o WolfzBR num ambiente próprio:

```bash
pipx install wolfzbr
```

Para exportar para o Tableau (`.hyper`), instale com o extra (Windows e Linux x64):

```bash
pipx install "wolfzbr[tableau]"
```

Sem pipx, num ambiente virtual: `pip install wolfzbr` (ou `pip install "wolfzbr[tableau]"`). O pacote já traz a interface compilada; não precisa de Node. Para atualizar: `pipx upgrade wolfzbr`.

## Começando

### Na interface

```bash
wolfz ui
```

Abre o navegador com a interface (o endereço só funciona com a chave que o terminal mostra; deixe o terminal aberto, Ctrl+C encerra).

1. **Arraste o arquivo** (`.xlsx`, `.xls`, `.ods` ou `.csv`). Se tiver mais de uma aba, escolha qual.
2. **Confira a estrutura detectada:** título, cabeçalho, dados, totais e rodapé aparecem em cores. Se a área estiver errada, clique e arraste na grade para marcar a certa. Aba com mais de uma tabela mostra todas, e você escolhe qual limpar.
3. **Aceite as sugestões:** o WolfzBR olha a tabela e propõe os passos (moeda e número em texto, datas, CPF e CEP sem zero, espaços invisíveis, acento estragado, meses ou categorias em colunas, mês e ano em colunas separadas…), cada um com o motivo. Aceite, edite, rejeite ou aceite todas.
4. **Ajuste a receita:** adicione, edite, reordene ou desative passos, vendo a tabela antes e depois de cada um. Clique no cabeçalho de uma coluna para ver o perfil dela.
5. **Exporte** nos formatos da [tabela abaixo](#formatos-de-exportação).

A receita é salva sozinha a cada edição, em `~/.wolfz/projects/<id>/recipe.wolfz.json` (o id aparece no endereço da interface).

### No terminal

Aplicar a receita ao arquivo do mês seguinte:

```bash
wolfz run vendas.wolfz.json vendas_fevereiro.xlsx -o saida/ --format xlsx
```

Se algum passo não se aplicar ao arquivo novo (uma coluna mudou de nome, por exemplo), nada é gravado, e a mensagem diz qual passo falhou e quais colunas existem. As **verificações** da receita (coluna sem vazio, código sem repetição, valor numa faixa, número mínimo de linhas) param a execução se o arquivo vier diferente, em vez de gravar uma tabela errada.

Vários arquivos de uma vez (o padrão entre aspas; o próprio `wolfz` expande, inclusive no PowerShell):

```bash
wolfz run vendas.wolfz.json "entrada/*.xlsx" -o saida/ --report relatorio.json
```

Outros comandos: `wolfz inspect planilha.xlsx` (perfil das colunas), `wolfz schema` (JSON Schema da receita) e `wolfz --help`. Códigos de saída do `run`: 0 ok · 1 um passo falhou ou uma verificação reprovou · 2 receita inválida ou uso incorreto · 3 arquivo ilegível.

### Em Python

```python
import wolfz

df = wolfz.run("vendas.wolfz.json", "vendas_fevereiro.xlsx")  # polars.DataFrame
r = wolfz.run_report("vendas.wolfz.json", "vendas_fevereiro.xlsx")  # a tabela e as linhas de cada passo

receita = wolfz.load_recipe("vendas.wolfz.json")  # valida; erro vira wolfz.RecipeError
wolfz.br.parse_brl("R$ 1.234,56")                  # 1234.56
wolfz.br.clean_cpf("529.982.247-25")               # '52998224725'
```

A API pública é `wolfz.run`, `wolfz.run_report` (com `wolfz.RunReport` e `wolfz.StepCount`), `wolfz.load_recipe`, `wolfz.RecipeError`, `wolfz.StepError` e as funções de `wolfz.br` (números, datas, documentos, UF). O resto do pacote é interno e pode mudar em qualquer versão.

## Formatos de exportação

| Formato | O que sai |
|---|---|
| CSV | UTF-8 com BOM; separador `,`, `;` ou tabulação; vírgula decimal opcional. Opção de neutralizar fórmulas (`=`, `+`, `-`, `@`). |
| Excel (`.xlsx`) | Data como data, número como número; texto nunca vira fórmula. |
| Parquet | Tipos preservados, compressão zstd. |
| Power Query M | A receita como consulta M que lê o arquivo de origem, para colar no Power BI ou no Excel. O caminho do arquivo é um parâmetro (`CaminhoArquivo`): para o mês seguinte, troque só o caminho. |
| Power BI (`.pbip`) | Projeto do Power BI Desktop: a tabela com os tipos, `R$` nas colunas de reais, as medidas `Total` e `Contagem de linhas`, e uma tabela calendário opcional em português. A consulta é o M da receita, com o parâmetro `CaminhoArquivo`. |
| Tableau (`.hyper` + `.tds`) | Extrato do Tableau com os tipos certos e uma fonte de dados ao lado, com nomes amigáveis e formato brasileiro (`R$`, `dd/mm/aaaa`). Precisa do extra `[tableau]`. |
| Script Python | A receita como script autônomo, que lê a planilha ou o CSV e grava `.csv` ou `.parquet`. Só depende do Polars (e de `fastexcel` e `python-calamine` para ler planilha). |

Cada operação tem a mesma regra no WolfzBR, no M e no script Python, com teste de equivalência. Guias: [Power BI](docs/guias/power-bi.md) · [Tableau](docs/guias/tableau.md) · [Reaplicando a receita todo mês](docs/guias/todo-mes.md).

## Padrões brasileiros

O catálogo tem 40 operações ([referência completa](docs/operacoes.md)): estrutura (área, cabeçalho em vários níveis, linhas e colunas vazias, preencher para baixo, despivotar), colunas, linhas, texto e padrões brasileiros:

- números (`1.234,56`, `(1,5)`, `10-` do SAP, `R$`) e a escala da unidade ("Mil Reais");
- valores do IBGE com os sinais `-`, `..`, `...` e `X`, sem virar zero o que não é zero;
- percentual, datas, mês/ano e sim/não;
- CPF, CNPJ (inclusive o alfanumérico), coluna com CPF ou CNPJ, CEP, telefone e UF;
- município e UF no mesmo campo ("Vitória - ES");
- **município do IBGE:** casa o nome digitado com a lista oficial (exato, abreviação como "V. Velha" e parecido), com o código de 7 dígitos. O que não casa com segurança fica para você revisar na tela; nada é trocado em silêncio;
- acento estragado (`SÃ£o Paulo`) e marca de nota de rodapé (`Abacaxi*`).

A lista de municípios vem da API de localidades do IBGE e fica dentro do pacote; fonte e data no [NOTICE](NOTICE).

## Privacidade

Nenhum dado sai da sua máquina. O WolfzBR não tem telemetria, não verifica atualização sozinho e a interface não carrega nada de fora (fonte, script ou estilo de CDN). A API local só atende em `127.0.0.1`, com uma chave nova a cada `wolfz ui`. O log não guarda valor de célula, só nomes de coluna e o tipo dos erros. A lista de municípios do IBGE já vem no pacote. Tudo isso tem teste: um fluxo completo roda com a rede bloqueada e procura dado da planilha no log.

Os projetos ficam em `~/.wolfz/`, sem criptografia própria: vale a criptografia de disco do sistema. Para apagar tudo, apague a pasta.

## Limites e limitações conhecidas

- **Arquivo de até 100 MB.** Acima disso, ele é recusado na hora, sem ser lido, com o tamanho e o limite na mensagem.
- **Máquina mínima: 8 GB de memória.** Medido num notebook de 8 GB (Windows 11, Intel Core i7 de 11ª geração, com navegador e editor abertos), com arquivos sintéticos de exportação de sistema (24 colunas: datas, CNPJ, CPF, município, `R$` e valores mensais):

  | Arquivo | Linhas | Importação + detecção | Memória de pico | Preview depois de editar um passo (p50 · p95) |
  |---|---:|---:|---:|---:|
  | CSV de 10 MB | 41 mil | 5 s | 290 MB | 23 ms · 94 ms |
  | `.xlsx` de 10 MB | 53 mil | 4 s | 280 MB | 25 ms · 95 ms |
  | CSV de 50 MB | 204 mil | 16 s | 580 MB | 58 ms · 339 ms |
  | `.xlsx` de 50 MB | 266 mil | 44 s | 680 MB | 37 ms · 594 ms |
  | CSV de 100 MB | 407 mil | 34 s | 950 MB | 26 ms · 346 ms |
  | `.xlsx` de 100 MB | 524 mil | 77 s | 1,2 GB | 79 ms · 706 ms |

  Os tempos variam uns 30% entre rodadas. Para medir na sua máquina: `uv run python scripts/benchmark_carga.py`.
- **Uma tabela por receita.** Aba com várias tabelas: a interface mostra todas, e cada uma é limpa num projeto.
- **A receita fica na pasta do projeto.** A interface ainda não salva o `.wolfz.json` numa pasta escolhida nem aplica uma receita salva a um arquivo novo: copie o arquivo do projeto e reaplique pelo `wolfz run` ou pelo parâmetro do Power BI ([guia](docs/guias/todo-mes.md)).
- **Tableau:** o `.hyper` sai só pela interface, e a Hyper API não tem pacote para macOS nem ARM.
- **Power Query:** a verificação por expressão regular (`matches`) não roda no M, que não tem regex; `.ods` o Power Query não lê (salve como `.xlsx`). Outras diferenças no [guia do Power BI](docs/guias/power-bi.md#diferenças-conhecidas-entre-o-m-e-o-wolfzbr).
- **Município por semelhança** roda no WolfzBR; o M e o script usam a tabela de-para que a exportação grava ao lado.

## Documentação

- [A receita (`.wolfz.json`)](docs/receita.md): o formato, campo a campo, e a compatibilidade entre versões.
- [Operações](docs/operacoes.md): as 40 operações, com parâmetros, exemplos e a tradução em M.
- Guias: [Usando o M exportado no Power BI](docs/guias/power-bi.md) · [Usando o .hyper no Tableau](docs/guias/tableau.md) · [Reaplicando a receita todo mês](docs/guias/todo-mes.md).
- [Desenho técnico](docs/system_design.md) e [mudanças por versão](CHANGELOG.md).

## Contribuindo

Contribuições são bem-vindas: veja o [CONTRIBUTING.md](CONTRIBUTING.md) (ambiente com uv, testes, como adicionar uma operação ou um arquivo ao corpus) e o [código de conduta](CODE_OF_CONDUCT.md). Vulnerabilidade de segurança se reporta em particular, como diz o [SECURITY.md](SECURITY.md).

## Licença

[MIT](LICENSE).

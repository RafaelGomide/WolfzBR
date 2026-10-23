# WolfzBR

[![CI](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml/badge.svg)](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml)

Limpeza de planilhas brasileiras com receitas reproduzíveis. Você arrasta a planilha suja (título, cabeçalho no meio, totais, `1.234,56`, `R$`, datas `31/12/2024`), ajusta os passos na tela e exporta a tabela limpa junto com a **receita**: o mesmo passo a passo em Power Query M e em script Python, para refazer no mês seguinte.

Tudo roda na sua máquina. Nenhum dado sai do seu computador.

> **Status:** pré-alfa (0.8). O formato da receita ainda pode mudar até a 1.0.

![Importar, ajustar a receita e exportar](https://raw.githubusercontent.com/RafaelGomide/WolfzBR/main/docs/demo.gif)

## Instalação

Requer Python 3.12 ou mais novo. Recomendado com [pipx](https://pipx.pypa.io/), que isola o WolfzBR num ambiente próprio:

```bash
pipx install wolfzbr
```

ou com `pip`, num ambiente virtual:

```bash
pip install wolfzbr
```

O pacote já traz a interface compilada; não precisa de Node.

## Uso

### Interface

```bash
wolfz ui
```

Abre o navegador com a interface. Para usar:

1. Arraste o arquivo (`.xlsx`, `.xls`, `.ods` ou `.csv`). Se tiver mais de uma aba, escolha qual.
2. Confira a estrutura detectada: título, cabeçalho, dados, totais e rodapé aparecem em cores. Se a área estiver errada, clique e arraste na grade para marcar a certa.
3. Aceite as sugestões: o WolfzBR olha a tabela e propõe os passos (moeda e número em texto, datas, CPF e CEP sem zero, espaços invisíveis, acento estragado, meses, safras ou categorias em colunas, linhas de região entre as UFs, `-9999` no lugar do vazio, mês e ano em colunas separadas…), cada um com o motivo. Aceite, edite, rejeite ou aceite todas: o "aceitar todas" vai por etapa (limpar e converter, depois mudar a forma da tabela, depois as verificações).
4. Ajuste a receita: adicione, edite, reordene ou desative passos, vendo a tabela antes e depois de cada um. Clique no cabeçalho de uma coluna para ver o perfil dela.
5. Exporte: CSV (pronto para o Excel em português), Excel, Parquet, Power Query M e script Python.

A receita é salva automaticamente a cada edição. O endereço só funciona com a chave de acesso que o terminal mostra, nova a cada execução. Deixe o terminal aberto enquanto usa; Ctrl+C encerra.

Opções: `--port` fixa a porta; `--no-browser` só mostra o endereço, sem abrir o navegador.

### Linha de comando

Aplicar uma receita salva ao arquivo do mês seguinte:

```bash
wolfz run vendas.wolfz.json vendas_fevereiro.xlsx -o saida/ --format xlsx
```

- Se algum passo não se aplicar ao arquivo novo (uma coluna mudou de nome, por exemplo), nada é gravado e a mensagem diz qual passo falhou e quais colunas existem.
- **Verificações** (`assert`): a receita pode conferir o arquivo novo — coluna sem vazio, código sem repetição, valor dentro de uma faixa, formato, número mínimo de linhas. Se o arquivo vier diferente, a execução para com a mensagem em vez de gravar uma tabela errada. A interface sugere as verificações a partir da tabela de hoje.
- **Aba que muda de nome** (`DEZEMBRO_2025` → `JANEIRO_2026`): a importação já propõe o padrão (`source.match.sheet_name_regex`), e a interface mostra e deixa editar.

Vários arquivos de uma vez (o padrão vai entre aspas; o próprio `wolfz` expande, inclusive no PowerShell):

```bash
wolfz run vendas.wolfz.json "entrada/*.xlsx" -o saida/ --report relatorio.json
```

Cada arquivo é processado à parte: um que falha não para os outros. No fim aparece a tabela do que deu certo e do que falhou, e `--report` grava o mesmo em JSON.

Outros comandos:

```bash
wolfz inspect planilha.xlsx      # perfil das colunas no terminal
wolfz schema                     # JSON Schema da receita
wolfz --help
```

Códigos de saída do `run`: 0 ok · 1 um passo falhou ou uma verificação reprovou · 2 receita inválida ou uso incorreto · 3 arquivo ilegível. Em lote, o maior código entre os arquivos.

Receitas antigas continuam abrindo nas versões novas: quando o formato muda, o WolfzBR converte ao carregar (o arquivo só é regravado quando você salva). Já uma receita feita num WolfzBR mais novo que o instalado não é lida pela metade: a mensagem diz as duas versões e pede `pipx upgrade wolfzbr`.

### Em Python

```python
import wolfz

df = wolfz.run("vendas.wolfz.json", "vendas_fevereiro.xlsx")  # polars.DataFrame
```

## Exportação

| Formato | O que sai |
|---|---|
| CSV | UTF-8 com BOM; separador `,`, `;` ou tabulação; vírgula decimal opcional. Opção de neutralizar fórmulas (`=`, `+`, `-`, `@`). |
| Excel (`.xlsx`) | Data como data, número como número; texto nunca vira fórmula. |
| Parquet | Tipos preservados, compressão zstd. |
| Power Query M | A receita como consulta M que lê o arquivo de origem, para colar no Power BI ou no Excel. Vem com o parâmetro `CaminhoArquivo` num arquivo à parte: para o mês seguinte, troque só o caminho. |
| Script Python | A receita como script autônomo, que lê a planilha ou o CSV e grava `.csv` ou `.parquet`. Só depende do Polars (e de `fastexcel` e `python-calamine` para ler planilha). |
| Tableau (`.hyper` + `.tds`) | Extrato do Tableau com os tipos certos (data, número, texto) e uma fonte de dados `.tds` ao lado, com nomes amigáveis e formato brasileiro (`R$`, `dd/mm/aaaa`). Precisa do extra: `pip install "wolfzbr[tableau]"` (Windows e Linux x64). |
| Power BI (`.pbip`) | Projeto do Power BI Desktop: modelo com a tabela, os tipos, `R$` nas colunas de reais e as medidas `Total` e `Contagem de linhas`; a consulta é o M da receita, com o parâmetro `CaminhoArquivo` (para o mês seguinte, troque o parâmetro e atualize). Tabela calendário opcional, com os meses em português. |

## Padrões brasileiros

O catálogo tem 40 operações: estrutura (área, cabeçalho, linhas e colunas vazias, preencher para baixo, despivotar), colunas, texto e padrões brasileiros. Os padrões cobrem:

- números (`1.234,56`, `(1,5)`, `10-` do SAP, `R$`) e a escala da unidade ("Mil Reais");
- valores do IBGE com os sinais `-`, `..`, `...` e `X`, sem virar zero o que não é zero;
- percentual, datas e mês/ano;
- sim/não;
- CPF, CNPJ (inclusive o alfanumérico), coluna com CPF ou CNPJ, CEP, telefone e UF;
- município e UF no mesmo campo ("Vitória - ES");
- **município do IBGE**: casa o nome digitado com a lista oficial (exato, abreviação como "V. Velha" e parecido), com o código de 7 dígitos. O que não casa com segurança fica para você revisar na tela; nada é trocado em silêncio;
- acento estragado (`SÃ£o Paulo`) e marca de nota de rodapé (`Abacaxi*`).

Cada operação tem a mesma regra no motor (Polars), no M e no script Python, com teste de equivalência. A exceção é o casamento de municípios por semelhança, que o M não sabe fazer: a exportação leva junto a tabela de-para (`depara_municipios.csv`) e o M e o script fazem a ligação exata com ela.

A lista de municípios vem da API de localidades do IBGE e fica dentro do pacote (funciona sem internet); fonte e data no [NOTICE](NOTICE).

## Limites

- Arquivo de até 100 MB.
- Uma tabela por aba. Duas tabelas na mesma aba: marque a área de cada uma em projetos separados.
- Cabeçalho em várias linhas é juntado num nome só, mas o cabeçalho mesclado na horizontal ainda não é preenchido. Isso chega na 0.6.

## Documentação

- Desenho técnico: [`docs/system_design.md`](docs/system_design.md)
- Mudanças: [`CHANGELOG.md`](CHANGELOG.md)
- Como contribuir: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Licença

[MIT](LICENSE)

# Reaplicando a receita todo mês

O WolfzBR existe para isto: você limpa a planilha uma vez, e no mês seguinte o arquivo novo (mesmo sistema, mesmo layout, dados novos) sai limpo sem refazer nada. O que permite isso é a **receita** (`.wolfz.json`), o passo a passo da limpeza.

## 1. Guarde a receita

Na primeira vez, monte a receita na interface (`wolfz ui`). Ela é salva sozinha a cada edição, na pasta do projeto:

```
~/.wolfz/projects/<id do projeto>/recipe.wolfz.json
```

O id do projeto aparece no endereço da interface (`…&projeto=01J…`); no Windows, `~` é `C:\Users\<você>`. Copie esse arquivo para um lugar fixo com um nome que diga o que ele limpa (`arrecadacao.wolfz.json`), de preferência numa pasta versionada (Git) ou compartilhada com quem faz o mesmo relatório. É essa cópia que você reaplica nos meses seguintes.

## 2. Torne a receita resistente ao mês seguinte

Alguns cuidados na primeira vez evitam surpresa depois:

- **Recorte a área com fim automático.** No passo "Recortar a área" (`select_range`), use **fim automático** em vez de uma célula final fixa: o arquivo de fevereiro tem mais linhas que o de janeiro.
- **Aba que muda de nome.** Se a aba se chama `JANEIRO_2026` e no mês seguinte vai ser `FEVEREIRO_2026`, confira o padrão do nome da aba que a importação propõe (`source.match.sheet_name_regex` na receita). Com ele, o WolfzBR e o M exportado acham a aba nova sozinhos.
- **Remova totais pela palavra, não pela posição.** "Remover linhas" (`drop_rows_where`) com "começa com Total" continua certo quando o total muda de linha.
- **Ponha verificações.** A interface sugere, a partir da tabela de hoje, verificações (`assert`) como "coluna sem vazio", "código sem repetição", "valor dentro de uma faixa" e "pelo menos N linhas". Se o arquivo do mês vier diferente, a execução para com a mensagem em vez de gravar uma tabela errada.

## 3. Rode no arquivo novo

Pelo terminal, um arquivo:

```bash
wolfz run vendas.wolfz.json vendas_fevereiro.xlsx -o saida/ --format xlsx
```

Ou todos os arquivos de uma pasta de uma vez (o padrão entre aspas; o próprio `wolfz` expande, inclusive no PowerShell):

```bash
wolfz run vendas.wolfz.json "entrada/*.xlsx" -o saida/ --report relatorio.json
```

Cada arquivo é processado à parte: um que falha não para os outros. No fim aparece a tabela do que deu certo e do que falhou; `--report` grava o mesmo em JSON, para automatizar.

Formatos de saída do `run`: `--format csv` (padrão), `xlsx` ou `parquet`. Para o CSV abrir direto no Excel em português, use `--sep ";" --decimal-comma`.

Pelo Python, num notebook ou script:

```python
import wolfz

df = wolfz.run("vendas.wolfz.json", "vendas_fevereiro.xlsx")  # polars.DataFrame
```

Se você usa o **Power BI**, nem precisa rodar o WolfzBR: troque o parâmetro `CaminhoArquivo` e atualize (veja [Usando o M exportado no Power BI](power-bi.md#mês-seguinte)). No **Tableau**, rode e exporte o `.hyper` de novo ([Usando o .hyper no Tableau](tableau.md#mês-seguinte)).

## 4. Quando o arquivo novo é diferente

O `wolfz run` sai com um código que diz o que aconteceu:

| Código | Significado | O que fazer |
|---|---|---|
| 0 | Deu certo. | — |
| 1 | Um passo não se aplicou ou uma verificação reprovou. Nada foi gravado. | Leia a mensagem: ela diz o passo e, se for coluna, quais colunas existem naquele ponto. |
| 2 | Receita inválida, ou uso errado do comando. | A mensagem diz o passo e o campo. |
| 3 | O arquivo de entrada não pôde ser lido (não existe, corrompido, protegido por senha, acima de 100 MB). | Confira o arquivo. |

Em lote, o código é o pior entre os arquivos.

Exemplos comuns e como resolver:

- **Coluna que não existe mais**: o sistema mudou o nome da coluna. A mensagem diz o passo (`s4`) e as colunas que chegam nele. Corrija o nome no passo do `.wolfz.json` (campo `cols`, `col` ou `mapping`) e rode de novo. O formato está em [A receita](../receita.md); `wolfz schema > wolfz.schema.json` dá o JSON Schema para o editor validar e completar.
- **Verificação reprovada**: o arquivo veio com dado duplicado, vazio ou fora da faixa, ou a verificação era rígida demais. Confira o arquivo antes de mexer na receita; se for a verificação, ajuste ou desative o passo (`"enabled": false`).
- **Aba não encontrada**: a aba mudou de nome e a receita não tem o padrão. Acrescente `"match": {"sheet_name_regex": "Vendas \\d{4}"}` em `source`.

Mudança grande de layout (colunas novas no meio, cabeçalho em outra linha) é mais fácil de refazer na interface: importe o arquivo novo, monte a receita olhando a tabela e copie o `recipe.wolfz.json` novo por cima do antigo.

## 5. Atualizando o WolfzBR

```bash
pipx upgrade wolfzbr
```

A receita antiga continua abrindo nas versões novas: o WolfzBR converte ao abrir, e o arquivo só é regravado quando você salva. Uma receita salva numa versão **mais nova** do que a instalada não abre (a mensagem pede para atualizar); por isso, quem divide a receita com outras pessoas deve usar a mesma versão, ou a mais nova. Detalhes em [A receita](../receita.md#versões-do-formato).

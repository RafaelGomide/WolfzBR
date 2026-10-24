# A receita (`.wolfz.json`)

A receita é o passo a passo da limpeza de uma planilha, num arquivo JSON que dá para ler, versionar no Git e reaplicar no arquivo do mês seguinte. É a fonte de verdade de tudo o que o WolfzBR produz: a tabela limpa, a consulta Power Query M, o script Python e os projetos do Tableau e do Power BI saem dela.

Este documento descreve o formato `wolfz_version: "1.0"`. As operações, uma por uma, estão em [`operacoes.md`](operacoes.md).

## Exemplo

```json
{
  "created_at": "2026-10-16T00:00:00Z",
  "name": "Arrecadação por receita",
  "source": {
    "match": {
      "sheet_name_regex": "Arrecadação \\d{4}"
    },
    "sheet": "Arrecadação 2026",
    "type": "excel"
  },
  "steps": [
    {
      "end_detect": "auto",
      "id": "s1",
      "op": "select_range",
      "start": "A4"
    },
    {
      "id": "s2",
      "n": 1,
      "op": "header_rows",
      "separator": " "
    },
    {
      "col": "Código",
      "id": "s3",
      "ignore_case": true,
      "match": "starts_with",
      "op": "drop_rows_where",
      "value": "total"
    },
    {
      "cols": [
        "Arrecadado (R$)"
      ],
      "debit_negative": false,
      "id": "s4",
      "op": "parse_brl"
    },
    {
      "check": "not_null",
      "cols": [
        "Código"
      ],
      "enabled": false,
      "id": "s5",
      "op": "assert"
    }
  ],
  "wolfz_version": "1.0"
}
```

## Campos

| Campo | Tipo | Obrigatório | O que é |
|---|---|---|---|
| `wolfz_version` | texto `"maior.menor"` | sim | Versão do **formato** da receita, não do programa. Hoje, `"1.0"`. |
| `name` | texto | sim | Nome da receita. Vira o nome da tabela e dos arquivos exportados. Não pode ser vazio. |
| `created_at` | data e hora ISO 8601 | sim | Quando a receita foi criada, por exemplo `2026-10-16T14:00:00Z`. |
| `source` | objeto | sim | De onde vêm os dados (abaixo). |
| `steps` | lista de passos | não (padrão: vazia) | Os passos, na ordem em que rodam (abaixo). |

Qualquer campo fora destes é erro, inclusive dentro de `source` e dos passos: um erro de digitação nunca é ignorado em silêncio.

### `source`

| Campo | Tipo | O que é |
|---|---|---|
| `type` | `"excel"`, `"csv"` ou `"ods"` | Tipo do arquivo de origem. `"excel"` vale para `.xlsx`, `.xlsm` e `.xls`. |
| `sheet` | texto, opcional | Nome da aba lida. Sem ele, a primeira aba visível. Não se aplica a CSV. |
| `match.sheet_name_regex` | expressão regular, opcional | Para a aba que muda de nome a cada arquivo (`DEZEMBRO_2025` → `JANEIRO_2026`). Se a aba `sheet` não existe no arquivo novo, vale a primeira cujo nome **inteiro** casa com o padrão. A importação propõe o padrão quando o nome da aba tem mês ou ano. |

A receita não guarda o caminho do arquivo nem a codificação ou o separador do CSV: ela é reaplicada a arquivos diferentes, e a codificação e o separador são detectados a cada leitura.

### Passos

Todo passo tem:

| Campo | Tipo | O que é |
|---|---|---|
| `id` | `"s1"`, `"s2"`, … | Identificador do passo, único na receita. É por ele que as mensagens de erro e a interface se referem ao passo. A ordem de execução é a da lista, não a do número. |
| `op` | texto | O nome da operação: um dos 40 de [`operacoes.md`](operacoes.md). Nome fora do catálogo é erro. |
| `enabled` | sim/não, opcional | `false` deixa o passo na receita sem rodar (desativado na interface). Só é gravado quando é `false`. |

Os outros campos são os parâmetros da operação, todos no mesmo nível do `id` e do `op`.

## Como a receita roda

1. **Leitura.** A planilha vem como grade, tudo como texto: as colunas se chamam `A`, `B`, `C`… e a linha 1 da grade é a linha 1 da planilha. É sobre essa grade que `select_range` e `header_rows` trabalham. O CSV vem com o cabeçalho da primeira linha, a não ser que a receita comece por `select_range` ou `header_rows`: aí ele também vem como grade.
2. **Passos.** Cada passo ativo recebe a tabela do anterior, na ordem da lista. Os tipos mudam só onde um passo muda (`parse_brl` faz número, `parse_date_br` faz data; `cast` converte o resto).
3. **Erro.** Se um passo não se aplica ao arquivo (uma coluna mudou de nome, por exemplo), a execução para com a mensagem do passo e a lista das colunas que existem naquele ponto. Nada é gravado pela metade. Uma verificação (`assert`) que reprova também para.

A mesma receita roda igual na interface, no `wolfz run`, em `wolfz.run()` no Python, no script Python exportado e na consulta M exportada. A exceção conhecida é `normalize_municipio`: o casamento por semelhança roda no WolfzBR, e a exportação leva a tabela de-para que o M e o script usam (detalhes em [`operacoes.md`](operacoes.md#normalize_municipio)).

## Gravação

O arquivo é gravado sempre do mesmo jeito: chaves em ordem alfabética, indentação de 2 espaços, UTF-8 sem BOM, `\n` no fim, e sem os campos que valem `null`. Abrir e salvar uma receita não muda nenhum byte, então o diff no Git mostra só o que mudou de fato. Na leitura, o WolfzBR aceita arquivo com BOM (salvo pelo Bloco de Notas, por exemplo).

## Erros de validação

A receita é validada inteira ao abrir, e cada problema vira uma linha com o passo e o campo:

```
s3.match: valor inválido; esperado 'equals', 'starts_with', 'contains' ou 'in'
s4.cols: precisa de pelo menos 1 item(ns)
s7: operação desconhecida: 'parse_valor'
```

`wolfz schema` imprime o JSON Schema da receita, com todas as operações e parâmetros, para validar ou autocompletar no editor:

```bash
wolfz schema > wolfz.schema.json
```

## Versões do formato

O campo `wolfz_version` é a versão do formato, que muda bem menos que a do programa.

- **Receita antiga abre na versão nova.** Ao abrir, o WolfzBR migra a receita em memória para o formato atual; o arquivo só é regravado quando você salva. Toda versão publicada guarda receitas de teste para garantir isso (`tests/receitas_antigas/`).
- **Receita nova não abre na versão antiga.** Uma receita feita num WolfzBR mais novo que o instalado é recusada com a mensagem das duas versões e o comando para atualizar (`pipx upgrade wolfzbr`). Ela nunca é lida pela metade.
- **A partir da 1.0**, o formato `1.x` é compatível dentro da major: renomear uma operação ou um parâmetro só acontece numa versão 2.0, com migração.

| Formato | Gravado por | Mudança para o seguinte |
|---|---|---|
| `0.1` | WolfzBR 0.1.0 a 0.9.0 | Na 1.0, parâmetros renomeados: `split_col.delimiter` e `header_rows.joiner` viraram `separator`; `clean_cpf.flag` e `clean_cnpj.flag` viraram `add_valid_col`; `parse_ibge_value.status` virou `add_status_col`. A migração faz isso sozinha. |
| `1.0` | WolfzBR 1.0 em diante | — |

## Segurança

Abrir a receita de outra pessoa não executa código: a receita é só dado, validado contra o catálogo fechado de operações. Os nomes de coluna e os valores da receita entram no M e no Python exportados pelas funções de escape de cada linguagem, nunca colados direto no código (§11 do [desenho técnico](system_design.md#11-segurança)).

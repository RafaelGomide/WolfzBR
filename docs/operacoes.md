# Operações

<!-- Gerado por scripts/gerar_operacoes.py a partir do catálogo. Não edite à mão. -->

As 41 operações que um passo de receita pode usar, no formato `wolfz_version: "1.1"`. O formato da receita está em [`receita.md`](receita.md). Cada operação tem a mesma regra no motor (Polars), na consulta Power Query M e no script Python exportados, com teste de equivalência.

Todo passo tem também `id` (`s1`, `s2`, …), `op` (o nome da operação) e, opcional, `enabled` (`false` deixa o passo na receita sem rodar). Os exemplos abaixo são calculados pelo motor a cada geração deste arquivo.

- **Estrutura da tabela**
  - [`select_range`](#select_range): Recortar a área
  - [`header_rows`](#header_rows): Definir o cabeçalho
  - [`drop_empty_rows`](#drop_empty_rows): Remover linhas vazias
  - [`drop_empty_cols`](#drop_empty_cols): Remover colunas vazias
  - [`fill_down`](#fill_down): Preencher para baixo
  - [`unpivot`](#unpivot): Despivotar colunas
- **Colunas**
  - [`rename`](#rename): Renomear colunas
  - [`drop_cols`](#drop_cols): Remover colunas
  - [`reorder`](#reorder): Reordenar colunas
  - [`cast`](#cast): Mudar o tipo
  - [`split_col`](#split_col): Dividir coluna
  - [`merge_cols`](#merge_cols): Juntar colunas
- **Linhas**
  - [`drop_rows_where`](#drop_rows_where): Remover linhas
  - [`filter`](#filter): Filtrar linhas
  - [`dedupe`](#dedupe): Remover duplicadas
  - [`fill_null`](#fill_null): Preencher vazios
  - [`sort`](#sort): Ordenar
- **Texto**
  - [`trim`](#trim): Tirar espaços
  - [`case`](#case): Maiúsculas e minúsculas
  - [`remove_accents`](#remove_accents): Tirar acentos
  - [`replace`](#replace): Substituir texto
- **Padrões brasileiros**
  - [`parse_brl`](#parse_brl): Moeda (R$)
  - [`parse_decimal_br`](#parse_decimal_br): Número brasileiro (1.234,56)
  - [`parse_percent`](#parse_percent): Percentual
  - [`parse_date_br`](#parse_date_br): Data (dd/mm/aaaa)
  - [`parse_datetime_br`](#parse_datetime_br): Data e hora (dd/mm/aaaa hh:mm)
  - [`parse_month_year`](#parse_month_year): Mês/ano
  - [`parse_bool_br`](#parse_bool_br): Sim/não
  - [`clean_cpf`](#clean_cpf): Limpar CPF
  - [`clean_cnpj`](#clean_cnpj): Limpar CNPJ
  - [`clean_cep`](#clean_cep): Limpar CEP
  - [`normalize_uf`](#normalize_uf): Padronizar UF
  - [`clean_phone`](#clean_phone): Limpar telefone
  - [`clean_cpf_cnpj`](#clean_cpf_cnpj): Limpar CPF ou CNPJ
  - [`split_municipio_uf`](#split_municipio_uf): Separar município e UF
  - [`parse_ibge_value`](#parse_ibge_value): Valor do IBGE (-, .., ..., X)
  - [`scale_by_unit`](#scale_by_unit): Escala da unidade (mil, milhões)
  - [`fix_mojibake`](#fix_mojibake): Consertar acentos (SÃ£o → São)
  - [`strip_footnotes`](#strip_footnotes): Tirar marca de nota (*, ¹, (1))
  - [`normalize_municipio`](#normalize_municipio): Município do IBGE
- **Verificações**
  - [`assert`](#assert): Verificar (assert)

## Estrutura da tabela

<a id="select_range"></a>

### `select_range`: Recortar a área

Recorta a área da tabela na grade da planilha.

``start`` é a célula do canto superior esquerdo, em notação A1 (a linha
do cabeçalho, se houver). O fim pode ser ``end`` (canto inferior
direito) ou ``end_detect: "auto"``, que vai até a primeira linha
inteiramente vazia e até a última coluna.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `start` | texto | obrigatório | Célula inicial (ex.: A3) |
| `end` | texto | `null` | Célula final (ex.: F120) |
| `end_detect` | `"auto"` | `null` | Fim automático |

**Exemplo 1**

```json
{"op": "select_range", "start": "B2", "end": "C3"}
```

Antes:

| A | B | C |
|---|---|---|
| `x` | `t` | *nulo* |
| *nulo* | `Nome` | `Valor` |
| *nulo* | `Ana` | `1` |
| *nulo* | `Bia` | `2` |

Depois:

| B | C |
|---|---|
| `Nome` | `Valor` |
| `Ana` | `1` |

**Exemplo 2**

```json
{"op": "select_range", "start": "A2", "end_detect": "auto"}
```

Antes:

| A | B |
|---|---|
| `Título` | *nulo* |
| `Nome` | `Valor` |
| `Ana` | `1` |
| `␠␠` | *nulo* |
| `Fonte: X` | *nulo* |

Depois:

| A | B |
|---|---|
| `Nome` | `Valor` |
| `Ana` | `1` |

**Exemplo 3**

```json
{"op": "select_range", "start": "B1"}
```

Antes:

| A | B | C |
|---|---|---|
| `1` | `3` | `5` |
| `2` | `4` | *nulo* |

Depois:

| B | C |
|---|---|
| `3` | `5` |
| `4` | *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.FirstN(Table.Skip(Table.SelectColumns(Origem, List.Select(Table.ColumnNames(Origem), each WolfzColunaIndice(_) >= 1 and WolfzColunaIndice(_) <= 2)), 1), 2)
```

Usa as funções auxiliares `WolfzColunaIndice`, `WolfzVazia`, declaradas no início da consulta exportada.

<a id="header_rows"></a>

### `header_rows`: Definir o cabeçalho

Promove as ``n`` primeiras linhas a cabeçalho.

Com ``n`` maior que 1 (cabeçalho em várias linhas), as linhas de cima
são preenchidas para a direita, como célula mesclada, e as partes são
unidas com ``separator``: 'Área (ha)' sobre '2022' vira 'Área (ha) 2022'.
Célula de cabeçalho vazia mantém o nome atual; nome repetido ganha
sufixo (_2, _3…). Com ``names``, as ``n`` linhas são descartadas e as
colunas recebem esses nomes, na ordem (arquivo sem cabeçalho: ``n=0``).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `n` | inteiro (mín. 0, máx. 10) | `1` | Linhas de cabeçalho |
| `separator` | texto | `" "` | Separador |
| `names` | lista de colunas | `null` | Nomes das colunas |

**Exemplo 1**

```json
{"op": "header_rows"}
```

Antes:

| A | B | C | D |
|---|---|---|---|
| `Nome` | *nulo* | `Nome` | `␠␠Valor  (R$)␠` |
| `Ana` | `1` | `x` | `2` |

Depois:

| Nome | B | Nome_2 | Valor (R$) |
|---|---|---|---|
| `Ana` | `1` | `x` | `2` |

**Exemplo 2**

```json
{"op": "header_rows", "n": 2}
```

Antes:

| A | B | C |
|---|---|---|
| `Município` | `Área` | *nulo* |
| *nulo* | `2022` | `2023` |
| `Vitória` | `10` | `11` |

Depois:

| Município | Área 2022 | Área 2023 |
|---|---|---|
| `Vitória` | `10` | `11` |

**Exemplo 3**

```json
{"op": "header_rows", "n": 0, "names": ["cnpj", "nome"]}
```

Antes:

| A | B |
|---|---|
| `001` | `X` |
| `002` | `Y` |

Depois:

| cnpj | nome |
|---|---|
| `001` | `X` |
| `002` | `Y` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = WolfzCabecalho(Origem, 1, " ")
```

Usa as funções auxiliares `WolfzCabecalho`, `WolfzNomesUnicos`, declaradas no início da consulta exportada.

<a id="drop_empty_rows"></a>

### `drop_empty_rows`: Remover linhas vazias

Tira as linhas em que todas as células estão vazias (nulas ou só
com espaços).

Sem parâmetros.

**Exemplo 1**

```json
{"op": "drop_empty_rows"}
```

Antes:

| a | b |
|---|---|
| `1` | `x` |
| *nulo* | *nulo* |
| `␠␠` | *nulo* |
| `4` | *nulo* |

Depois:

| a | b |
|---|---|
| `1` | `x` |
| `4` | *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectRows(Origem, each not List.AllTrue(List.Transform(Record.FieldValues(_), WolfzVazia)))
```

Usa as funções auxiliares `WolfzVazia`, declaradas no início da consulta exportada.

<a id="drop_empty_cols"></a>

### `drop_empty_cols`: Remover colunas vazias

Tira as colunas sem nenhuma célula preenchida (colunas de espaçamento
de relatório, 'Valor de Compra' que nunca é preenchido).

Sem parâmetros.

**Exemplo 1**

```json
{"op": "drop_empty_cols"}
```

Antes:

| a | b | c |
|---|---|---|
| `1` | *nulo* | *nulo* |
| *nulo* | `␠␠` | `x` |

Depois:

| a | c |
|---|---|
| `1` | *nulo* |
| *nulo* | `x` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectColumns(Origem, List.Select(Table.ColumnNames(Origem), (c) => not List.AllTrue(List.Transform(Table.Column(Origem, c), WolfzVazia))))
```

Usa as funções auxiliares `WolfzVazia`, declaradas no início da consulta exportada.

<a id="fill_down"></a>

### `fill_down`: Preencher para baixo

Preenche para baixo as células vazias das colunas (categoria mesclada
na vertical, relatório que só escreve o grupo na primeira linha).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "fill_down", "cols": ["regiao"]}
```

Antes:

| regiao | v |
|---|---|
| *nulo* | `0` |
| `Sul` | `1` |
| *nulo* | `2` |
| `␠␠` | `3` |
| `Norte` | `4` |
| *nulo* | `5` |

Depois:

| regiao | v |
|---|---|
| *nulo* | `0` |
| `Sul` | `1` |
| `Sul` | `2` |
| `Sul` | `3` |
| `Norte` | `4` |
| `Norte` | `5` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.FillDown(Table.TransformColumns(Origem, {{"regiao", each if WolfzVazia(_) then null else _}}), {"regiao"})
```

Usa as funções auxiliares `WolfzVazia`, declaradas no início da consulta exportada.

<a id="unpivot"></a>

### `unpivot`: Despivotar colunas

Despivota: as colunas fora de ``index`` (meses lado a lado, anos)
viram duas colunas, nome e valor. A saída vai linha a linha e sem os
valores nulos, como o ``Table.UnpivotOtherColumns`` do Power Query.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `index` | lista de colunas | obrigatório | Colunas que ficam |
| `variable_name` | texto | `"variavel"` | Nome da coluna de variável |
| `value_name` | texto | `"valor"` | Nome da coluna de valor |

**Exemplo 1**

```json
{"op": "unpivot", "index": ["uf"], "variable_name": "mes"}
```

Antes:

| uf | jan | fev |
|---|---|---|
| `ES` | `1` | `2` |
| `RJ` | `3` | *nulo* |

Depois:

| uf | mes | valor |
|---|---|---|
| `ES` | `jan` | `1` |
| `ES` | `fev` | `2` |
| `RJ` | `jan` | `3` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.UnpivotOtherColumns(Origem, {"uf"}, "mes", "valor")
```

## Colunas

<a id="rename"></a>

### `rename`: Renomear colunas

Renomeia colunas. Coluna de origem inexistente é erro na execução:
a receita nunca renomeia "nada" em silêncio quando a planilha muda.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `mapping` | mapa de texto para (texto) | obrigatório | Nome atual -> nome novo. |

**Exemplo 1**

```json
{"op": "rename", "mapping": {"Vlr Venda": "valor", "Nº \"Pedido\"": "pedido"}}
```

Antes:

| Vlr Venda | Nº "Pedido" | UF |
|---|---|---|
| `1` | `7` | `ES` |

Depois:

| valor | pedido | UF |
|---|---|---|
| `1` | `7` | `ES` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.RenameColumns(Origem, {{"Vlr Venda", "valor"}, {"Nº ""Pedido""", "pedido"}})
```

<a id="drop_cols"></a>

### `drop_cols`: Remover colunas

Remove colunas. Coluna inexistente é erro: a receita nunca remove
"nada" em silêncio quando a planilha muda.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "drop_cols", "cols": ["obs", "id"]}
```

Antes:

| id | nome | obs |
|---|---|---|
| `1` | `Ana` | `x` |

Depois:

| nome |
|---|
| `Ana` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.RemoveColumns(Origem, {"obs", "id"})
```

<a id="reorder"></a>

### `reorder`: Reordenar colunas

Põe as colunas na ordem pedida. Com ``keep_rest`` (padrão), as
colunas não citadas vêm depois, na ordem em que estavam; sem ele, saem.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `keep_rest` | sim/não | `true` | Manter as outras colunas no fim |

**Exemplo 1**

```json
{"op": "reorder", "cols": ["valor", "data"]}
```

Antes:

| data | uf | valor | obs |
|---|---|---|---|
| `d` | `ES` | `1` | `o` |

Depois:

| valor | data | uf | obs |
|---|---|---|---|
| `1` | `d` | `ES` | `o` |

**Exemplo 2**

```json
{"op": "reorder", "cols": ["valor", "data"], "keep_rest": false}
```

Antes:

| data | uf | valor |
|---|---|---|
| `d` | `ES` | `1` |

Depois:

| valor | data |
|---|---|
| `1` | `d` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectColumns(Origem, {"valor", "data"} & List.Difference(Table.ColumnNames(Origem), {"valor", "data"}))
```

<a id="cast"></a>

### `cast`: Mudar o tipo

Converte o tipo das colunas: ``text``, ``int``, ``float``, ``date``
ou ``bool``. Pensado para os valores como a leitura entrega (número com
ponto decimal, data ISO, 'true'/'false'). Para número e data em formato
brasileiro, use ``parse_decimal_br`` e ``parse_date_br``. Valor que não
converte vira nulo; ``int`` com casas decimais também.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `types` | mapa de texto para (um de: `"text"`, `"int"`, `"float"`, `"date"`, `"bool"`) | obrigatório | Tipos |

**Exemplo 1**

```json
{"op": "cast", "types": {"q": "int", "v": "float", "d": "date", "b": "bool", "t": "text"}}
```

Antes:

| q | v | d | b | t |
|---|---|---|---|---|
| `12` | `1234.5` | `2024-01-31 00:00:00` | `true` | `a` |
| `␠3␠` | `-0.25` | `2024-02-29` | `FALSE` | *nulo* |
| `1.5` | `1e3` | `31/01/2024` | `sim` | `1` |
| `abc` | `1,234` | *nulo* | *nulo* | `b` |
| *nulo* | `inf` | `2023-02-30` | `""` | `c` |

Depois:

| q | v | d | b | t |
|---|---|---|---|---|
| `12` | 1234.5 | 2024-01-31 | verdadeiro | `a` |
| `3` | -0.25 | 2024-02-29 | falso | *nulo* |
| *nulo* | 1000.0 | *nulo* | *nulo* | `1` |
| *nulo* | *nulo* | *nulo* | *nulo* | `b` |
| *nulo* | *nulo* | *nulo* | *nulo* | `c` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"q", each let x = WolfzNumeroPonto(_) in if x <> null and Number.Round(x) = x then try Int64.From(x) otherwise null else null, Int64.Type}, {"v", each WolfzNumeroPonto(_), type nullable number}, {"d", each if _ is date then _ else if _ is datetime then Date.From(_) else if _ = null then null else try Date.FromText(Text.Start(Text.Trim(Text.From(_)), 10), [Format="yyyy-MM-dd", Culture="en-US"]) otherwise null, type nullable date}, {"b", each if _ is logical then _ else if _ = null then null else let t = Text.Lower(Text.Trim(Text.From(_))) in if t = "true" then true else if t = "false" then false else null, type nullable logical}, {"t", each if _ = null then null else Text.From(_, "en-US"), type nullable text}})
```

Usa as funções auxiliares `WolfzNumeroPonto`, declaradas no início da consulta exportada.

<a id="split_col"></a>

### `split_col`: Dividir coluna

Divide uma coluna por um delimitador literal (não é regex) em
``into`` colunas, no lugar da original. A última parte fica com o resto
do texto; parte que falta fica nula.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `separator` | texto | obrigatório | Separador |
| `into` | lista de colunas | obrigatório | Novas colunas |

**Exemplo 1**

```json
{"op": "split_col", "col": "mun_uf", "separator": " - ", "into": ["municipio", "uf"]}
```

Antes:

| id | mun_uf |
|---|---|
| `1` | `Vitória - ES` |
| `2` | `Serra` |
| `3` | *nulo* |
| `4` | `A - B - C` |

Depois:

| id | municipio | uf |
|---|---|---|
| `1` | `Vitória` | `ES` |
| `2` | `Serra` | *nulo* |
| `3` | *nulo* | *nulo* |
| `4` | `A` | `B - C` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SplitColumn(Origem, "mun_uf", Splitter.SplitTextByEachDelimiter({" - "}), {"municipio", "uf"})
```

<a id="merge_cols"></a>

### `merge_cols`: Juntar colunas

Junta colunas em uma só (``into``), na posição da primeira delas,
com ``separator`` entre os valores. Célula nula é pulada. Com ``keep``,
as colunas originais ficam.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `separator` | texto | `""` | Separador |
| `into` | texto | obrigatório | Novas colunas |
| `keep` | sim/não | `false` | Manter as colunas originais |

**Exemplo 1**

```json
{"op": "merge_cols", "cols": ["mes", "ano"], "separator": "/", "into": "competencia"}
```

Antes:

| id | mes | ano |
|---|---|---|
| `1` | `JAN` | `2024` |
| `2` | *nulo* | `2024` |
| `3` | `MAR` | *nulo* |

Depois:

| id | competencia |
|---|---|
| `1` | `JAN/2024` |
| `2` | `2024` |
| `3` | `MAR` |

**Exemplo 2**

```json
{"op": "merge_cols", "cols": ["a", "b"], "separator": "-", "into": "ab", "keep": true}
```

Antes:

| a | b |
|---|---|
| `1` | `2` |

Depois:

| ab | a | b |
|---|---|---|
| `1-2` | `1` | `2` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectColumns(Table.AddColumn(Origem, "competencia", each Text.Combine(List.Transform({Record.Field(_, "mes"), Record.Field(_, "ano")}, (v) => if v = null then null else Text.From(v, "en-US")), "/"), type text), List.InsertRange(List.RemoveItems(Table.ColumnNames(Origem), {"mes", "ano"}), List.Min(List.Transform({"mes", "ano"}, each List.PositionOf(Table.ColumnNames(Origem), _))), {"competencia"}))
```

## Linhas

<a id="drop_rows_where"></a>

### `drop_rows_where`: Remover linhas

Remove as linhas em que a coluna casa com a condição.

Sem regex de propósito: Power Query M não tem expressão regular nativa,
e toda operação precisa ter tradução fiel para M (ADR-2). Por isso a
condição se limita ao que as funções de texto do M expressam:

- ``equals``: valor igual a ``value``;
- ``starts_with``: começa com ``value`` (``Text.StartsWith``);
- ``contains``: contém ``value`` (``Text.Contains``);
- ``in``: valor é um dos itens da lista ``value`` (``List.Contains``).

A comparação é exata: espaços e acentos contam (normalize antes, se
preciso). ``ignore_case`` ignora maiúsculas/minúsculas. Célula vazia
(nula) nunca casa, então a linha fica.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `match` | um de: `"equals"`, `"starts_with"`, `"contains"`, `"in"` | obrigatório | Condição |
| `value` | texto ou lista de (texto) | obrigatório | Valor |
| `ignore_case` | sim/não | `false` | Ignorar maiúsculas/minúsculas |

**Exemplo 1**

```json
{"op": "drop_rows_where", "col": "regiao", "match": "starts_with", "value": "Total"}
```

Antes:

| regiao | v |
|---|---|
| `Sul` | `1` |
| `Total Sul` | `2` |
| `Totalmente` | `3` |
| *nulo* | `4` |
| `total` | `5` |

Depois:

| regiao | v |
|---|---|
| `Sul` | `1` |
| *nulo* | `4` |
| `total` | `5` |

**Exemplo 2**

```json
{"op": "drop_rows_where", "col": "regiao", "match": "contains", "value": "total", "ignore_case": true}
```

Antes:

| regiao | v |
|---|---|
| `Sul` | `1` |
| `Subtotal` | `2` |
| `TOTAL` | `3` |
| *nulo* | `4` |

Depois:

| regiao | v |
|---|---|
| `Sul` | `1` |
| *nulo* | `4` |

**Exemplo 3**

```json
{"op": "drop_rows_where", "col": "uf", "match": "equals", "value": "-"}
```

Antes:

| uf |
|---|
| `ES` |
| `-` |
| `␠-` |
| *nulo* |

Depois:

| uf |
|---|
| `ES` |
| `␠-` |
| *nulo* |

**Exemplo 4**

```json
{"op": "drop_rows_where", "col": "uf", "match": "in", "value": ["xx", "Br"], "ignore_case": true}
```

Antes:

| uf |
|---|
| `ES` |
| `XX` |
| `br` |
| `SP` |

Depois:

| uf |
|---|
| `ES` |
| `SP` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectRows(Origem, each let v = Text.From(Record.Field(_, "regiao")) in v = null or not (Text.StartsWith(v, "Total")))
```

<a id="filter"></a>

### `filter`: Filtrar linhas

Mantém as linhas que atendem a uma condição sobre uma coluna.

É uma DSL pequena, traduzível para M, e não uma expressão livre:
``equals``, ``not_equals``, ``gt``, ``ge``, ``lt``, ``le``, ``in``,
``not_in``, ``contains``, ``starts_with``, ``is_null`` e ``not_null``.
Data é comparada com texto ISO ('2024-01-31'). Célula nula só passa em
``is_null``.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `match` | um de: `"equals"`, `"not_equals"`, `"gt"`, `"ge"`, `"lt"`, `"le"`, `"in"`, `"not_in"`, `"contains"`, `"starts_with"`, `"is_null"`, `"not_null"` | obrigatório | Condição |
| `value` | texto ou inteiro ou número ou sim/não ou lista de (texto ou inteiro ou número ou sim/não) | `null` | Valor |
| `ignore_case` | sim/não | `false` | Ignorar maiúsculas/minúsculas |

**Exemplo 1**

```json
{"op": "filter", "col": "mes", "match": "in", "value": ["JAN", "FEV"]}
```

Antes:

| mes | v |
|---|---|
| `JAN` | `1` |
| `ANO` | `2` |
| *nulo* | `3` |
| `FEV` | `4` |

Depois:

| mes | v |
|---|---|
| `JAN` | `1` |
| `FEV` | `4` |

**Exemplo 2**

```json
{"op": "filter", "col": "v", "match": "ge", "value": 2}
```

Antes:

| v |
|---|
| `1` |
| `2` |
| *nulo* |
| `5` |

Depois:

| v |
|---|
| `2` |
| `5` |

**Exemplo 3**

```json
{"op": "filter", "col": "d", "match": "lt", "value": "2024-06-01"}
```

Antes:

| d |
|---|
| 2024-01-01 |
| 2025-01-01 |

Depois:

| d |
|---|
| 2024-01-01 |

**Exemplo 4**

```json
{"op": "filter", "col": "nome", "match": "contains", "value": "silva", "ignore_case": true}
```

Antes:

| nome |
|---|
| `Ana Silva` |
| `Bia` |
| *nulo* |

Depois:

| nome |
|---|
| `Ana Silva` |

**Exemplo 5**

```json
{"op": "filter", "col": "obs", "match": "is_null"}
```

Antes:

| obs | id |
|---|---|
| *nulo* | `1` |
| `x` | `2` |

Depois:

| obs | id |
|---|---|
| *nulo* | `1` |

**Exemplo 6**

```json
{"op": "filter", "col": "uf", "match": "equals", "value": "ES"}
```

Antes:

| uf |
|---|
| `ES` |
| `es` |
| `RJ` |
| *nulo* |

Depois:

| uf |
|---|
| `ES` |

**Exemplo 7**

```json
{"op": "filter", "col": "uf", "match": "not_equals", "value": "es", "ignore_case": true}
```

Antes:

| uf |
|---|
| `ES` |
| `RJ` |
| *nulo* |

Depois:

| uf |
|---|
| `RJ` |

**Exemplo 8**

```json
{"op": "filter", "col": "v", "match": "gt", "value": 2.5}
```

Antes:

| v |
|---|
| 1.0 |
| 2.5 |
| 3.0 |
| *nulo* |

Depois:

| v |
|---|
| 3.0 |

**Exemplo 9**

```json
{"op": "filter", "col": "v", "match": "le", "value": 2}
```

Antes:

| v |
|---|
| `1` |
| `2` |
| `3` |
| *nulo* |

Depois:

| v |
|---|
| `1` |
| `2` |

**Exemplo 10**

```json
{"op": "filter", "col": "mes", "match": "not_in", "value": ["TOTAL", "ANO"]}
```

Antes:

| mes |
|---|
| `JAN` |
| `TOTAL` |
| *nulo* |
| `ANO` |

Depois:

| mes |
|---|
| `JAN` |

**Exemplo 11**

```json
{"op": "filter", "col": "obs", "match": "not_null"}
```

Antes:

| obs |
|---|
| *nulo* |
| `x` |
| `""` |

Depois:

| obs |
|---|
| `x` |
| `""` |

**Exemplo 12**

```json
{"op": "filter", "col": "conta", "match": "starts_with", "value": "1.1"}
```

Antes:

| conta |
|---|
| `1.1.01` |
| `1.2` |
| `11` |
| *nulo* |

Depois:

| conta |
|---|
| `1.1.01` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.SelectRows(Origem, each let v = Record.Field(_, "mes") in v <> null and List.Contains({"JAN", "FEV"}, v))
```

<a id="dedupe"></a>

### `dedupe`: Remover duplicadas

Remove linhas repetidas, mantendo a primeira. Com ``cols``, compara
só essas colunas; sem, a linha inteira.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | `null` | Colunas |

**Exemplo 1**

```json
{"op": "dedupe"}
```

Antes:

| a | b |
|---|---|
| `1` | `x` |
| `1` | `x` |
| `2` | `y` |
| `1` | `z` |

Depois:

| a | b |
|---|---|
| `1` | `x` |
| `2` | `y` |
| `1` | `z` |

**Exemplo 2**

```json
{"op": "dedupe", "cols": ["a"]}
```

Antes:

| a | b |
|---|---|
| `1` | `x` |
| `1` | `y` |
| `2` | `z` |

Depois:

| a | b |
|---|---|
| `1` | `x` |
| `2` | `z` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.Distinct(Origem)
```

<a id="fill_null"></a>

### `fill_null`: Preencher vazios

Preenche células nulas com um valor fixo.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `value` | texto ou inteiro ou número ou sim/não | obrigatório | Valor |

**Exemplo 1**

```json
{"op": "fill_null", "cols": ["obs"], "value": "sem observação"}
```

Antes:

| obs |
|---|
| *nulo* |
| `ok` |

Depois:

| obs |
|---|
| `sem observação` |
| `ok` |

**Exemplo 2**

```json
{"op": "fill_null", "cols": ["q"], "value": 0}
```

Antes:

| q |
|---|
| *nulo* |
| `3` |

Depois:

| q |
|---|
| `0` |
| `3` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.ReplaceValue(Origem, null, "sem observação", Replacer.ReplaceValue, {"obs"})
```

<a id="sort"></a>

### `sort`: Ordenar

Ordena pelas colunas de ``by``. ``descending`` vale para todas ou é
uma lista, uma por coluna. Nulos ficam como no Power Query: no começo da
ordem crescente e no fim da decrescente. Empate mantém a ordem original.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `by` | lista de colunas | obrigatório | Ordenar por |
| `descending` | sim/não ou lista de (sim/não) | `false` | Decrescente |

**Exemplo 1**

```json
{"op": "sort", "by": ["uf", "v"], "descending": [false, true]}
```

Antes:

| uf | v |
|---|---|
| `SP` | `1` |
| `ES` | `2` |
| *nulo* | `3` |
| `ES` | `5` |

Depois:

| uf | v |
|---|---|
| *nulo* | `3` |
| `ES` | `5` |
| `ES` | `2` |
| `SP` | `1` |

**Exemplo 2**

```json
{"op": "sort", "by": ["v"], "descending": true}
```

Antes:

| v |
|---|
| `1` |
| *nulo* |
| `3` |

Depois:

| v |
|---|
| `3` |
| `1` |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.Sort(Origem, {{"uf", Order.Ascending}, {"v", Order.Descending}})
```

## Texto

<a id="trim"></a>

### `trim`: Tirar espaços

Apara espaços nas pontas, inclusive o espaço não separável (\xa0)
que vem de páginas web e PDFs, e remove caracteres invisíveis
(zero-width, BOM, hífen suave) de qualquer posição. Com
``collapse_spaces``, espaços repetidos no meio viram um só.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `collapse_spaces` | sim/não | `false` | Juntar espaços repetidos |

**Exemplo 1**

```json
{"op": "trim", "cols": ["nome"]}
```

Antes:

| nome |
|---|
| `␠␠Ana␠` |
| `\u00a0Bia\u200b` |
| `Car  la\t` |
| *nulo* |
| `␠␠␠␠␠␠` |

Depois:

| nome |
|---|
| `Ana` |
| `Bia` |
| `Car  la` |
| *nulo* |
| `""` |

**Exemplo 2**

```json
{"op": "trim", "cols": ["nome"], "collapse_spaces": true}
```

Antes:

| nome |
|---|
| `␠S\u00e3o \u00a0 Paulo␠` |
| `a\t\tb` |

Depois:

| nome |
|---|
| `São Paulo` |
| `a b` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"nome", each if _ = null then null else Text.Trim(Text.Remove(Text.From(_), {"​", "‌", "‍", "⁠", "﻿", "­"}), {" ", "#(tab)", "#(cr)", "#(lf)", " ", " ", " ", " ", "　"}), type nullable text}})
```

<a id="case"></a>

### `case`: Maiúsculas e minúsculas

Maiúsculas (``upper``), minúsculas (``lower``) ou a primeira letra
de cada palavra em maiúscula (``title``).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `mode` | um de: `"upper"`, `"lower"`, `"title"` | obrigatório | Modo |

**Exemplo 1**

```json
{"op": "case", "cols": ["a"], "mode": "upper"}
```

Antes:

| a |
|---|
| `são paulo` |
| *nulo* |

Depois:

| a |
|---|
| `SÃO PAULO` |
| *nulo* |

**Exemplo 2**

```json
{"op": "case", "cols": ["a"], "mode": "lower"}
```

Antes:

| a |
|---|
| `ÉRICA` |

Depois:

| a |
|---|
| `érica` |

**Exemplo 3**

```json
{"op": "case", "cols": ["a"], "mode": "title"}
```

Antes:

| a |
|---|
| `JOÃO DA SILVA` |
| `vila velha` |

Depois:

| a |
|---|
| `João Da Silva` |
| `Vila Velha` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"a", each if _ = null then null else Text.Upper(Text.From(_)), type nullable text}})
```

<a id="remove_accents"></a>

### `remove_accents`: Tirar acentos

Tira acentos e cedilha: 'São José' -> 'Sao Jose'. Mantém caixa e
pontuação. Usa uma tabela fixa de letras latinas (À a ſ), a mesma no
Polars e no M, que não tem função nativa para isso.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "remove_accents", "cols": ["m"]}
```

Antes:

| m |
|---|
| `São José do Calçado` |
| `ÁGUA DOCE` |
| `Itaú-Ünião` |
| *nulo* |
| `abc` |

Depois:

| m |
|---|
| `Sao Jose do Calcado` |
| `AGUA DOCE` |
| `Itau-Uniao` |
| *nulo* |
| `abc` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"m", each if _ = null then null else WolfzSemAcento(Text.From(_)), type nullable text}})
```

Usa as funções auxiliares `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="replace"></a>

### `replace`: Substituir texto

Substitui texto literal (não é regex: o M não tem regex nativa).

Por padrão troca cada ocorrência de ``old`` dentro da célula. Com
``whole`` (ou com ``new`` nulo), troca só a célula inteira igual a
``old``: ``{"old": "31.12.9999", "new": null}`` apaga a data sentinela.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `old` | texto | obrigatório | Procurar |
| `new` | texto | `null` | Trocar por |
| `whole` | sim/não | `false` | Só o valor inteiro |

**Exemplo 1**

```json
{"op": "replace", "cols": ["v"], "old": " ", "new": ""}
```

Antes:

| v |
|---|
| `95 626 753` |
| `12` |
| *nulo* |

Depois:

| v |
|---|
| `95626753` |
| `12` |
| *nulo* |

**Exemplo 2**

```json
{"op": "replace", "cols": ["d"], "old": "31.12.9999"}
```

Antes:

| d |
|---|
| `31.12.9999` |
| `01.02.2024` |
| `31.12.99999` |

Depois:

| d |
|---|
| *nulo* |
| `01.02.2024` |
| `31.12.99999` |

**Exemplo 3**

```json
{"op": "replace", "cols": ["s"], "old": "N/I", "new": "não informado", "whole": true}
```

Antes:

| s |
|---|
| `N/I` |
| `N/I X` |
| *nulo* |

Depois:

| s |
|---|
| `não informado` |
| `N/I X` |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"v", each if _ = null then null else Text.Replace(Text.From(_), " ", "")}})
```

## Padrões brasileiros

<a id="parse_brl"></a>

### `parse_brl`: Moeda (R$)

Converte moeda brasileira em número: 'R$ 1.234,56' -> 1234.56.

Aceita negativo contábil '(1.234,56)', menos no fim (SAP), '-' como zero
(formato contábil do Excel) e, com ``debit_negative``, sufixo D/C com
débito negativo. Valor que não é moeda vira nulo, nunca um número
errado (ver ``wolfz.br.numeros.parse_brl``).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `debit_negative` | sim/não | `false` | D (débito) vira negativo |

**Exemplo 1**

```json
{"op": "parse_brl", "cols": ["valor"]}
```

Antes:

| valor |
|---|
| `R$ 1.234,56` |
| `(1.234,56)` |
| `1.234,56-` |
| `R$ -` |
| `#N/D` |
| *nulo* |
| `12%` |
| `1,5E+3` |

Depois:

| valor |
|---|
| 1234.56 |
| -1234.56 |
| -1234.56 |
| 0.0 |
| *nulo* |
| *nulo* |
| *nulo* |
| 1500.0 |

**Exemplo 2**

```json
{"op": "parse_brl", "cols": ["debito", "credito"], "debit_negative": true}
```

Antes:

| debito | credito |
|---|---|
| `100,00 D` | `R$ 10` |
| `50,00 C` | `abc` |

Depois:

| debito | credito |
|---|---|
| -100.0 | 10.0 |
| 50.0 | *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"valor", each WolfzParseBrl(_, false), type nullable number}})
```

Usa as funções auxiliares `WolfzParseBrl`, declaradas no início da consulta exportada.

<a id="parse_decimal_br"></a>

### `parse_decimal_br`: Número brasileiro (1.234,56)

Número em formato brasileiro: '1.234,56' -> 1234.56. Aceita
negativo contábil '(1,5)', menos no fim (SAP), símbolo de moeda,
espaço como milhar e notação científica. Valor com '%' vira nulo (use
``parse_percent``). ``decimal='.'`` para bases que publicam ponto
decimal; ``decimal='auto'`` decide pela coluna inteira (ponto quando
algum valor só faz sentido com ponto decimal, como número do Excel lido
como texto: '8725.3480').

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `decimal` | um de: `","`, `"."`, `"auto"` | `","` | Separador decimal |
| `dash_is_zero` | sim/não | `false` | Traço vale zero |
| `debit_negative` | sim/não | `false` | D (débito) vira negativo |

**Exemplo 1**

```json
{"op": "parse_decimal_br", "cols": ["v"]}
```

Antes:

| v |
|---|
| `1.234,56` |
| `(1,5)` |
| `10-` |
| `R$ 3` |
| `1 234,5` |
| `12%` |
| `-` |
| `abc` |

*… mais 2 linhas.*

Depois:

| v |
|---|
| 1234.56 |
| -1.5 |
| -10.0 |
| 3.0 |
| 1234.5 |
| *nulo* |
| *nulo* |
| *nulo* |

*… mais 2 linhas.*

**Exemplo 2**

```json
{"op": "parse_decimal_br", "cols": ["v"], "decimal": ".", "dash_is_zero": true}
```

Antes:

| v |
|---|
| `1.234` |
| `1,234.5` |
| `-` |

Depois:

| v |
|---|
| 1.234 |
| 1234.5 |
| 0.0 |

**Exemplo 3**

```json
{"op": "parse_decimal_br", "cols": ["v", "w"], "decimal": "auto"}
```

Antes:

| v | w |
|---|---|
| `8725.3480` | `1.234` |
| `0.125` | `2,5` |
| `1` | `1.234.567` |
| *nulo* | *nulo* |

Depois:

| v | w |
|---|---|
| 8725.348 | 1234.0 |
| 0.125 | 2.5 |
| 1.0 | 1234567.0 |
| *nulo* | *nulo* |

**Exemplo 4**

```json
{"op": "parse_decimal_br", "cols": ["v"], "debit_negative": true}
```

Antes:

| v |
|---|
| `1.234,56 D` |
| `10,00 C` |
| `5,00` |
| `7,5D` |
| *nulo* |

Depois:

| v |
|---|
| -1234.56 |
| 10.0 |
| 5.0 |
| -7.5 |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"v", each WolfzNumeroBr(_, false, false, "pt-BR"), type nullable number}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzDecimalProvavel`, `WolfzEspacos`, `WolfzNulo`, `WolfzNumeroBr`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_percent"></a>

### `parse_percent`: Percentual

Percentual para fração: '12,5%' -> 0.125. Sem o '%', ``bare`` diz o
que o número é: ``fraction`` ('0,125' -> 0.125) ou ``points`` ('12,5' ->
0.125). A escolha vale para a coluna inteira, nunca valor a valor.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `bare` | um de: `"fraction"`, `"points"` | `"fraction"` | Número sem % |

**Exemplo 1**

```json
{"op": "parse_percent", "cols": ["p"]}
```

Antes:

| p |
|---|
| `12,5%` |
| `0,125` |
| `100 %` |
| *nulo* |
| `x` |

Depois:

| p |
|---|
| 0.125 |
| 0.125 |
| 1.0 |
| *nulo* |
| *nulo* |

**Exemplo 2**

```json
{"op": "parse_percent", "cols": ["p"], "bare": "points"}
```

Antes:

| p |
|---|
| `12,5` |
| `3%` |

Depois:

| p |
|---|
| 0.125 |
| 0.03 |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"p", each WolfzPercentual(_, false), type nullable number}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzNulo`, `WolfzNumeroBr`, `WolfzPercentual`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_date_br"></a>

### `parse_date_br`: Data (dd/mm/aaaa)

Data em qualquer formato comum no Brasil: '31/12/2024', '31.12.24',
'2024-12-31', '31 de dezembro de 2024', 8 dígitos ('20241231',
'31122024') e serial do Excel. Data impossível, zerada ou o 'sem data
fim' de ERP (ano 9999) vira nulo. ``eight_digits`` decide como ler 8
dígitos; ``century_pivot`` decide o século de ano com 2 dígitos.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `eight_digits` | um de: `"auto"`, `"ymd"`, `"dmy"` | `"auto"` | Oito dígitos |
| `century_pivot` | inteiro (mín. 0, máx. 99) | `30` | Virada do século (ano com 2 dígitos) |
| `accept_excel_serial` | sim/não | `true` | Aceitar número de série do Excel |

**Exemplo 1**

```json
{"op": "parse_date_br", "cols": ["d"]}
```

Antes:

| d |
|---|
| `31/12/2024` |
| `31.12.24` |
| `2024-12-31T10:00:00` |
| `31 de dezembro de 2024` |
| `20241231` |
| `45657` |
| `31/02/2024` |
| `31.12.9999` |

*… mais 2 linhas.*

Depois:

| d |
|---|
| 2024-12-31 |
| 2024-12-31 |
| 2024-12-31 |
| 2024-12-31 |
| 2024-12-31 |
| 2024-12-31 |
| *nulo* |
| *nulo* |

*… mais 2 linhas.*

**Exemplo 2**

```json
{"op": "parse_date_br", "cols": ["d"], "eight_digits": "dmy", "accept_excel_serial": false}
```

Antes:

| d |
|---|
| `01022024` |
| `45657` |
| `15/03/29` |
| `15/03/30` |

Depois:

| d |
|---|
| 2024-02-01 |
| *nulo* |
| 2029-03-15 |
| 1930-03-15 |

**Exemplo 3**

```json
{"op": "parse_date_br", "cols": ["d"], "eight_digits": "ymd", "century_pivot": 50}
```

Antes:

| d |
|---|
| `20240201` |
| `01022024` |
| `15/03/49` |
| `15/03/50` |

Depois:

| d |
|---|
| 2024-02-01 |
| *nulo* |
| 2049-03-15 |
| 1950-03-15 |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"d", each WolfzDataBr(_, "auto", 30, true), type nullable date}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzDataBr`, `WolfzEspacos`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_datetime_br"></a>

### `parse_datetime_br`: Data e hora (dd/mm/aaaa hh:mm)

Data e hora: '31/01/2026 14:35:22', '31/01/2026 14:35',
'2026-01-31T14:35:22', com milissegundos, serial do Excel com fração.
Lê a data como ``parse_date_br`` (mesmos parâmetros) e mantém a hora;
data sem hora fica com 00:00:00. O fuso no fim ('Z', '-03:00') é
ignorado: fica a hora do relógio, e o arquivo não grava fuso. Hora
impossível ('25:61') vira nulo.

Formato da receita 1.1: uma receita com esta operação não abre no WolfzBR 1.0.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `eight_digits` | um de: `"auto"`, `"ymd"`, `"dmy"` | `"auto"` | Oito dígitos |
| `century_pivot` | inteiro (mín. 0, máx. 99) | `30` | Virada do século (ano com 2 dígitos) |
| `accept_excel_serial` | sim/não | `true` | Aceitar número de série do Excel |

**Exemplo 1**

```json
{"op": "parse_datetime_br", "cols": ["d"]}
```

Antes:

| d |
|---|
| `31/01/2026 14:35:22` |
| `31/01/2026 14:35` |
| `2026-01-31T14:35:22` |
| `2026-01-31 14:35:22.123` |
| `2026-01-31T14:35:22Z` |
| `2026-01-31T14:35:22-03:00` |
| `46053.6079` |
| `31/01/2026` |

*… mais 7 linhas.*

Depois:

| d |
|---|
| 2026-01-31T14:35:22 |
| 2026-01-31T14:35:00 |
| 2026-01-31T14:35:22 |
| 2026-01-31T14:35:22.123000 |
| 2026-01-31T14:35:22 |
| 2026-01-31T14:35:22 |
| 2026-01-31T14:35:22.560000 |
| 2026-01-31T00:00:00 |

*… mais 7 linhas.*

**Exemplo 2**

```json
{"op": "parse_datetime_br", "cols": ["d"], "eight_digits": "ymd", "accept_excel_serial": false}
```

Antes:

| d |
|---|
| `20240201 08:01:02` |
| `01022024 08:01` |
| `46053.6079` |
| `45657` |

Depois:

| d |
|---|
| 2024-02-01T08:01:02 |
| *nulo* |
| *nulo* |
| *nulo* |

**Exemplo 3**

```json
{"op": "parse_datetime_br", "cols": ["d"], "eight_digits": "dmy", "century_pivot": 50}
```

Antes:

| d |
|---|
| `01022024 08:01` |
| `15/03/49 23:59:59` |
| `31.12.9999 10:00` |
| `31 de janeiro de 2026 8:05` |

Depois:

| d |
|---|
| 2024-02-01T08:01:00 |
| 2049-03-15T23:59:59 |
| *nulo* |
| 2026-01-31T08:05:00 |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"d", each WolfzDataHoraBr(_, "auto", 30, true), type nullable datetime}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzDataBr`, `WolfzDataHoraBr`, `WolfzEspacos`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_month_year"></a>

### `parse_month_year`: Mês/ano

Mês/ano para o 1º dia do mês: 'jan/24', 'Janeiro de 2024',
'01/2024', '2024-01', '202401', 'Competência 03/2025'.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `century_pivot` | inteiro (mín. 0, máx. 99) | `30` | Virada do século (ano com 2 dígitos) |

**Exemplo 1**

```json
{"op": "parse_month_year", "cols": ["m"]}
```

Antes:

| m |
|---|
| `jan/24` |
| `Janeiro de 2024` |
| `01/2024` |
| `2024-01` |
| `202401` |
| `Competência 03/2025` |
| `13/2024` |
| *nulo* |

Depois:

| m |
|---|
| 2024-01-01 |
| 2024-01-01 |
| 2024-01-01 |
| 2024-01-01 |
| 2024-01-01 |
| 2025-03-01 |
| *nulo* |
| *nulo* |

**Exemplo 2**

```json
{"op": "parse_month_year", "cols": ["m"], "century_pivot": 50}
```

Antes:

| m |
|---|
| `jan/49` |
| `jan/50` |
| `03/2025` |

Depois:

| m |
|---|
| 2049-01-01 |
| 1950-01-01 |
| 2025-03-01 |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"m", each WolfzMesAno(_, 30), type nullable date}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzMesAno`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_bool_br"></a>

### `parse_bool_br`: Sim/não

'Sim'/'S'/'X'/'1' -> verdadeiro; 'Não'/'N'/'0' -> falso. Com
``empty_is_false``, célula vazia é falso (colunas de "marque com X").

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `empty_is_false` | sim/não | `false` | Vazio vale não |

**Exemplo 1**

```json
{"op": "parse_bool_br", "cols": ["b"]}
```

Antes:

| b |
|---|
| `Sim` |
| `NÃO` |
| `x` |
| `0` |
| `talvez` |
| `""` |

Depois:

| b |
|---|
| verdadeiro |
| falso |
| verdadeiro |
| falso |
| *nulo* |
| *nulo* |

**Exemplo 2**

```json
{"op": "parse_bool_br", "cols": ["b"], "empty_is_false": true}
```

Antes:

| b |
|---|
| `X` |
| `␠␠` |
| `s` |

Depois:

| b |
|---|
| verdadeiro |
| falso |
| verdadeiro |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"b", each WolfzBool(_, false), type nullable logical}})
```

Usa as funções auxiliares `WolfzBool`, `WolfzChave`, `WolfzEspacos`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="clean_cpf"></a>

### `clean_cpf`: Limpar CPF

CPF como texto de 11 dígitos, sem máscara: '123.456.789-09' ->
'12345678909'; '2345678909' -> '02345678909' (zero perdido no Excel).
CPF mascarado do Portal da Transparência ('***.456.789-**') vira
'***456789**'. Com ``pad_zeros=False``, CPF curto vira nulo.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `pad_zeros` | sim/não | `true` | Completar zeros à esquerda |
| `add_valid_col` | sim/não | `false` | Criar coluna de validade |

**Exemplo 1**

```json
{"op": "clean_cpf", "cols": ["cpf"], "add_valid_col": true}
```

Antes:

| cpf |
|---|
| `529.982.247-25` |
| `2345678909` |
| `12345678909.0` |
| `***.456.789-**` |
| `1,23E+10` |
| *nulo* |

Depois:

| cpf | cpf_valido |
|---|---|
| `52998224725` | verdadeiro |
| `02345678909` | falso |
| `12345678909` | verdadeiro |
| `***456789**` | falso |
| *nulo* | *nulo* |
| *nulo* | *nulo* |

**Exemplo 2**

```json
{"op": "clean_cpf", "cols": ["cpf"], "pad_zeros": false}
```

Antes:

| cpf |
|---|
| `2345678909` |
| `52998224725` |

Depois:

| cpf |
|---|
| *nulo* |
| `52998224725` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.AddColumn(Table.TransformColumns(Origem, {{"cpf", each WolfzCpf(_, true), type nullable text}}), "cpf_valido", each if Record.Field(_, "cpf") = null then null else WolfzCpfValido(Record.Field(_, "cpf")), type nullable logical)
```

Usa as funções auxiliares `WolfzChave`, `WolfzCpf`, `WolfzCpfValido`, `WolfzEspacos`, `WolfzNulo`, `WolfzPrepId`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="clean_cnpj"></a>

### `clean_cnpj`: Limpar CNPJ

CNPJ como texto de 14 caracteres, sem máscara, letras em maiúscula:
'12.345.678/0001-95' -> '12345678000195'; '191' -> '00000000000191'.
Aceita o CNPJ alfanumérico (julho de 2026); a coluna de validade confere o dígito
verificador com a regra nova, que vale também para o numérico.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `pad_zeros` | sim/não | `true` | Completar zeros à esquerda |
| `add_valid_col` | sim/não | `false` | Criar coluna de validade |

**Exemplo 1**

```json
{"op": "clean_cnpj", "cols": ["c"], "add_valid_col": true}
```

Antes:

| c |
|---|
| `00.000.000/0001-91` |
| `191` |
| `12.abc.345/01de-35` |
| `11.222.333/0001-80` |
| `abc` |
| *nulo* |

Depois:

| c | c_valido |
|---|---|
| `00000000000191` | verdadeiro |
| `00000000000191` | verdadeiro |
| `12ABC34501DE35` | verdadeiro |
| `11222333000180` | falso |
| *nulo* | *nulo* |
| *nulo* | *nulo* |

**Exemplo 2**

```json
{"op": "clean_cnpj", "cols": ["c"], "pad_zeros": false}
```

Antes:

| c |
|---|
| `191` |
| `00.000.000/0001-91` |
| *nulo* |

Depois:

| c |
|---|
| *nulo* |
| `00000000000191` |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.AddColumn(Table.TransformColumns(Origem, {{"c", each WolfzCnpj(_, true), type nullable text}}), "c_valido", each if Record.Field(_, "c") = null then null else WolfzCnpjValido(Record.Field(_, "c")), type nullable logical)
```

Usa as funções auxiliares `WolfzChave`, `WolfzCnpj`, `WolfzCnpjValido`, `WolfzEspacos`, `WolfzNulo`, `WolfzPrepId`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="clean_cep"></a>

### `clean_cep`: Limpar CEP

CEP como 8 dígitos: '29100-000' -> '29100000'; '1310100' ->
'01310100' (zero perdido no Excel). CEP de 5 dígitos é ambíguo e vira
nulo.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "clean_cep", "cols": ["cep"]}
```

Antes:

| cep |
|---|
| `29100-000` |
| `1310100` |
| `29100` |
| `00000-000` |
| *nulo* |
| `1310100.0` |

Depois:

| cep |
|---|
| `29100000` |
| `01310100` |
| *nulo* |
| *nulo* |
| *nulo* |
| `01310100` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"cep", each WolfzCep(_), type nullable text}})
```

Usa as funções auxiliares `WolfzCep`, `WolfzChave`, `WolfzEspacos`, `WolfzNulo`, `WolfzPrepId`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="normalize_uf"></a>

### `normalize_uf`: Padronizar UF

UF como sigla: 'es', 'Espírito Santo', 'ESPIRITO SANTO' -> 'ES'.
O que não é UF vira nulo.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "normalize_uf", "cols": ["uf"]}
```

Antes:

| uf |
|---|
| `es` |
| `Espírito Santo` |
| `SAO PAULO` |
| `␠rj␠` |
| `XX` |
| *nulo* |

Depois:

| uf |
|---|
| `ES` |
| `ES` |
| `SP` |
| `RJ` |
| *nulo* |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"uf", each WolfzUf(_), type nullable text}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzNulo`, `WolfzSemAcento`, `WolfzUf`, declaradas no início da consulta exportada.

<a id="clean_phone"></a>

### `clean_phone`: Limpar telefone

Telefone no formato E.164: '(27) 99999-9999' -> '+5527999999999'.
Trata +55, zero de longa distância, código de operadora e celular
antigo de 8 dígitos (acrescenta o 9, a não ser com
``add_ninth_digit=False``). Número sem DDD usa ``default_ddd``; sem ele,
vira nulo, como 0800 e DDD que não existe.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `default_ddd` | texto | `null` | DDD para número sem DDD |
| `add_ninth_digit` | sim/não | `true` | Acrescentar o 9 no celular antigo |

**Exemplo 1**

```json
{"op": "clean_phone", "cols": ["tel"]}
```

Antes:

| tel |
|---|
| `(27) 99999-9999` |
| `+55 27 3333-4444` |
| `027 8888-7777` |
| `0 21 27 99999-9999` |
| `0800 123 4567` |
| `99999-9999` |
| *nulo* |

Depois:

| tel |
|---|
| `+5527999999999` |
| `+552733334444` |
| `+5527988887777` |
| `+5527999999999` |
| *nulo* |
| *nulo* |
| *nulo* |

**Exemplo 2**

```json
{"op": "clean_phone", "cols": ["tel"], "default_ddd": "27", "add_ninth_digit": false}
```

Antes:

| tel |
|---|
| `8888-7777` |
| `(11) 8888-7777` |
| `27 1234-5678` |

Depois:

| tel |
|---|
| `+552788887777` |
| `+551188887777` |
| `+552712345678` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"tel", each WolfzTelefone(_, null, true), type nullable text}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzNulo`, `WolfzPrepId`, `WolfzSemAcento`, `WolfzTelefone`, declaradas no início da consulta exportada.

<a id="clean_cpf_cnpj"></a>

### `clean_cpf_cnpj`: Limpar CPF ou CNPJ

Coluna com CPF ou CNPJ ("CPF OU CNPJ DO SANCIONADO" no CEIS): limpa
e completa os zeros no tamanho certo. Com ``person_type_col`` (coluna com
'F'/'J', 'PF'/'PJ', 'Física'/'Jurídica'), o tipo decide; sem ela, o
tamanho e o dígito verificador. Ambíguo vira nulo.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `person_type_col` | coluna | `null` | Coluna do tipo de pessoa (F/J) |

**Exemplo 1**

```json
{"op": "clean_cpf_cnpj", "col": "doc"}
```

Antes:

| doc |
|---|
| `529.982.247-25` |
| `191` |
| `11.222.333/0001-81` |
| `2345678909` |
| `abc` |
| *nulo* |

Depois:

| doc |
|---|
| `52998224725` |
| *nulo* |
| `11222333000181` |
| *nulo* |
| *nulo* |
| *nulo* |

**Exemplo 2**

```json
{"op": "clean_cpf_cnpj", "col": "doc", "person_type_col": "tipo"}
```

Antes:

| doc | tipo |
|---|---|
| `191` | `J` |
| `191` | `F` |
| `52998224725` | `Pessoa Física` |
| *nulo* | `J` |

Depois:

| doc | tipo |
|---|---|
| `00000000000191` | `J` |
| `00000000191` | `F` |
| `52998224725` | `Pessoa Física` |
| *nulo* | `J` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"doc", each WolfzCpfCnpj(_, null), type nullable text}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzCnpj`, `WolfzCnpjValido`, `WolfzCpf`, `WolfzCpfCnpj`, `WolfzCpfValido`, `WolfzEspacos`, `WolfzNulo`, `WolfzPrepId`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="split_municipio_uf"></a>

### `split_municipio_uf`: Separar município e UF

Separa município e UF que vêm no mesmo campo: 'Vitória - ES',
'Vitória/ES', 'Alta Floresta D'Oeste (RO)'. O município fica em ``col``
e a UF vai para a coluna nova ``uf_col``. Só separa se o fim for uma UF
de verdade: 'Embu-Guaçu' continua inteiro (e a UF fica nula).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `uf_col` | coluna | `"uf"` | Coluna da UF |

**Exemplo 1**

```json
{"op": "split_municipio_uf", "col": "m"}
```

Antes:

| m |
|---|
| `Vitória - ES` |
| `Vitória/es` |
| `Alta Floresta D'Oeste (RO)` |
| `Embu-Guaçu` |
| `Serra (XX)` |
| *nulo* |

Depois:

| m | uf |
|---|---|
| `Vitória` | `ES` |
| `Vitória` | `ES` |
| `Alta Floresta D'Oeste` | `RO` |
| `Embu-Guaçu` | *nulo* |
| `Serra (XX)` | *nulo* |
| *nulo* | *nulo* |

**Exemplo 2**

```json
{"op": "split_municipio_uf", "col": "local", "uf_col": "sigla"}
```

Antes:

| local |
|---|
| `Serra – ES` |
| `␠␠Linhares  -  es␠` |

Depois:

| local | sigla |
|---|---|
| `Serra` | `ES` |
| `Linhares` | `ES` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Table.AddColumn(Origem, "uf", each WolfzMunicipioUf(Record.Field(_, "m")){1}, type nullable text), {{"m", each WolfzMunicipioUf(_){0}, type nullable text}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzMunicipioUf`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="parse_ibge_value"></a>

### `parse_ibge_value`: Valor do IBGE (-, .., ..., X)

Valor de tabela do IBGE (SIDRA, Censo, DATASUS) com os sinais
convencionais: '-' é zero absoluto, '0' é zero arredondado, '..' não se
aplica, '...' não disponível, 'X' omitido por sigilo. '-' vira 0; os
outros sinais viram nulo, nunca zero. Com ``add_status_col`` (padrão), cria a
coluna ``<coluna>_situacao`` dizendo qual era o caso de cada célula.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `decimal` | um de: `"."`, `","` | `"."` | Separador decimal |
| `add_status_col` | sim/não | `true` | Criar coluna de situação |

**Exemplo 1**

```json
{"op": "parse_ibge_value", "cols": ["v"]}
```

Antes:

| v |
|---|
| `5556` |
| `-` |
| `..` |
| `...` |
| `X` |
| `0` |
| `1234.5` |
| `abc` |

*… mais 1 linhas.*

Depois:

| v | v_situacao |
|---|---|
| 5556.0 | `valor` |
| 0.0 | `zero_absoluto` |
| *nulo* | `nao_se_aplica` |
| *nulo* | `nao_disponivel` |
| *nulo* | `omitido_sigilo` |
| 0.0 | `zero_arredondado` |
| 1234.5 | `valor` |
| *nulo* | `invalido` |

*… mais 1 linhas.*

**Exemplo 2**

```json
{"op": "parse_ibge_value", "cols": ["v"], "decimal": ",", "add_status_col": false}
```

Antes:

| v |
|---|
| `1.234,5` |
| `x` |
| `0,0` |

Depois:

| v |
|---|
| 1234.5 |
| *nulo* |
| 0.0 |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Table.AddColumn(Origem, "v_situacao", each WolfzIbge(Record.Field(_, "v"), "en-US"){1}, type text), {{"v", each WolfzIbge(_, "en-US"){0}, type nullable number}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzIbge`, `WolfzNulo`, `WolfzNumeroBr`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="scale_by_unit"></a>

### `scale_by_unit`: Escala da unidade (mil, milhões)

Multiplica colunas numéricas pela escala escrita na unidade: 'Mil
Reais' -> x1.000, 'R$ milhões' -> x1.000.000. A unidade é fixa
(``unit``, a do título da tabela) ou vem de outra coluna
(``unit_col``, uma por linha). Use depois de converter o número.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |
| `unit` | texto | `null` | Unidade (ex.: Mil Reais) |
| `unit_col` | coluna | `null` | Coluna com a unidade |

**Exemplo 1**

```json
{"op": "scale_by_unit", "cols": ["v"], "unit": "Mil Reais"}
```

Antes:

| v |
|---|
| 1.5 |
| *nulo* |
| 2.0 |

Depois:

| v |
|---|
| 1500.0 |
| *nulo* |
| 2000.0 |

**Exemplo 2**

```json
{"op": "scale_by_unit", "cols": ["v", "w"], "unit_col": "u"}
```

Antes:

| v | w | u |
|---|---|---|
| 1.0 | `1` | `R$ milhões` |
| 2.0 | `1` | `Toneladas` |
| 3.0 | `1` | `bilhões` |
| 4.0 | *nulo* | *nulo* |

Depois:

| v | w | u |
|---|---|---|
| 1000000.0 | `1000000` | `R$ milhões` |
| 2.0 | `1` | `Toneladas` |
| 3000000000.0 | `1000000000` | `bilhões` |
| 4.0 | *nulo* | *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"v", each _ * 1000, type nullable number}})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEscala`, `WolfzEspacos`, `WolfzNulo`, `WolfzSemAcento`, declaradas no início da consulta exportada.

<a id="fix_mojibake"></a>

### `fix_mojibake`: Consertar acentos (SÃ£o → São)

Conserta acento estragado de texto UTF-8 lido como Latin-1:
'SÃ£o Paulo' -> 'São Paulo'. Desfaz até duas camadas; texto que não
volta inteiro fica como está.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "fix_mojibake", "cols": ["t"]}
```

Antes:

| t |
|---|
| `SÃ£o Paulo` |
| `InformaÃ§Ã£o` |
| `SÃƒÂ£o` |
| `São Paulo` |
| `SÃO PAULO` |
| *nulo* |

Depois:

| t |
|---|
| `São Paulo` |
| `Informação` |
| `São` |
| `São Paulo` |
| `SÃO PAULO` |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"t", each WolfzMojibake(_), type nullable text}})
```

Usa as funções auxiliares `WolfzMojibake`, declaradas no início da consulta exportada.

<a id="strip_footnotes"></a>

### `strip_footnotes`: Tirar marca de nota (*, ¹, (1))

Tira a marca de nota de rodapé do fim do texto: 'Abacaxi*' ->
'Abacaxi', 'Total²' -> 'Total', 'Receita líquida (1)' -> 'Receita
líquida'. Sem isso, a mesma categoria aparece com e sem a marca em anos
diferentes e não agrupa.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cols` | lista de colunas | obrigatório | Colunas |

**Exemplo 1**

```json
{"op": "strip_footnotes", "cols": ["t"]}
```

Antes:

| t |
|---|
| `Abacaxi*` |
| `Abacaxi **` |
| `Total²` |
| `Receita líquida (1)` |
| `Nota (123)` |
| `A* *` |
| `Sem marca␠` |
| *nulo* |

Depois:

| t |
|---|
| `Abacaxi` |
| `Abacaxi` |
| `Total` |
| `Receita líquida` |
| `Nota (123)` |
| `A*` |
| `Sem marca␠` |
| *nulo* |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = Table.TransformColumns(Origem, {{"t", each WolfzNotaRodape(_), type nullable text}})
```

Usa as funções auxiliares `WolfzNotaRodape`, declaradas no início da consulta exportada.

<a id="normalize_municipio"></a>

### `normalize_municipio`: Município do IBGE

Casa o nome do município com a lista oficial do IBGE e cria
``<col>_codigo_ibge``, ``<col>_nome_ibge`` e ``<col>_status``, sem mexer
na coluna original.

Casa o nome exato (sem acento, caixa e pontuação), depois expande
abreviações ('V. Velha', 'Sto.', 'S.') e por fim procura o mais parecido,
só na UF da linha quando há ``uf_col``. Parecido com nota abaixo de
``threshold`` (0 a 100), ou nome que existe em mais de uma UF sem UF
informada, fica com status ``revisar`` e sem código: confira na
interface. O que você aceitar ou corrigir lá vai para ``manual``
("valor" ou "valor|UF" -> código IBGE; nulo marca que não tem
correspondência).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `col` | coluna | obrigatório | Coluna |
| `uf_col` | coluna | `null` | Coluna da UF |
| `threshold` | inteiro (mín. 50, máx. 100) | `90` | Nota mínima do parecido (50 a 100) |
| `manual` | mapa de texto para (texto) | `{}` | Decisões da revisão |

**Exemplo 1**

```json
{"op": "normalize_municipio", "col": "m", "uf_col": "uf"}
```

Antes:

| m | uf |
|---|---|
| `Vitória` | `ES` |
| `V. Velha` | `ES` |
| `Cachoeiro Itapemirim` | `ES` |
| `Xyzzz` | `ES` |
| *nulo* | `ES` |
| `SERRA` | `espírito santo` |
| `Vitória` | `ES` |

Depois:

| m | uf | m_codigo_ibge | m_nome_ibge | m_status |
|---|---|---|---|---|
| `Vitória` | `ES` | `3205309` | `Vitória` | `exato` |
| `V. Velha` | `ES` | `3205200` | `Vila Velha` | `abreviacao` |
| `Cachoeiro Itapemirim` | `ES` | `3201209` | `Cachoeiro de Itapemirim` | `fuzzy` |
| `Xyzzz` | `ES` | *nulo* | *nulo* | `revisar` |
| *nulo* | `ES` | *nulo* | *nulo* | *nulo* |
| `SERRA` | `espírito santo` | `3205002` | `Serra` | `exato` |
| `Vitória` | `ES` | `3205309` | `Vitória` | `exato` |

**Exemplo 2**

```json
{"op": "normalize_municipio", "col": "m", "threshold": 98, "manual": {"Bom Jesus": "2201903", "Cidade X": null}}
```

Antes:

| m |
|---|
| `Bom Jesus` |
| `Vila Velhaa` |
| `Cidade X` |
| `São Paulo` |
| `S. Mateus` |

Depois:

| m | m_codigo_ibge | m_nome_ibge | m_status |
|---|---|---|---|
| `Bom Jesus` | `2201903` | `Bom Jesus` | `manual` |
| `Vila Velhaa` | *nulo* | *nulo* | `revisar` |
| `Cidade X` | *nulo* | *nulo* | `sem_correspondencia` |
| `São Paulo` | `3550308` | `São Paulo` | `exato` |
| `S. Mateus` | `3204906` | `São Mateus` | `abreviacao` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = let
        // De-para exportado pelo WolfzBR (ADR-7): join exato, sem fuzzy no M.
        depara = Table.SelectRows(
            Table.PromoteHeaders(Csv.Document(File.Contents(CaminhoDeparaMunicipios), [Delimiter = ";", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]),
            each [passo] = "s1"
        ),
        ordem = Table.AddIndexColumn(Origem, "__ordem", 0, 1),
        comValor = Table.AddColumn(
            ordem, "__valor", each WolfzLimpo(Record.Field(_, "m")), type nullable text
        ),
        comChave = Table.AddColumn(comValor, "__uf", each let u = WolfzUf(Record.Field(_, "uf")) in if u = null then "" else u, type text),
        juntas = Table.NestedJoin(
            comChave, {"__valor", "__uf"}, depara, {"valor", "uf"}, "__depara", JoinKind.LeftOuter
        ),
        abertas = Table.ExpandTableColumn(
            juntas, "__depara", {"codigo_ibge", "nome_ibge", "status"}, {"m_codigo_ibge", "m_nome_ibge", "m_status"}
        ),
        semVazio = Table.TransformColumns(abertas, {{"m_codigo_ibge", each if _ = "" then null else _, type nullable text}, {"m_nome_ibge", each if _ = "" then null else _, type nullable text}}),
        comStatus = Table.ReplaceValue(
            semVazio, each Record.Field(_, "m_status"), each if [__valor] <> null and Record.Field(_, "m_status") = null then "fora_do_depara" else Record.Field(_, "m_status"), Replacer.ReplaceValue, {"m_status"}
        ),
        ordenadas = Table.Sort(comStatus, {{"__ordem", Order.Ascending}})
    in
        Table.RemoveColumns(ordenadas, {"__ordem", "__valor", "__uf"})
```

Usa as funções auxiliares `WolfzChave`, `WolfzEspacos`, `WolfzLimpo`, `WolfzNulo`, `WolfzSemAcento`, `WolfzUf`, declaradas no início da consulta exportada.

## Verificações

<a id="assert"></a>

### `assert`: Verificar (assert)

Verificação que não muda os dados: a receita para com mensagem se o
arquivo vier diferente do esperado. ``not_null`` (sem célula vazia),
``unique`` (as colunas juntas não se repetem), ``in_range`` (entre
``min`` e ``max``), ``matches`` (casa com a expressão regular
``pattern``; não roda no Power BI, que não tem expressão regular) e
``row_count_min`` (pelo menos ``min_rows`` linhas).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `check` | um de: `"not_null"`, `"unique"`, `"in_range"`, `"matches"`, `"row_count_min"` | obrigatório | Verificação |
| `cols` | lista de colunas | `[]` | Colunas |
| `min` | número ou texto | `null` | Mínimo |
| `max` | número ou texto | `null` | Máximo |
| `pattern` | texto | `null` | Padrão (expressão regular) |
| `min_rows` | inteiro (mín. 1) | `null` | Mínimo de linhas |

**Exemplo 1**

```json
{"op": "assert", "check": "not_null", "cols": ["cpf"]}
```

Antes:

| cpf | nome |
|---|---|
| `1` | `a` |
| `2` | *nulo* |

Depois:

| cpf | nome |
|---|---|
| `1` | `a` |
| `2` | *nulo* |

**Exemplo 2**

```json
{"op": "assert", "check": "unique", "cols": ["uf", "ano"]}
```

Antes:

| uf | ano |
|---|---|
| `ES` | `2024` |
| `ES` | `2025` |
| `RJ` | `2024` |

Depois:

| uf | ano |
|---|---|
| `ES` | `2024` |
| `ES` | `2025` |
| `RJ` | `2024` |

**Exemplo 3**

```json
{"op": "assert", "check": "in_range", "cols": ["v"], "min": 0.0, "max": 100.0}
```

Antes:

| v |
|---|
| 0.0 |
| 50.5 |
| *nulo* |
| 100.0 |

Depois:

| v |
|---|
| 0.0 |
| 50.5 |
| *nulo* |
| 100.0 |

**Exemplo 4**

```json
{"op": "assert", "check": "matches", "cols": ["cep"], "pattern": "\\d{8}"}
```

Antes:

| cep |
|---|
| `29100000` |
| *nulo* |

Depois:

| cep |
|---|
| `29100000` |
| *nulo* |

**Exemplo 5**

```json
{"op": "assert", "check": "row_count_min", "min_rows": 2}
```

Antes:

| a |
|---|
| `x` |
| `y` |
| `z` |

Depois:

| a |
|---|
| `x` |
| `y` |
| `z` |

Em Power Query M (passo do primeiro exemplo):

```m
Passo = let
        falhas = Table.RowCount(Table.SelectRows(Origem, each List.AnyTrue({WolfzVazia(Record.Field(_, "cpf"))}))),
        mensagem = "cpf" & ": " & Text.From(falhas) & " linhas vazias"
    in
        if falhas > 0 then error Error.Record("WolfzBR: verificação reprovada", mensagem, [Passo = "s1", Verificacao = "not_null"])
        else Origem
```

Usa as funções auxiliares `WolfzVazia`, declaradas no início da consulta exportada.

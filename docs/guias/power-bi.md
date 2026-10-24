# Usando o M exportado no Power BI

O WolfzBR exporta a receita para o Power BI de dois jeitos:

- **Projeto PBIP** (`.pbip`): um projeto pronto do Power BI Desktop, com a tabela, os tipos, `R$` nas colunas de reais, as medidas `Total` e uma tabela calendário opcional. É o caminho mais curto para começar um relatório novo.
- **Consulta Power Query M** (`.pq`): o texto da consulta, para colar num relatório ou numa planilha do Excel que já existe.

Nos dois, a consulta lê o **arquivo original** e refaz a limpeza no próprio Power Query. Não é uma cópia da tabela limpa: no mês seguinte, você troca o caminho do arquivo e atualiza.

Requisito: Power BI Desktop atualizado (Windows). Para planilha `.xls`, o Power BI pede o Access Database Engine se ele faltar; `.ods` o Power Query não lê (salve como `.xlsx` antes).

## Antes de exportar: o arquivo de origem

A consulta precisa do caminho completo do arquivo original. Se você abriu o arquivo arrastando para a interface, o navegador não informa onde ele está: na tela de exportação, preencha **Arquivo de origem** com o caminho (por exemplo `C:\Dados\Arrecadação\janeiro.xlsx`). Ele fica guardado no projeto. Sem isso, a consulta sai com um caminho de exemplo, e é preciso trocar o parâmetro no Power BI antes do primeiro refresh.

## Projeto PBIP

1. Na interface, **Exportar** → marque **Power BI (.pbip)** e, se quiser, **Tabela calendário**. Escolha a pasta.
2. Saem, na pasta: `<nome>.pbip`, a pasta `<nome>.SemanticModel/` (o modelo) e a pasta `<nome>.Report/` (o relatório, com uma página vazia). Se a receita usa município do IBGE, sai também `depara_municipios.csv`.
3. Abra o `<nome>.pbip` com duas vezes (ou **Arquivo → Abrir** no Power BI Desktop).
4. **Página Inicial → Atualizar.** A tabela carrega lendo o arquivo original.

O que vem pronto no modelo:

- uma tabela com o nome da receita e os tipos da tabela limpa (data, número inteiro, número decimal, texto, sim/não);
- `R$ #,0.00` nas colunas de reais (`parse_brl`), `%` nas de percentual e datas em `dd/MM/yyyy`;
- a medida `Total <coluna>` para cada coluna numérica que não é código, ano ou documento, e `Contagem de linhas`;
- com a opção marcada, a tabela `Calendário` (nome do mês e mês abreviado em português, trimestre, ano e mês), marcada como tabela de datas e ligada à primeira coluna de data.

Os arquivos do projeto são texto (TMDL e JSON) e podem ir para o Git junto com a receita.

## Consulta M

1. Na interface, **Exportar** → marque **Power Query (M)**. Saem dois arquivos: `<nome>.pq` (a consulta) e `<nome>.CaminhoArquivo.pq` (o parâmetro com o caminho do arquivo).
2. No Power BI Desktop: **Página Inicial → Transformar dados** (no Excel: **Dados → Obter Dados → Iniciar o Editor do Power Query**).
3. **Nova Fonte → Consulta Nula.** Renomeie a consulta para `CaminhoArquivo`, abra o **Editor Avançado** e cole o conteúdo de `<nome>.CaminhoArquivo.pq`. Ela vira um parâmetro (o ícone muda no painel de consultas).
4. **Nova Fonte → Consulta Nula** de novo. Dê o nome da tabela, abra o **Editor Avançado** e cole o conteúdo de `<nome>.pq`.
5. **Fechar e Aplicar.**

Cada passo da receita vira uma etapa com nome em português no painel **Etapas Aplicadas** ("Cabeçalhos promovidos", "Valores do IBGE convertidos"…), e as funções auxiliares do WolfzBR (`WolfzNumeroBr`, `WolfzData`…) ficam no começo da consulta. O último passo fixa os tipos das colunas.

### Município do IBGE

Se a receita tem o passo `normalize_municipio`, a exportação leva também `depara_municipios.csv` e o parâmetro `<nome>.CaminhoDeparaMunicipios.pq`. Crie o parâmetro `CaminhoDeparaMunicipios` do mesmo jeito do passo 3, **antes** de colar a consulta. O casamento por semelhança ("V. Velha" → Vila Velha) roda no WolfzBR, que o M não sabe fazer; o M só liga cada valor ao código pelo de-para.

## Mês seguinte

Com o arquivo novo salvo em algum lugar:

1. **Transformar dados → Editar parâmetros** → `CaminhoArquivo` = o caminho do arquivo novo.
2. **Aplicar alterações** e **Atualizar**.

Se o arquivo novo tem município que não estava no de-para, a linha fica com status `fora_do_depara`: abra o arquivo novo no WolfzBR, revise os municípios e exporte de novo (só o `depara_municipios.csv` muda).

## Quando o refresh dá erro

- **"WolfzBR: verificação reprovada"**: uma verificação (`assert`) da receita não passou no arquivo novo, por exemplo um código repetido ou uma coluna com vazio. Os detalhes do erro dizem qual verificação e por quê. É de propósito: melhor parar do que carregar uma tabela errada.
- **Coluna não encontrada** numa etapa: o arquivo novo mudou (coluna renomeada, aba diferente). Para uma coluna renomeada, corrija o nome direto na etapa que falhou, no Power Query: a consulta é sua para editar. Mudança grande de layout é mais fácil de refazer: importe o arquivo novo na interface, monte a receita e exporte a consulta de novo (veja [Reaplicando a receita todo mês](todo-mes.md#4-quando-o-arquivo-novo-é-diferente)).
- **Aba com outro nome** (`DEZEMBRO_2025` → `JANEIRO_2026`): se a receita tem o padrão do nome da aba (`source.match`), a consulta acha a aba nova sozinha.

## Diferenças conhecidas entre o M e o WolfzBR

- `assert` com `matches` (expressão regular) não roda no Power Query, que não tem expressão regular: fica só como comentário na consulta.
- No CSV, a consulta lê o número de colunas do arquivo exportado; um arquivo novo com colunas a mais perde as excedentes.
- Número com muitas casas decimais pode aparecer com uma diferença na última casa (arredondamento do Power Query).

Fora isso, o M dá a mesma tabela que o WolfzBR: cada operação tem teste de equivalência, o M gerado passa no parser oficial da Microsoft no CI, e cada versão é conferida à mão no Power BI Desktop.

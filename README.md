# WolfzBR

[![CI](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml/badge.svg)](https://github.com/RafaelGomide/WolfzBR/actions/workflows/ci.yml)

Limpeza de planilhas brasileiras com receitas reproduzíveis. Você arrasta a planilha suja (título, cabeçalho no meio, totais, `1.234,56`, `R$`, datas `31/12/2024`), ajusta os passos na tela e exporta a tabela limpa junto com a **receita**: o mesmo passo a passo em Power Query M e em script Python, para refazer no mês seguinte.

Tudo roda na sua máquina. Nenhum dado sai do seu computador.

> **Status:** pré-alfa (0.x). O formato da receita ainda pode mudar até a 1.0.

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
3. Ajuste a receita: adicione, edite, reordene ou desative passos, vendo a tabela antes e depois de cada um. Clique no cabeçalho de uma coluna para ver o perfil dela.
4. Exporte: CSV (pronto para o Excel em português), Excel, Parquet, Power Query M e script Python.

A receita é salva automaticamente a cada edição. O endereço só funciona com a chave de acesso que o terminal mostra, nova a cada execução. Deixe o terminal aberto enquanto usa; Ctrl+C encerra.

Opções: `--port` fixa a porta; `--no-browser` só mostra o endereço, sem abrir o navegador.

### Linha de comando

Aplicar uma receita salva ao arquivo do mês seguinte:

```bash
wolfz run vendas.wolfz.json vendas_fevereiro.xlsx -o saida/ --format xlsx
```

- Se algum passo não se aplicar ao arquivo novo (uma coluna mudou de nome, por exemplo), nada é gravado e a mensagem diz qual passo falhou e quais colunas existem.
- Se a aba muda de nome todo mês (`Vendas 2024` → `Vendas 2025`), use `source.match.sheet_name_regex` na receita.

Outros comandos:

```bash
wolfz inspect planilha.xlsx      # perfil das colunas no terminal
wolfz schema                     # JSON Schema da receita
wolfz --help
```

Códigos de saída do `run`: 0 ok · 1 um passo falhou · 2 receita inválida ou uso incorreto · 3 arquivo ilegível.

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
| Power Query M | A receita como função M, para colar no Power BI ou no Excel. |
| Script Python | A receita como script autônomo, que só depende do Polars. |

Tableau (`.hyper`) e projeto do Power BI (`.pbip`) estão previstos para versões futuras.

## Padrões brasileiros

O catálogo tem 31 operações: estrutura (área, cabeçalho, linhas e colunas vazias, preencher para baixo, despivotar), colunas, texto e padrões brasileiros. Os padrões cobrem:

- números (`1.234,56`, `(1,5)`, `10-` do SAP, `R$`);
- percentual, datas e mês/ano;
- sim/não;
- CPF, CNPJ (inclusive o alfanumérico), CEP e UF.

Cada operação tem a mesma regra no motor (Polars), no M e no script Python, com teste de equivalência.

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

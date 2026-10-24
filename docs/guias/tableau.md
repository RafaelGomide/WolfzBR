# Usando o .hyper no Tableau

O WolfzBR exporta a tabela limpa como extrato do Tableau (`.hyper`), com os tipos certos, e uma fonte de dados (`.tds`) ao lado, com nomes amigáveis e o formato brasileiro já configurado: `R$ 1.234,56`, `12,50%` e `31/01/2024`.

Diferente do M do Power BI, o `.hyper` é a **tabela pronta**, não a receita: ele não se atualiza sozinho com o arquivo do mês seguinte (veja [Mês seguinte](#mês-seguinte)).

## Instalação

O Tableau precisa de um extra, porque a Hyper API da Tableau é um pacote grande e só existe para algumas plataformas:

```bash
pipx install "wolfzbr[tableau]"
```

ou, se o WolfzBR já está instalado com pipx:

```bash
pipx inject wolfzbr tableauhyperapi
```

Funciona no Windows e no Linux x64. No macOS e em ARM a Hyper API não tem pacote: a opção do Tableau aparece desabilitada na exportação, e o `.csv` ou o `.parquet` abrem no Tableau do mesmo jeito (sem o formato brasileiro pronto).

## Exportar

Na interface, **Exportar** → marque **Tableau (.hyper + .tds)** e escolha a pasta. Saem dois arquivos com o nome da receita:

- `<nome>.hyper`: os dados. Data como `DATE`, data e hora como `TIMESTAMP`, inteiro como `BIG_INT`, número como `DOUBLE` e texto como `TEXT`. Coluna de reais (`parse_brl`) vira `NUMERIC(18,2)`, sem erro de arredondamento, quando nenhum valor tem mais de duas casas.
- `<nome>.tds`: a fonte de dados, que aponta para o `.hyper` da mesma pasta.

## Abrir no Tableau

Abra o **`.tds`** (duas vezes no arquivo, ou **Arquivo → Abrir** no Tableau Desktop ou Public). Ele abre o `.hyper` que está ao lado e traz:

- nomes amigáveis: `valor_total` aparece como **Valor total** (o nome de verdade, para fórmulas, continua `valor_total`);
- `R$` com ponto de milhar e vírgula decimal nas colunas de reais;
- percentual nas colunas de `parse_percent`;
- datas em `dd/mm/aaaa`.

Mantenha os dois arquivos juntos: dá para mover a pasta inteira para outro lugar, o `.tds` procura o `.hyper` ao lado dele. Abrir o `.hyper` direto (**Conectar → Mais… → Arquivo de extrato do Tableau**) também funciona, com os tipos certos, mas sem os nomes e formatos do `.tds`.

## Mês seguinte

O `.hyper` sai da interface, a partir de um projeto; o `wolfz run` grava CSV, Excel e Parquet, mas não `.hyper`. Há dois caminhos:

- **Usar um CSV como fonte.** Reaplique a receita pelo terminal, sempre para o mesmo arquivo de saída, e conecte o Tableau a ele uma vez (**Conectar → Arquivo de texto**):

  ```bash
  wolfz run vendas.wolfz.json vendas_fevereiro.xlsx -o dados/vendas.csv --overwrite
  ```

  Nos meses seguintes, rode de novo e use **Dados → Atualizar** no Tableau. O CSV sai com ponto decimal e datas `aaaa-mm-dd`, que o Tableau reconhece como número e data; o formato `R$` e `dd/mm/aaaa` você define uma vez na fonte do Tableau e salva.

- **Exportar o `.hyper` de novo.** Importe o arquivo novo na interface, refaça os passos (as sugestões trazem a maior parte) e exporte o `.hyper` + `.tds` para a **mesma pasta**, confirmando que quer sobrescrever. Como o nome dos arquivos e das colunas é o mesmo, as planilhas e os painéis que você montou continuam funcionando.

## Se um formato não aparecer

Se uma data aparecer como `1/31/2024` ou um valor sem `R$`, defina o formato à mão no Tableau (**Propriedades padrão → Formato do número** ou **da data**) e salve a fonte (**Dados → Adicionar às fontes de dados salvas**). E abra uma issue com a versão do Tableau: o formato vem do `.tds` e deveria ter sido aplicado.

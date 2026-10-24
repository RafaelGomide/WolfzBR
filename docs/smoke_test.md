# Roteiro de smoke test

Conferência à mão de uma versão antes de publicá-la, num computador limpo: uns 15 minutos. Os testes automáticos cobrem o código; este roteiro cobre o que só aparece instalando de verdade, como o pacote do PyPI, o navegador abrindo, o Power BI lendo o arquivo e a mensagem que a pessoa vê.

**Quando:** a cada versão de teste (`rc`) publicada pelo workflow de release, em **Windows e Linux** limpos (sem o repositório nem um WolfzBR instalado antes), e de novo na versão final se algo mudou depois da `rc`.

**Precisa de:** Python 3.12 ou 3.13, [pipx](https://pipx.pypa.io/), um navegador e, no Windows, o Power BI Desktop.

## Arquivos de teste

Três CSV sintéticos (dados inventados), de [`tests/corpus/_fixtures/smoke/`](../tests/corpus/_fixtures/smoke):

| Arquivo | O que é |
|---|---|
| `junho.csv` | Remuneração de servidores, 15 linhas: o arquivo do primeiro mês. |
| `julho.csv` | O mesmo layout no mês seguinte, com 30 linhas. |
| `outro_formato.csv` | Uma planilha com outras colunas (preços de GLP da ANP). |

Baixe os três da tag que está sendo testada (troque `v1.0.0rc1` pela versão), numa pasta de trabalho:

```bash
for f in junho julho outro_formato; do curl -fsSLO "https://raw.githubusercontent.com/RafaelGomide/WolfzBR/v1.0.0rc1/tests/corpus/_fixtures/smoke/$f.csv"; done
```

No PowerShell:

```powershell
foreach ($f in "junho", "julho", "outro_formato") { Invoke-WebRequest "https://raw.githubusercontent.com/RafaelGomide/WolfzBR/v1.0.0rc1/tests/corpus/_fixtures/smoke/$f.csv" -OutFile "$f.csv" }
```

Para o passo 3, baixe também `tests/corpus/receita_municipal/original.xlsx` como `receita_municipal.xlsx`.

## Instalar a versão

Do **PyPI** (versão final ou `rc` já publicada lá):

```bash
pipx install "wolfzbr==1.0.0rc1"
```

Do **TestPyPI**: baixe só o wheel de lá e instale o arquivo, com as dependências vindas do PyPI. Com `--extra-index-url`, o pip pode trazer do TestPyPI um pacote falso com o nome de uma dependência.

```bash
pip download --no-deps --index-url https://test.pypi.org/simple/ "wolfzbr==1.0.0rc1" -d wheel
```
```bash
pipx install wheel/wolfzbr-1.0.0rc1-py3-none-any.whl
```

## Passos

| # | Faça | Tem de acontecer |
|---|---|---|
| 1 | Instale (acima). | Instala sem erro e sem pedir Node nem compilador. |
| 2 | `wolfz --version` | Mostra `wolfz 1.0.0rc1` (a versão testada). |
| 3 | `wolfz inspect receita_municipal.xlsx` | Tabela com o perfil das colunas no terminal, com acentos certos. |
| 4 | `wolfz ui` e, no navegador que abrir: arraste `junho.csv`; clique em **Aceitar todas** até não sobrar sugestão; confira a tabela em **Antes e depois**; **Exportar** com CSV, Power Query (M) e Power BI (.pbip) marcados, informando em **Arquivo de origem** o caminho completo do `julho.csv` e uma pasta de saída vazia. | O navegador abre sozinho. A estrutura aparece em cores. As sugestões entram por etapa (moeda e mês/ano; depois as verificações), sem passo repetido. A exportação termina com "Pronto: 15 linhas" e os arquivos na pasta. |
| 5 | Copie a receita do projeto (`~/.wolfz/projects/<id>/recipe.wolfz.json`; o id está no endereço da interface) para a pasta de trabalho como `servidores.wolfz.json`. Depois: `wolfz run servidores.wolfz.json julho.csv -o julho_limpo.csv` | Sai com código 0 e **30 linhas** (o arquivo inteiro, não as 15 de junho). |
| 6 | `wolfz run servidores.wolfz.json outro_formato.csv -o x.csv` | Sai com código 1, diz o passo e a coluna que falta e lista as colunas que existem. `x.csv` não é criado. |
| 7 | Só no Windows: abra o `.pbip` exportado no passo 4 no Power BI Desktop e clique em **Atualizar**. | Abre sem erro; o refresh lê o `julho.csv` (o arquivo de origem informado); um cartão com `Contagem de linhas` mostra 30; valores em `R$`. |

Ao terminar, `wolfz ui` encerra com Ctrl+C e `pipx uninstall wolfzbr` limpa a máquina.

## Registro

Anote o resultado de cada versão. Uma linha com ❌ não deixa a versão sair: abra uma issue com o passo, o sistema e a mensagem, corrija e publique a próxima `rc`.

| Versão | Data | Sistema | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Quem |
|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | |

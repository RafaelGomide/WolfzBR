# Segurança

## Como reportar uma vulnerabilidade

**Não abra issue pública.** Reporte em particular pelo GitHub:

1. Abra <https://github.com/RafaelGomide/WolfzBR/security/advisories/new> (aba **Security** do repositório → **Report a vulnerability**).
2. Descreva o problema, a versão do WolfzBR (`wolfz --version`), o sistema operacional e os passos para reproduzir.
3. Se houver arquivo de exemplo, use dado inventado: nunca mande planilha com dado real de pessoa ou de cliente.

O relato fica visível só para você e para quem mantém o projeto até a correção sair. O WolfzBR é mantido por uma pessoa: a meta é responder em até 7 dias e, confirmada a falha, publicar a correção em até 30 dias, com crédito para quem reportou, se você quiser.

## Versões com correção

| Versão | Recebe correção de segurança |
|---|---|
| a mais recente | sim |
| anteriores | não: atualize com `pipx upgrade wolfzbr` |

## O que conta como vulnerabilidade

O WolfzBR roda só na sua máquina, e o modelo de ameaça é outro programa na mesma máquina, como uma página web aberta no navegador tentando falar com a API local (§11 do [desenho técnico](docs/system_design.md#11-segurança)). Exemplos do que reportar:

- acessar a API local sem o token da sessão, de outro site ou de outra máquina da rede;
- arquivo de planilha que trava a máquina, esgota a memória ou escreve fora da pasta escolhida;
- receita `.wolfz.json` de terceiros que executa código ao ser aberta, ou consulta M e script Python exportados em que um nome de coluna ou um valor da receita vira código;
- dado de célula (CPF, nome, valor) gravado em log, ou qualquer chamada de rede feita pelo WolfzBR;
- dependência com vulnerabilidade conhecida que afete o WolfzBR.

Fora do escopo: quem já tem acesso à sua conta no computador (lê o workspace em `~/.wolfz/` como lê qualquer outro arquivo seu) e o conteúdo das planilhas que você mesmo importa.

## O que o projeto já faz

- API só em `127.0.0.1`, com token novo a cada `wolfz ui`, validação do `Host` e sem CORS.
- Limite de 100 MB por arquivo e do tamanho descompactado de `.xlsx` e `.ods` (zip bomb).
- Sem telemetria, sem verificação de atualização e sem nada carregado de CDN: nenhum dado sai da máquina.
- Teste para cada risco da tabela do §11.5 do design (`tests/test_api/test_riscos.py`), inclusive um fluxo completo com a rede bloqueada e a procura por dado de célula no log (`tests/test_api/test_privacidade.py`).
- `pip-audit` e `npm audit` no CI, a cada push e toda semana.

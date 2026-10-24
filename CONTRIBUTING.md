# Contribuindo com o WolfzBR

Obrigado pelo interesse. Este guia cobre o ambiente, os testes, como adicionar uma operação ou um arquivo ao corpus, e as convenções de commit e de PR. Ao participar, você concorda com o [código de conduta](CODE_OF_CONDUCT.md).

Para relatar um bug ou pedir uma operação, abra uma issue pelo modelo. Vulnerabilidade de segurança **não** vai em issue: veja o [SECURITY.md](SECURITY.md).

## Ambiente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) e Node.js 24 (para a interface e para validar o M gerado).

```bash
git clone https://github.com/RafaelGomide/WolfzBR.git
cd WolfzBR
uv sync --extra dev                                  # --extra tableau para testar o .hyper
uv run pre-commit install
npm ci --ignore-scripts --prefix tools/m-parser      # parser oficial de Power Query M
```

O `uv sync` cria o `.venv` com as versões travadas no `uv.lock`; `uv run <comando>` roda dentro dele. Para usar o `wolfz` do código-fonte: `uv run wolfz ui`.

## Testes

```bash
uv run pytest                                     # tudo (uns 6 minutos)
uv run pytest tests/test_ops -q --no-cov          # uma pasta
uv run pytest -k parse_brl                        # por nome
```

Antes de abrir um PR, rode o mesmo que o CI:

```bash
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run pytest
```

O que os testes cobrem, e onde mexer quando um quebra:

| Pasta | O quê |
|---|---|
| `tests/test_br/` | Parsers e validadores de valor (`wolfz.br`), com testes de propriedade (Hypothesis). |
| `tests/test_ops/` | Cada operação no motor. |
| `tests/test_export/test_equivalencia.py` | Cada exemplo de cada operação dá o mesmo resultado no Polars e no script Python exportado, e o M passa no parser oficial. |
| `tests/test_corpus/` | O corpus de planilhas sujas: detecção e receitas esperadas de ponta a ponta. |
| `tests/test_recipe/test_receitas_antigas.py` | Receitas gravadas por cada versão publicada continuam abrindo e dando a mesma tabela. |
| `tests/test_api/` | API local, segurança (§11 do design) e privacidade (sem rede, sem dado no log). |
| `tests/test_docs.py` | `docs/operacoes.md` em dia com o catálogo e links da documentação. |

Sem o `tools/m-parser` instalado, os testes que validam o M com o parser oficial são pulados; no CI eles são obrigatórios (`WOLFZ_REQUIRE_M_PARSER=1`).

## Como adicionar uma operação

Toda operação tem **três implementações da mesma regra**, no motor (Polars), no Power Query M e no script Python exportado, e o teste de equivalência confere que as três concordam. Antes de começar, abra uma issue descrevendo o caso real (de preferência com um arquivo público) e o nome proposto: depois da 1.0, nome e parâmetros de operação não mudam sem uma versão major.

1. **A classe.** Em `src/wolfz/ops/<área>.py` (`estrutura`, `colunas`, `linhas`, `texto`, `br`, `verificacao`), uma subclasse de `Op` com `@register_op`:

   ```python
   @register_op
   class RemoveAccents(Op):
       """Tira acentos e cedilha: 'São José' -> 'Sao Jose'. Mantém caixa e
       pontuação."""

       op: Literal["remove_accents"]
       m_label = "Acentos removidos"         # nome da etapa no Power Query
       cols: list[str] = Field(min_length=1)

       examples = (
           {
               "step": {"cols": ["m"]},
               "input": {"m": ["São José do Calçado", None]},
               "expected": {"m": ["Sao Jose do Calcado", None]},
           },
       )

       def to_polars(self, lf: pl.LazyFrame) -> pl.LazyFrame: ...
       def to_m(self, prev: str, name: str) -> str: ...
       def to_python(self) -> str: ...
   ```

   - O nome é `snake_case` em inglês, no padrão dos outros: `parse_*` converte texto em tipo, `clean_*` limpa documento, `normalize_*` casa com uma lista oficial. Parâmetro que é nome de coluna termina em `_col`; opção que acrescenta coluna começa com `add_`; texto que separa ou junta partes é `separator`.
   - A docstring vira a descrição em `docs/operacoes.md` e na interface: português, com exemplo entre aspas.
   - `examples` precisa exercitar **todos** os parâmetros e os casos sujos (vazio, nulo, valor que não converte). O teste de equivalência roda cada exemplo e reprova operação sem exemplo.
   - Regra de valor (um valor bruto → um valor limpo) fica em `wolfz.br` como função pura, e a operação a aplica na coluna. O script exportado embute essas funções (`python_helpers`); o M usa funções auxiliares declaradas uma vez (`m_helpers`).
   - No M e no Python, nome de coluna e texto da receita entram **só** pelas funções de escape (`m_text`, `m_field`, `repr`), nunca colados direto no código (§11.5 do design).
2. **A interface.** Em `frontend/src/textos.ts`, o nome da operação (`ops`) e o rótulo de cada parâmetro novo (`params`). O formulário do passo é montado a partir do JSON Schema.
3. **A documentação.** `uv run python scripts/gerar_operacoes.py` regera `docs/operacoes.md` (o teste falha se você esquecer).
4. **A sugestão** (opcional). Se a operação deve ser proposta sozinha, uma regra em `src/wolfz/core/suggest/regras.py` com `@rule`, com teste em `tests/test_suggest/`.
5. **Conferir no Power BI.** O CI garante que o M é válido, não que o Power Query dá o mesmo resultado. Se a tradução usa uma função M que o projeto ainda não usava, diga no PR: quem mantém confere no Power BI Desktop antes da release.

## Como adicionar um arquivo ao corpus

O corpus (`tests/corpus/`) é o conjunto de planilhas sujas com a resposta certa ao lado, que mede a detecção e impede regressão. A estrutura de cada pasta e os campos do gabarito estão em [`tests/corpus/README.md`](tests/corpus/README.md). Em resumo:

- **Nunca** dado de cliente ou de pessoa real. Arquivo de sistema corporativo (ERP, folha, cadastro) entra como **sintético**, gerado por `scripts/gerar_sinteticos.py`, imitando a estrutura com valores inventados.
- Arquivo **público** (portal de transparência, IBGE, DATASUS) entra por `scripts/corpus_publico.py`, que baixa o original e monta o gabarito com regras escritas à mão, sem passar pelos parsers do WolfzBR (senão o teste compararia o código com ele mesmo).
- Nenhum arquivo acima de 1 MB no Git: recorte as linhas que mostram o problema, ou deixe o original fora do Git com `externo.json`.
- Mexeu em `src/wolfz/core/detect/`? Rode `uv run python scripts/medir_deteccao.py` e cole o resultado no PR.

## Interface (`frontend/`)

A interface compilada vai para `src/wolfz/static/` (fora do Git) e entra no wheel.

```bash
cd frontend
npm ci --ignore-scripts
npm run build          # gera src/wolfz/static/
```

Desenvolvimento com recarga automática: suba a API local numa porta fixa, e o Vite repassa `/api` para ela.

```bash
uv run python scripts/servidor_teste.py --port 8799     # imprime a URL com o token
cd frontend && npm run dev                              # abra http://localhost:5173/#token=<token>
```

Mudou alguma rota ou resposta da API? Regere o cliente TypeScript (o pytest e o CI conferem):

```bash
uv run python scripts/gerar_openapi.py
cd frontend && npm run api
```

Antes de abrir um PR que mexe na interface:

```bash
cd frontend
npm run lint
npm run format:check
npm run build
npx playwright install chromium   # só na primeira vez
npm run e2e
```

Textos da interface ficam só em `frontend/src/textos.ts`. Gerar o pacote (`uv build`) exige a interface compilada antes; para um wheel sem ela, de propósito, `WOLFZ_SEM_INTERFACE=1`.

## Mensagens de commit

O projeto segue [Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/):

```
<tipo>(<escopo opcional>): <descrição no imperativo, em português> [ID da tarefa]
```

| Tipo | Quando usar |
|---|---|
| `feat` | Funcionalidade nova para quem usa o WolfzBR |
| `fix` | Correção de bug |
| `perf` | Mais rápido ou com menos memória, mesmo resultado |
| `docs` | Só documentação |
| `refactor` | Mudança de código que não altera comportamento |
| `test` | Só testes |
| `ci` | Workflows do GitHub Actions |
| `build` | Empacotamento, dependências, `pyproject.toml` |
| `chore` | Manutenção que não se encaixa nos outros |

- O escopo indica a área: `feat(ingest): leitura de .xls`.
- O ID entre colchetes é o da tarefa no planejamento, quando houver.
- Mudança incompatível no formato da receita ou na API pública em Python leva `!` depois do tipo (`feat!: ...`) e uma linha `BREAKING CHANGE:` no corpo explicando a migração.

Exemplos:

```
feat: operações rename, drop_rows_where e parse_brl [F0.F]
fix(br): CNPJ alfanumérico com "E" era tratado como notação científica
docs: guia de uso do M exportado no Power BI [FH.D4]
```

## Pull requests

Uma tarefa = uma issue = um PR. O modelo de PR traz o checklist da definição de pronto: CI verde, testes com pelo menos um caso de dado sujo real, docstring em português no que for público, `CHANGELOG.md` atualizado e, se a mudança alterar uma decisão de design, `docs/system_design.md` atualizado no mesmo PR.

## Publicar uma versão

Para quem mantém o projeto. Depois de criar a tag, guarde as receitas daquela versão para o teste de compatibilidade:

```bash
uv run python scripts/receitas_antigas.py v1.0.0
```

O script roda o código da tag num `git worktree` temporário e grava em `tests/receitas_antigas/<tag>/` as receitas como aquela versão salvava, a tabela que ela produzia e um catálogo com um passo por exemplo de cada operação. O teste falha se uma versão do `CHANGELOG.md` (fora a atual) não tiver a sua pasta. Mudou o formato da receita? Suba `CURRENT_VERSION` e escreva a migração em `src/wolfz/core/recipe/migrate.py`: as receitas guardadas precisam continuar abrindo e dando a mesma tabela.

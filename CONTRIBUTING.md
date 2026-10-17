# Contribuindo com o WolfzBR

> Versão mínima. O guia completo (como propor operações novas, corpus de testes, revisão) entra antes da 1.0.

## Ambiente

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) e, para validar o M gerado, Node.js LTS.

```bash
uv sync --extra dev
uv run pre-commit install
npm ci --ignore-scripts --prefix tools/m-parser
```

Antes de abrir um PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run pytest
```

## Interface (`frontend/`)

Requisitos: Node.js 24. A interface compilada vai para `src/wolfz/static/` (fora do Git) e entra no wheel.

```bash
cd frontend
npm ci --ignore-scripts
npm run build          # gera src/wolfz/static/
```

Desenvolvimento com recarga automática: suba a API local numa porta fixa e o Vite repassa `/api` para ela.

```bash
python scripts/servidor_teste.py --port 8799     # imprime a URL com o token
cd frontend && npm run dev                        # abra http://localhost:5173/#token=<token>
```

Mudou alguma rota ou resposta da API? Regere o cliente TypeScript (o pytest e o CI conferem):

```bash
python scripts/gerar_openapi.py
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

Textos da interface ficam só em `frontend/src/textos.ts`.

Gerar o pacote (`uv build`) exige a interface compilada antes; para um wheel sem ela, de propósito, `WOLFZ_SEM_INTERFACE=1`.

## Mensagens de commit

O projeto segue [Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/):

```
<tipo>: <descrição no imperativo, em português> [ID da tarefa]
```

| Tipo | Quando usar |
|---|---|
| `feat` | Funcionalidade nova para quem usa o WolfzBR |
| `fix` | Correção de bug |
| `docs` | Só documentação |
| `refactor` | Mudança de código que não altera comportamento |
| `test` | Só testes |
| `ci` | Workflows do GitHub Actions |
| `build` | Empacotamento, dependências, `pyproject.toml` |
| `chore` | Manutenção que não se encaixa nos outros |

- O escopo é opcional e indica a área: `feat(ingest): leitura de .xls [F1.A2]`.
- O ID entre colchetes é o da tarefa no planejamento, quando houver.
- Mudança incompatível no formato da receita leva `!` depois do tipo (`feat!: ...`) e uma linha `BREAKING CHANGE:` no corpo explicando a migração.

Exemplos:

```
feat: operações rename, drop_rows_where e parse_brl [F0.F]
fix(br): CNPJ alfanumérico com "E" era tratado como notação científica
docs: decisões pendentes do system design [F0.A]
```

## Pull requests

Uma tarefa = uma issue = um PR. O modelo de PR traz o checklist da definição de pronto: CI verde, testes com pelo menos um caso de dado sujo real, docstring em português no que for público, `CHANGELOG.md` atualizado e, se a mudança alterar uma decisão de design, `docs/system_design.md` atualizado no mesmo PR.

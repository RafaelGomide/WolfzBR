# Changelog

Todas as mudanças relevantes do WolfzBR ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e o projeto usa [Versionamento Semântico](https://semver.org/lang/pt-BR/). Mudança incompatível no formato da receita é versão *major*.

## [Não publicado]

## [0.1.0] - 2026-10-16

Primeira versão: receita, três operações e `wolfz run`. Ainda não publicada no PyPI.

### Adicionado

- Pacote `wolfzbr` (`src/wolfz/`) com parsers e validadores brasileiros: moeda, percentual, datas, CPF, CNPJ (inclusive alfanumérico), CEP, telefone, UF, município e código IBGE.
- Receita `.wolfz.json`: modelo validado, serialização estável (mesmos bytes ao carregar e salvar), mensagens de erro com o passo e o campo, migração de versão e JSON Schema (`wolfz schema`).
- Operações `rename`, `drop_rows_where` e `parse_brl`, cada uma com tradução para Polars, Power Query M e script Python.
- Exportação mínima para Power Query M e para script Python autônomo, com teste de equivalência Polars × Python para todas as operações e validação do M pelo parser oficial da Microsoft.
- Motor que aplica a receita e aponta o passo que falhou (`StepError`, no formato Problem Details).
- `wolfz.run(receita, arquivo)` para uso em notebook.
- CLI `wolfz run RECEITA ARQUIVO -o SAIDA` com saída CSV ou Parquet e códigos de saída documentados.
- CI no GitHub Actions (Linux e Windows, Python 3.12 e 3.13), ruff, pre-commit e import-linter.
- Receita e CSV de exemplo (`exemplo.wolfz.json`, `tests/corpus/minimo.csv`).

### Corrigido

- `clean_cnpj` descartava CNPJ alfanumérico válido que parecia notação científica (ex.: `00.000.000/000E-20`).

[Não publicado]: https://github.com/RafaelGomide/WolfzBR/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RafaelGomide/WolfzBR/releases/tag/v0.1.0

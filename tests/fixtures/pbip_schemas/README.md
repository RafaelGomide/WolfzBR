# JSON Schemas do PBIP

Cópia dos schemas oficiais da Microsoft ([microsoft/json-schemas](https://github.com/microsoft/json-schemas/tree/main/fabric), licença MIT, ver `LICENSE`), nas versões que os templates de `src/wolfz/export/pbip/templates/` declaram em `$schema`.

O teste `tests/test_export/test_pbip.py` valida cada JSON exportado contra o schema que ele declara, sem rede. Ao trocar a versão num template, baixe o schema da versão nova para a mesma estrutura de pastas (`<caminho depois de /fabric/>/schema.json`).

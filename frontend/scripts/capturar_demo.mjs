// Captura os quadros do GIF provisório do README (F1.K4).
//
// Precisa da API local no ar com um workspace vazio e token conhecido:
//   WOLFZ_E2E_TOKEN=demo python scripts/servidor_teste.py --port 8796 --home <pasta vazia>
//   node frontend/scripts/capturar_demo.mjs <pasta dos quadros>
//   python scripts/montar_gif.py <pasta dos quadros> docs/demo.gif
//
// Usa um arquivo do corpus de desenvolvimento, nunca os de validação.

import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const saida = process.argv[2];
if (!saida) throw new Error("uso: node capturar_demo.mjs <pasta dos quadros>");
mkdirSync(saida, { recursive: true });

const porta = process.env.WOLFZ_DEMO_PORT ?? "8796";
const token = process.env.WOLFZ_E2E_TOKEN ?? "demo";
const arquivo = fileURLToPath(
  new URL("../../tests/corpus/receita_municipal/original.xlsx", import.meta.url),
);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 760 } });
let n = 0;
const quadro = async (repetir = 1) => {
  await page.waitForTimeout(400);
  for (let i = 0; i < repetir; i++) {
    n += 1;
    await page.screenshot({ path: join(saida, `${String(n).padStart(3, "0")}.png`) });
  }
};

await page.goto(`http://127.0.0.1:${porta}/#token=${token}`);
await page.getByRole("heading", { name: "Limpe uma planilha" }).waitFor();
await quadro(3);

// Importar: a detecção já propõe área e cabeçalho.
await page.locator('input[type="file"]').setInputFiles({
  name: "receita_municipal.xlsx",
  mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  buffer: readFileSync(arquivo),
});
await page.getByRole("button", { name: "Exportar" }).waitFor();
await quadro(4);

// Antes e depois do cabeçalho.
await page
  .locator('li[data-passo="s2"]')
  .getByRole("button", { name: "Definir o cabeçalho" })
  .click();
await quadro(3);

// Novo passo: número brasileiro nas colunas de valor.
await page.getByRole("button", { name: "+ Adicionar passo" }).click();
await page.getByRole("searchbox").fill("número");
await quadro(2);
await page
  .getByRole("dialog", { name: "Escolha a operação" })
  .getByRole("button", { name: /Número brasileiro/ })
  .click();
const form = page.getByRole("form", { name: "Novo passo" });
await form.getByRole("button", { name: "+ Previsão Atualizada (R$)" }).click();
await form.getByRole("button", { name: "+ Arrecadado (R$)" }).click();
await quadro(2);
await form.getByRole("button", { name: "Aplicar" }).click();
await page.getByRole("status").filter({ hasText: "Salvo" }).waitFor();
await quadro(4);

// Perfil da coluna.
await page.getByRole("button", { name: "+ Adicionar passo" }).waitFor();
await quadro(1);

// Exportar.
await page.getByRole("button", { name: "Exportar" }).click();
const dialogo = page.getByRole("dialog", { name: "Exportar" });
await dialogo.getByLabel("Power Query (M)").check();
await quadro(2);
await dialogo.getByRole("button", { name: "Exportar" }).click();
await dialogo.getByText(/Pronto:/).waitFor();
await quadro(5);

await browser.close();
console.log(`${n} quadros em ${saida}`);

// Captura os quadros do GIF do README (FH.D1): planilha de remuneração de
// servidores → as 6 sugestões aceitas → projeto do Power BI exportado.
//
// Precisa da interface compilada (npm run build) e da API local no ar com
// um workspace vazio e token conhecido:
//   WOLFZ_E2E_TOKEN=demo python scripts/servidor_teste.py --port 8796 --home <pasta vazia>
//   node frontend/scripts/capturar_demo.mjs <pasta dos quadros> <pasta de saída do PBIP>
//   python scripts/montar_gif.py <pasta dos quadros> docs/demo.gif
//
// O fim do roteiro, o .pbip abrindo e atualizando no Power BI Desktop, é
// gravado à mão: salve as capturas de tela na pasta dos quadros como 900.png,
// 901.png… antes de montar o GIF, que junta os quadros em ordem de nome.
//
// Usa um arquivo sintético do corpus (dados inventados), nunca os de validação.
// A pasta de saída aparece na tela: use uma sem o seu nome de usuário
// (no Windows, "C:\Users\Public\Documents\WolfzBR demo"). O arquivo de
// origem é copiado para <pasta de saída>\dados, e é para ele que o .pbip aponta.

import { chromium } from "@playwright/test";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [saida, pastaPbip] = process.argv.slice(2);
if (!saida || !pastaPbip) {
  throw new Error("uso: node capturar_demo.mjs <pasta dos quadros> <pasta de saída do PBIP>");
}
mkdirSync(saida, { recursive: true });
const origem = join(resolve(pastaPbip), "dados", "remuneracao_servidores.csv");

const porta = process.env.WOLFZ_DEMO_PORT ?? "8796";
const token = process.env.WOLFZ_E2E_TOKEN ?? "demo";
const arquivo = fileURLToPath(
  new URL("../../tests/corpus/servidores_remuneracao/original.csv", import.meta.url),
);

mkdirSync(join(resolve(pastaPbip), "dados"), { recursive: true });
copyFileSync(arquivo, origem);

const browser = await chromium.launch();
// Tema escuro: a interface segue o sistema no modo "automático".
const page = await browser.newPage({
  viewport: { width: 1280, height: 760 },
  colorScheme: "dark",
});
let n = 0;
const quadro = async (repetir = 1) => {
  await page.waitForTimeout(400);
  for (let i = 0; i < repetir; i++) {
    n += 1;
    await page.screenshot({ path: join(saida, `${String(n).padStart(3, "0")}.png`) });
  }
};
const salvo = () => page.getByRole("status").filter({ hasText: "Salvo" }).waitFor();

await page.goto(`http://127.0.0.1:${porta}/#token=${token}`);
await page.getByRole("heading", { name: "Limpe uma planilha" }).waitFor();
await quadro(3);

// Importar: a detecção já propõe o cabeçalho, e as sugestões aparecem.
await page.locator('input[type="file"]').setInputFiles({
  name: "remuneracao_servidores.csv",
  mimeType: "text/csv",
  buffer: readFileSync(arquivo),
});
const aceitarTodas = page.getByRole("button", { name: /Aceitar todas/ });
await aceitarTodas.waitFor();
await quadro(5);

// "Aceitar todas" vai por etapa (limpar e converter, mudar a forma,
// verificar): um clique por etapa, até não sobrar sugestão.
for (let etapa = 0; etapa < 4 && (await aceitarTodas.count()) > 0; etapa++) {
  await aceitarTodas.click();
  await salvo();
  await quadro(3);
}

// A receita inteira, antes e depois.
await page.getByRole("tab", { name: "Antes e depois" }).click();
await quadro(4);

// Exportar o projeto do Power BI, com a tabela calendário.
await page.getByRole("button", { name: "Exportar" }).click();
const dialogo = page.getByRole("dialog", { name: "Exportar" });
await dialogo.getByLabel("CSV", { exact: true }).uncheck();
await dialogo.getByLabel("Power BI (projeto .pbip)").check();
await dialogo.getByLabel("Tabela calendário").check();
await dialogo.getByLabel(/Arquivo de origem/).fill(origem);
await dialogo.getByLabel("Pasta de saída").fill(resolve(pastaPbip));
await quadro(3);
await dialogo.getByRole("button", { name: "Exportar" }).click();
await dialogo.getByText(/Pronto:/).waitFor();
await quadro(6);

await browser.close();
console.log(`${n} quadros em ${saida}; projeto do Power BI em ${pastaPbip}`);

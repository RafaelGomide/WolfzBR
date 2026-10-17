import { expect, type Page } from "@playwright/test";
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const CORPUS = fileURLToPath(new URL("../../tests/corpus/", import.meta.url));

/** Cópia do arquivo do corpus com o nome da pasta (``original.xlsx`` ->
 * ``receita_municipal.xlsx``), para o projeto ter um nome reconhecível. */
export function arquivo(pasta: string, nome = "original.xlsx"): string {
  const destino = join(mkdtempSync(join(tmpdir(), "wolfz-e2e-arquivo-")), pasta + extname(nome));
  copyFileSync(`${CORPUS}${pasta}/${nome}`, destino);
  return destino;
}

/** Abre a interface como o ``wolfz ui`` abriria: token no fragmento. */
export async function abrir(page: Page) {
  await page.goto(`/#token=${process.env.WOLFZ_E2E_TOKEN}`);
  await expect(page.getByRole("heading", { name: "Limpe uma planilha" })).toBeVisible();
}

export async function importar(page: Page, caminho: string) {
  await page.locator('input[type="file"]').setInputFiles(caminho);
}

/** Espera o projeto abrir (barra com o botão Exportar). */
export async function esperarProjeto(page: Page, nome: string) {
  await expect(page.getByRole("heading", { level: 1, name: nome })).toBeVisible();
  await expect(page.getByRole("button", { name: "Exportar" })).toBeVisible();
}

export function grade(page: Page, rotulo: string | RegExp) {
  return page.locator(".grade", { has: page.locator(".grade-barra", { hasText: rotulo }) });
}

export function passo(page: Page, id: string) {
  return page.locator(`li[data-passo="${id}"]`);
}

/** Adiciona um passo pelo seletor de operações. */
export async function adicionarPasso(page: Page, busca: string, nome: string) {
  await page.getByRole("button", { name: "+ Adicionar passo" }).click();
  await page.getByRole("searchbox", { name: "Buscar operação…" }).fill(busca);
  await page
    .getByRole("dialog", { name: "Escolha a operação" })
    .getByRole("button", { name: nome })
    .click();
  await expect(page.getByRole("form", { name: "Novo passo" })).toBeVisible();
}

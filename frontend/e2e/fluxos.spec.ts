// Fluxos principais da interface (F1.H15, F0.A14).

import { expect, test } from "@playwright/test";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { abrir, adicionarPasso, arquivo, esperarProjeto, grade, importar, passo } from "./apoio";

test("importar → editar → exportar", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  // Receita inicial vinda da detecção: área e cabeçalho.
  await expect(passo(page, "s1")).toContainText("Recortar a área");
  await expect(passo(page, "s2")).toContainText("Definir o cabeçalho");

  // Editar: novo passo que tira a coluna Código.
  await passo(page, "s2").getByRole("button", { name: "Definir o cabeçalho" }).click();
  await adicionarPasso(page, "drop_cols", "Remover colunas");
  const form = page.getByRole("form", { name: "Novo passo" });
  // "Adicionar todas" põe as 4 colunas de uma vez; "Limpar" desfaz.
  await form.getByRole("button", { name: "Adicionar todas (4)" }).click();
  await expect(form.locator(".ficha")).toHaveCount(4);
  await form.getByRole("button", { name: "Limpar" }).click();
  await expect(form.locator(".ficha")).toHaveCount(0);
  await form.getByRole("button", { name: "+ Código" }).click();
  await form.getByRole("button", { name: "Aplicar" }).click();
  await expect(passo(page, "s3")).toContainText("Código");
  await expect(page.getByRole("status").filter({ hasText: "Salvo" })).toBeVisible();
  await expect(grade(page, "Depois de s3")).toBeVisible();
  await expect(grade(page, "Depois de s3")).toHaveAttribute("data-total", "12");

  // Exportar CSV e Power Query para uma pasta nova.
  const saida = mkdtempSync(join(tmpdir(), "wolfz-e2e-saida-"));
  await page.getByRole("button", { name: "Exportar" }).click();
  const dialogo = page.getByRole("dialog", { name: "Exportar" });
  await dialogo.getByLabel("Power Query (M)").check();
  await dialogo.getByLabel("Excel (.xlsx)").check();
  // Padrão do CSV: ponto e vírgula e vírgula decimal (Excel em português).
  await expect(dialogo.getByLabel("Separador")).toHaveValue(";");
  await expect(dialogo.getByLabel("Vírgula decimal (1234,56)")).toBeChecked();
  await dialogo.getByLabel("Pasta de saída").fill(saida);
  await dialogo.getByRole("button", { name: "Exportar" }).click();
  await expect(dialogo.getByText("Pronto: 12 linhas")).toBeVisible();
  const csv = readFileSync(join(saida, "receita_municipal.csv"), "utf-8");
  expect(csv.split("\n")[0]).not.toContain("Código");
  expect(csv.charCodeAt(0)).toBe(0xfeff); // UTF-8 com BOM
  expect(csv.split("\n")[0]).toContain(";");
  expect(existsSync(join(saida, "receita_municipal.pq"))).toBe(true);
  expect(existsSync(join(saida, "receita_municipal.xlsx"))).toBe(true);

  // Exportar de novo: avisa que os arquivos existem e só sobrescreve se confirmar.
  await dialogo.getByRole("button", { name: "Exportar" }).click();
  await expect(dialogo.getByText("Já existem arquivos com esses nomes:")).toBeVisible();
  await dialogo.getByRole("button", { name: "Sobrescrever" }).click();
  await expect(dialogo.getByText("Pronto: 12 linhas")).toBeVisible();
});

test("erro de passo destaca o passo e mostra as colunas", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  await adicionarPasso(page, "drop_cols", "Remover colunas");
  const form = page.getByRole("form", { name: "Novo passo" });
  await form.getByRole("combobox", { name: "Colunas" }).fill("coluna_fantasma");
  await form.getByRole("button", { name: "Adicionar", exact: true }).click();
  await form.getByRole("button", { name: "Aplicar" }).click();

  const s3 = passo(page, "s3");
  await expect(s3).toHaveClass(/com-erro/);
  await expect(s3.getByRole("alert")).toContainText("O passo s3 falhou");
  await expect(s3.getByRole("alert")).toContainText("coluna_fantasma");
  await expect(s3.getByRole("alert").locator(".ficha")).toContainText([
    "Código",
    "Descrição da Receita",
  ]);

  // Desativar o passo tira o erro sem perder o passo.
  await s3.getByRole("button", { name: "Desativar", exact: true }).click();
  await expect(s3).toHaveClass(/desativado/);
  await expect(s3).not.toHaveClass(/com-erro/);
  await s3.getByRole("button", { name: "Ativar", exact: true }).click();
  await expect(s3).toHaveClass(/com-erro/);

  // Remover resolve.
  page.once("dialog", (d) => d.accept());
  await s3.getByRole("button", { name: "Remover", exact: true }).click();
  await expect(passo(page, "s3")).toHaveCount(0);
});

test("reabrir projeto pela lista e com F5", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("vendas_regiao_mesclada"));
  await esperarProjeto(page, "vendas_regiao_mesclada.xlsx");
  const passos = await page.locator("li[data-passo]").count();

  // F5 reabre o mesmo projeto (o token e o projeto ficam no fragmento).
  await page.reload();
  await esperarProjeto(page, "vendas_regiao_mesclada.xlsx");
  await expect(page.locator("li[data-passo]")).toHaveCount(passos);

  // Voltar e abrir pela lista de recentes.
  await page.getByRole("button", { name: "← Voltar" }).click();
  const item = page.locator(".projeto-item", { hasText: "vendas_regiao_mesclada.xlsx" }).first();
  await expect(item).toBeVisible();
  await item.getByRole("button", { name: "Abrir" }).click();
  await esperarProjeto(page, "vendas_regiao_mesclada.xlsx");
  await expect(page.locator("li[data-passo]")).toHaveCount(passos);
});

test("planilha com várias abas pergunta qual importar", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("licitacoes_ods", "original.ods"));
  const dialogo = page.getByRole("dialog", { name: "Qual aba importar?" });
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByRole("radio")).toHaveCount(2);
  await dialogo.getByLabel("Legenda").check();
  await dialogo.getByRole("button", { name: "Importar esta aba" }).click();
  await esperarProjeto(page, "licitacoes_ods.ods");
  await expect(page.getByText("aba Legenda")).toBeVisible();
});

test("ajustar a área arrastando na visão bruta", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");
  await expect(passo(page, "s1")).toContainText("A4:D16");

  // Geometria padrão do Glide: cabeçalho de 36 px, linha de 34 px,
  // numeração de 32 px (menos de 100 linhas); a coluna A tem 90 px.
  const canvas = grade(page, "Arquivo original").locator("canvas").first();
  const caixa = (await canvas.boundingBox())!;
  const ponto = (col: number, linha: number) => ({
    x: caixa.x + 32 + col * 90 + 45,
    y: caixa.y + 36 + linha * 34 + 17,
  });
  const de = ponto(0, 3); // A4
  const ate = ponto(2, 9); // C10
  await page.mouse.move(de.x, de.y);
  await page.mouse.down();
  await page.mouse.move(ate.x, ate.y, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByText("Seleção: A4:C10")).toBeVisible();

  await page.getByRole("button", { name: "Usar a seleção como área" }).click();
  await expect(passo(page, "s1")).toContainText("A4:C10");
  await page.getByRole("tab", { name: "Antes e depois" }).click();
  await expect(grade(page, "Receita inteira")).toHaveAttribute("data-total", "6");
});

test("lista digitada com vírgulas vira vários valores (Remover linhas, in)", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  await passo(page, "s2").getByRole("button", { name: "Definir o cabeçalho" }).click();
  await adicionarPasso(page, "drop_rows_where", "Remover linhas");
  const form = page.getByRole("form", { name: "Novo passo" });
  await form.getByRole("combobox", { name: "Coluna" }).fill("Código");
  await form.getByRole("combobox", { name: "Condição" }).selectOption("in");
  await form
    .getByRole("combobox", { name: "Valor: Tipo do valor" })
    .selectOption({ label: "lista" });
  // Do jeito que se escreve na mão (com aspas de Python no meio) e sem
  // clicar em "Adicionar": sair do campo já confirma.
  await form.getByRole("textbox", { name: "Valor" }).fill("1.1.1.2.50.0.0, '1.1.1.3.03.1.0'");
  await form.getByRole("button", { name: "Aplicar" }).click();

  await expect(passo(page, "s3")).toContainText("1.1.1.2.50.0.0, 1.1.1.3.03.1.0");
  await expect(grade(page, "Depois de s3")).toHaveAttribute("data-total", "10");
});

test("revisão de municípios: aceitar a sugestão grava na receita", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("_fixtures", "municipios_digitados.csv"));
  await esperarProjeto(page, "fixtures.csv");

  await adicionarPasso(page, "normalize_municipio", "Município do IBGE");
  const form = page.getByRole("form", { name: "Novo passo" });
  await form.getByRole("combobox", { name: "Coluna", exact: true }).fill("municipio");
  await form.getByRole("combobox", { name: "Coluna da UF" }).fill("uf");
  await form.getByRole("button", { name: "Aplicar" }).click();

  const s3 = passo(page, "s3");
  await s3.getByRole("button", { name: "Revisar municípios" }).click();
  const revisao = page.getByRole("region", { name: "Municípios do passo s3" });
  await expect(revisao).toContainText("1 valor precisa de revisão.");
  const item = revisao.locator(".item-municipio", { hasText: "Guarapary" });
  await expect(item).toContainText("2 linhas");
  await item.getByRole("button", { name: /Aceitar Guarapari \(ES\)/ }).click();

  await expect(revisao).toContainText("Nada pendente de revisão.");
  await expect(revisao.locator(".item-municipio", { hasText: "Guarapary" })).toContainText(
    "decidido por você",
  );
  await expect(grade(page, "Depois de s3")).toHaveAttribute("data-total", "6");
});

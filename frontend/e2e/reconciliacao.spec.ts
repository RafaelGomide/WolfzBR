// Contagem de linhas por passo na interface (F1 da 1.1, ux.md §1).

import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { abrir, adicionarPasso, arquivo, esperarProjeto, grade, importar, passo } from "./apoio";

/** CSV com cabeçalho e 80 linhas: 60 vendas e 20 estornos. Tirar os
 * estornos é 25% das linhas (e mais de 10), acima do limite de alerta do
 * servidor. As linhas lidas são 81: o cabeçalho também é linha da grade. */
function vendasComEstornos(): string {
  const linhas = ["Tipo;Valor"];
  for (let i = 1; i <= 80; i++) linhas.push(`${i % 4 === 0 ? "Estorno" : "Venda"};${i}`);
  const destino = join(mkdtempSync(join(tmpdir(), "wolfz-e2e-arquivo-")), "estornos.csv");
  writeFileSync(destino, linhas.join("\n") + "\n", "utf-8");
  return destino;
}

async function removerEstornos(page: Page) {
  await adicionarPasso(page, "drop_rows_where", "Remover linhas");
  const form = page.getByRole("form", { name: "Novo passo" });
  await form.getByRole("combobox", { name: "Coluna" }).fill("Tipo");
  await form.getByRole("combobox", { name: "Condição" }).selectOption("equals");
  await form.getByRole("textbox", { name: "Valor" }).fill("Estorno");
  await form.getByRole("button", { name: "Aplicar" }).click();
}

const chamada = (page: Page) => page.locator(".chamada-alerta");
const faixa = (page: Page) => page.locator(".faixa-contagem");

test("passo que tira muitas linhas: destaque, chamada sem fechar e faixa", async ({ page }) => {
  await abrir(page);
  await importar(page, vendasComEstornos());
  await esperarProjeto(page, "estornos.csv");
  await expect(page.locator(".passos .origem")).toContainText("81 linhas");
  await expect(chamada(page).getByRole("status")).toBeEmpty();

  await removerEstornos(page);
  const novo = page.locator("li[data-passo]", { hasText: "Remover linhas" });
  const id = (await novo.getAttribute("data-passo"))!;

  // Passo em destaque, com o número e o percentual; aviso, não erro.
  await expect(novo).toHaveClass(/alerta/);
  await expect(novo).not.toHaveClass(/com-erro/);
  await expect(novo.locator(".contador")).toHaveText("⚠ −20 linhas (25%)");
  await expect(novo.locator(".contador")).toHaveAttribute(
    "title",
    "Entraram 80 linhas, saíram 60.",
  );
  // Leitor de tela: por extenso, ligado ao nome do passo.
  await expect(novo.getByRole("button", { name: /Remover linhas/ })).toHaveAccessibleDescription(
    /^Atenção: tirou 20 linhas, 25%/,
  );

  // Chamada no topo do painel, sem botão de fechar (D5).
  await expect(chamada(page).getByRole("status")).toHaveText(
    "⚠ Atenção: 1 passo tirou muitas linhas.",
  );
  await expect(chamada(page)).toContainText(`${id} Remover linhas: −20 linhas (25%).`);
  await expect(chamada(page).getByRole("button", { name: "Fechar" })).toHaveCount(0);

  // A faixa do "Antes e depois" mostra a perda total sem abrir o passo.
  await page.getByRole("button", { name: "Arquivo original", exact: true }).click();
  await page.getByRole("tab", { name: "Antes e depois" }).click();
  await expect(faixa(page)).toHaveText("Arquivo original 81 linhas");
  // "Ver o passo" seleciona o passo e leva o foco a ele.
  await chamada(page).getByRole("button", { name: "Ver o passo" }).click();
  await expect(novo.getByRole("button", { name: /Remover linhas/ })).toBeFocused();
  await expect(grade(page, `Depois de ${id}`)).toHaveAttribute("data-total", "60");
  await expect(faixa(page)).toHaveClass(/alerta/);
  await expect(faixa(page)).toContainText(`Antes de ${id} 80 linhas → Depois de ${id} 60 linhas`);

  // Desativar o passo faz o alerta sumir sozinho.
  await novo.getByRole("button", { name: "Desativar", exact: true }).click();
  await expect(novo).not.toHaveClass(/alerta/);
  await expect(novo.locator(".contador")).toHaveCount(0);
  await expect(chamada(page).getByRole("status")).toBeEmpty();
  await novo.getByRole("button", { name: "Ativar", exact: true }).click();
  await expect(chamada(page).getByRole("status")).toContainText("1 passo tirou muitas linhas.");
});

test("faixa da receita inteira com alerta aponta o passo que mais tirou", async ({ page }) => {
  await abrir(page);
  await importar(page, vendasComEstornos());
  await esperarProjeto(page, "estornos.csv");
  await removerEstornos(page);
  const id = (await page
    .locator("li[data-passo]", { hasText: "Remover linhas" })
    .getAttribute("data-passo"))!;

  // Ao reabrir não há passo selecionado: a faixa é a da receita inteira.
  await page.reload();
  await esperarProjeto(page, "estornos.csv");
  await page.getByRole("tab", { name: "Antes e depois" }).click();
  const f = faixa(page);
  await expect(f).toHaveClass(/alerta/);
  await expect(f).toContainText("Atenção: a receita tirou 25% das linhas.");
  await expect(f).toContainText("Arquivo original 81 linhas → Receita inteira 60 linhas · −21");
  await expect(f).toContainText(`A maior parte saiu no passo ${id} Remover linhas.`);
});

test("passo que tira poucas linhas mostra o número sem alerta", async ({ page }) => {
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  await adicionarPasso(page, "drop_rows_where", "Remover linhas");
  const form = page.getByRole("form", { name: "Novo passo" });
  await form.getByRole("combobox", { name: "Coluna" }).fill("Código");
  await form.getByRole("combobox", { name: "Condição" }).selectOption("in");
  await form
    .getByRole("combobox", { name: "Valor: Tipo do valor" })
    .selectOption({ label: "lista" });
  await form.getByRole("textbox", { name: "Valor" }).fill("1.1.1.2.50.0.0, 1.1.1.3.03.1.0");
  await form.getByRole("button", { name: "Aplicar" }).click();

  // 2 de 12 linhas: abaixo do mínimo de 10 linhas, então não alerta. (O s1
  // alerta por conta própria: o rodapé da planilha fica fora da área.)
  const s3 = passo(page, "s3");
  await expect(s3.locator(".contador")).toHaveText("−2 linhas");
  await expect(s3).not.toHaveClass(/alerta/);
  await expect(chamada(page)).toContainText("s1 Recortar a área");
  await expect(chamada(page)).not.toContainText("s3");
  await expect(faixa(page)).toContainText(`Antes de s3 12 linhas → Depois de s3 10 linhas · −2`);
  await expect(faixa(page)).not.toHaveClass(/alerta/);
});

test("contando… enquanto a contagem não chega, sem segurar a grade", async ({ page }) => {
  let soltar: () => void = () => undefined;
  const preso = new Promise<void>((r) => (soltar = r));
  await page.route("**/reconciliation", async (rota) => {
    await preso;
    await rota.continue();
  });
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  await expect(passo(page, "s1").locator(".contador")).toHaveText("contando…");
  await expect(page.locator(".passos .origem")).toContainText("contando…");
  // A grade e a edição continuam usáveis enquanto conta.
  await passo(page, "s2").getByRole("button", { name: "Definir o cabeçalho" }).click();
  await expect(grade(page, "Depois de s2")).toBeVisible();
  await expect(faixa(page)).toContainText("contando…");

  soltar();
  await expect(passo(page, "s1").locator(".contador")).not.toHaveText("contando…");
  await expect(page.locator(".passos .origem")).not.toContainText("contando…");
});

test("contagem que falha avisa e deixa tentar de novo", async ({ page }) => {
  let falhar = true;
  await page.route("**/reconciliation", async (rota) => {
    if (!falhar) return rota.continue();
    await rota.fulfill({
      status: 500,
      contentType: "application/problem+json",
      body: JSON.stringify({ title: "Erro interno", detail: "falha simulada" }),
    });
  });
  await abrir(page);
  await importar(page, arquivo("receita_municipal"));
  await esperarProjeto(page, "receita_municipal.xlsx");

  const origem = page.locator(".passos .origem");
  await expect(origem.getByText("Contagem indisponível")).toHaveAttribute(
    "title",
    "falha simulada",
  );
  await expect(passo(page, "s1").locator(".contador")).toHaveCount(0);

  falhar = false;
  await origem.getByRole("button", { name: "Tentar de novo" }).click();
  await expect(origem).not.toContainText("Contagem indisponível");
  await expect(origem.locator(".contador")).toContainText("linhas");
});

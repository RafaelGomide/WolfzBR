// Juntar abas na interface (F3 da 1.1, ux.md §2) e a op parse_datetime_br
// no formulário (F4).

import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { abrir, adicionarPasso, esperarProjeto, grade, importar, passo } from "./apoio";

const python =
  process.env.WOLFZ_PYTHON ??
  (process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python");

/** Planilha com 30 linhas em JAN, FEV e MAR: FEV tem "vendedor" (caixa
 * diferente) e MAR tem a coluna a mais Desconto. Resumo tem menos colunas;
 * Base é oculta e Config, muito oculta. */
function vendasTrimestre(): string {
  const destino = join(mkdtempSync(join(tmpdir(), "wolfz-e2e-arquivo-")), "trimestre.xlsx");
  const script = `
import sys
from openpyxl import Workbook
wb = Workbook()
wb.remove(wb.active)
for nome, cab in [("JAN", ["Loja", "Vendedor", "Valor"]),
                  ("FEV", ["Loja", "vendedor", "Valor"]),
                  ("MAR", ["Loja", "Vendedor", "Valor", "Desconto"])]:
    ws = wb.create_sheet(nome)
    ws.append(cab)
    for i in range(1, 31):
        ws.append([f"L{i % 3}", f"V{i % 5}", i * 10] + ([i] if len(cab) == 4 else []))
r = wb.create_sheet("Resumo"); r.append(["Mês", "Total"]); r.append(["JAN", 4650])
b = wb.create_sheet("Base"); b.append(["x", "y", "z"]); b.append([1, 2, 3]); b.sheet_state = "hidden"
c = wb.create_sheet("Config"); c.append(["a", "b", "c"]); c.append([1, 2, 3]); c.sheet_state = "veryHidden"
wb.save(sys.argv[1])
`;
  const arquivoScript = join(mkdtempSync(join(tmpdir(), "wolfz-e2e-script-")), "gerar.py");
  writeFileSync(arquivoScript, script, "utf-8");
  execFileSync(python, ["-I", arquivoScript, destino]);
  return destino;
}

/** A receita salva, como a API devolve. */
async function receitaSalva(page: Page): Promise<Record<string, unknown>> {
  const id = new URL(page.url()).hash.match(/projeto=([^&]+)/)?.[1];
  const r = await page.request.get(`/api/projects/${id}`, {
    headers: { Authorization: `Bearer ${process.env.WOLFZ_E2E_TOKEN}` },
  });
  return (await r.json()).recipe;
}

const dialogo = (page: Page) => page.getByRole("dialog", { name: "Qual aba importar?" });
const blocoAbas = (page: Page) => page.locator(".abas-juntas");

async function importarJuntando(page: Page) {
  await abrir(page);
  await importar(page, vendasTrimestre());
  const d = dialogo(page);
  await expect(d).toBeVisible();
  await d.getByRole("radio", { name: "Juntar várias abas numa tabela só" }).check();
  return d;
}

test("importar juntando abas: pré-seleção, ocultas fora e regra conferida", async ({ page }) => {
  const d = await importarJuntando(page);
  const juntar = d.getByRole("list", { name: "Juntar várias abas numa tabela só" });

  // Pré-seleção: as abas com a quantidade de colunas mais comum.
  await expect(juntar.getByRole("checkbox", { name: /JAN/ })).toBeChecked();
  await expect(juntar.getByRole("checkbox", { name: /FEV/ })).toBeChecked();
  await expect(juntar.getByRole("checkbox", { name: /MAR/ })).not.toBeChecked();
  await expect(juntar.getByRole("checkbox", { name: /Resumo/ })).not.toBeChecked();
  // Aba oculta nunca entra (D11).
  await expect(juntar.getByRole("checkbox", { name: /Base/ })).toBeDisabled();
  await expect(juntar.getByRole("checkbox", { name: /Config/ })).toBeDisabled();
  await expect(d).toContainText("2 abas ocultas não foram incluídas: Base, Config.");

  // Menos de 2 abas: não importa.
  await juntar.getByRole("checkbox", { name: /FEV/ }).uncheck();
  await expect(d).toContainText("Marque pelo menos 2 abas.");
  await expect(d.getByRole("button", { name: /^Importar/ })).toBeDisabled();

  await juntar.getByRole("checkbox", { name: /FEV/ }).check();
  await juntar.getByRole("checkbox", { name: /MAR/ }).check();
  // A regra vem do servidor e vale também para este arquivo (D8).
  await expect(d).toContainText("A regra gravada na receita escolhe neste arquivo: JAN, FEV, MAR.");
  await expect(d).toContainText('Uma coluna "aba" diz de qual aba veio cada linha.');
  await d.getByRole("button", { name: "Importar 3 abas" }).click();

  await esperarProjeto(page, "trimestre.xlsx");
  await page.getByRole("tab", { name: "Antes e depois" }).click();
  await expect(grade(page, "Receita inteira")).toHaveAttribute("data-total", "90");

  const receita = await receitaSalva(page);
  expect(receita.wolfz_version).toBe("1.1");
  expect((receita.source as Record<string, unknown>).combine_sheets).toMatchObject({
    origin_col: "aba",
  });

  // Bloco "Abas" no painel, com o aviso persistente das colunas diferentes.
  const bloco = blocoAbas(page);
  await expect(bloco).toContainText("Abas JAN, FEV, MAR (3), juntas · coluna aba");
  await expect(bloco).toContainText("2 abas ocultas não foram incluídas: Base, Config.");
  const aviso = bloco.locator(".aviso-abas");
  await expect(aviso).toContainText("Atenção: As abas não têm as mesmas colunas.");
  await expect(aviso).toContainText(
    'FEV: tem "vendedor", as outras têm "Vendedor". Viraram duas colunas.',
  );
  await expect(aviso).toContainText("MAR: tem a mais Desconto.");
  await expect(aviso).toContainText("Nenhuma coluna foi tirada.");
  await expect(aviso.getByRole("button", { name: "Fechar" })).toHaveCount(0);
});

test("editar as abas juntas no painel e desligar a coluna de origem", async ({ page }) => {
  const d = await importarJuntando(page);
  await d.getByRole("button", { name: "Importar 2 abas" }).click();
  await esperarProjeto(page, "trimestre.xlsx");
  const bloco = blocoAbas(page);
  await expect(bloco).toContainText("Abas JAN, FEV (2), juntas · coluna aba");
  await expect(bloco.locator(".aviso-abas")).not.toContainText("MAR");

  // JAN e FEV viram a lista exata dos nomes, que não vira molde no M: a
  // exportação avisa que a consulta junta todas as abas visíveis.
  const saida = mkdtempSync(join(tmpdir(), "wolfz-e2e-saida-"));
  await page.getByRole("button", { name: "Exportar" }).click();
  const exportar = page.getByRole("dialog", { name: "Exportar" });
  await exportar.getByLabel("Power Query (M)").check();
  await exportar.getByLabel("Pasta de saída").fill(saida);
  await exportar.getByRole("button", { name: "Exportar" }).click();
  await expect(exportar.getByText(/Pronto: 60 linhas/)).toBeVisible();
  await expect(exportar.getByRole("alert").first()).toContainText(
    "O padrão de nome das abas desta receita não vai para o Power Query",
  );
  await exportar.getByRole("button", { name: "Fechar" }).click();

  await bloco.getByRole("button", { name: "Editar" }).click();
  const form = bloco.getByRole("form", { name: "Abas que entram" });
  await form.getByRole("checkbox", { name: /MAR/ }).check();
  await expect(form).toContainText("escolhe neste arquivo: JAN, FEV, MAR.");
  await form.getByLabel("Coluna que diz de qual aba veio cada linha").uncheck();
  await form.getByRole("button", { name: "Salvar" }).click();

  await expect(bloco).toContainText("Abas JAN, FEV, MAR (3), juntas · sem coluna de origem");
  await expect(bloco.locator(".aviso-abas")).toContainText("MAR: tem a mais Desconto.");
  const receita = await receitaSalva(page);
  expect((receita.source as Record<string, unknown>).combine_sheets).toMatchObject({
    origin_col: null,
  });
  await page.getByRole("tab", { name: "Antes e depois" }).click();
  await expect(grade(page, "Receita inteira")).toHaveAttribute("data-total", "90");
});

test("op Data e hora no formulário", async ({ page }) => {
  const csv = join(mkdtempSync(join(tmpdir(), "wolfz-e2e-arquivo-")), "chamados.csv");
  writeFileSync(
    csv,
    "Chamado;Abertura\n1;31/01/2026 14:35:22\n2;01/02/2026 08:00\n3;02/02/2026\n",
    "utf-8",
  );
  await abrir(page);
  await importar(page, csv);
  await esperarProjeto(page, "chamados.csv");

  await adicionarPasso(page, "parse_datetime_br", "Data e hora (dd/mm/aaaa hh:mm)");
  const form = page.getByRole("form", { name: "Novo passo" });
  await expect(form.getByLabel("Aceitar número de série do Excel")).toBeVisible();
  await form.getByRole("button", { name: "+ Abertura" }).click();
  await form.getByRole("button", { name: "Aplicar" }).click();

  const novo = page.locator("li[data-passo]", { hasText: "Data e hora" });
  await expect(novo).not.toHaveClass(/com-erro/);
  const id = (await novo.getAttribute("data-passo"))!;
  await expect(grade(page, `Depois de ${id}`)).toHaveAttribute("data-total", "3");
  await expect(passo(page, id)).toContainText("Abertura");
});

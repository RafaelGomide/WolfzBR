// Texto digitado ou colado num campo de lista -> itens.
//
// "NORTE, NORDESTE, SUL" vira três itens: vírgula, ponto e vírgula e quebra
// de linha separam. Colchetes e aspas em volta ("['NORTE', 'SUL']", como
// numa lista do Python) são ignorados. O nome exato de uma coluna conhecida
// fica inteiro, mesmo com vírgula ("PRECIPITAÇÃO TOTAL, HORÁRIO (mm)").

const ASPAS = /^(["'`])(.*)\1$/s;

function semAspas(t: string): string {
  const m = ASPAS.exec(t);
  return m ? m[2] : t;
}

export function separarItens(texto: string, conhecidos: readonly string[] = []): string[] {
  const t = texto.trim();
  if (!t) return [];
  if (conhecidos.includes(t)) return [t];
  const sem = t.replace(/^[[(]\s*/, "").replace(/\s*[\])]$/, "");
  const itens = sem
    .split(/[\n;,]/)
    .map((p) => semAspas(p.trim()).trim())
    .filter((p) => p !== "");
  return [...new Set(itens)];
}

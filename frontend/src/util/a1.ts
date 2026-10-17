// Notação A1 do Excel. Linhas e colunas 0-based na grade (linha 0 = linha 1
// do Excel), como o raw.parquet do projeto.

export function letra(col: number): string {
  let s = "";
  let n = col + 1;
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

export function indiceDaLetra(letras: string): number {
  let n = 0;
  for (const c of letras.toUpperCase()) n = n * 26 + (c.charCodeAt(0) - 64);
  return n - 1;
}

export function paraA1(linha: number, col: number): string {
  return `${letra(col)}${linha + 1}`;
}

/** ``"B12"`` -> ``{linha: 11, col: 1}``; ``null`` se não for A1. */
export function deA1(a1: unknown): { linha: number; col: number } | null {
  if (typeof a1 !== "string") return null;
  const m = /^\s*([A-Za-z]{1,3})(\d{1,7})\s*$/.exec(a1);
  if (!m) return null;
  return { linha: Number(m[2]) - 1, col: indiceDaLetra(m[1]) };
}

import type { Passo, Receita } from "../api/cliente";
import { T } from "../textos";

export const ativo = (p: Passo) => p.enabled !== false;

/** Próximo id livre: s1, s2, … (o maior + 1, nunca reaproveita). */
export function novoId(receita: Receita): string {
  const nums = receita.steps.map((p) => Number(p.id.slice(1))).filter(Number.isFinite);
  return `s${Math.max(0, ...nums) + 1}`;
}

/** Os passos com ids novos e seguidos, depois do maior id da receita. */
export function numerar(receita: Receita, passos: Record<string, unknown>[]): Passo[] {
  const inicio = Number(novoId(receita).slice(1));
  return passos.map((p, i) => ({ ...p, id: `s${inicio + i}` }) as Passo);
}

/** Passo cujo resultado é a tabela "antes" de ``id``: o último passo ativo
 * anterior a ele, ou ``"raw"`` se não houver. */
export function passoAnterior(receita: Receita, id: string): string {
  const i = receita.steps.findIndex((p) => p.id === id);
  for (let j = i - 1; j >= 0; j--) if (ativo(receita.steps[j])) return receita.steps[j].id;
  return "raw";
}

export function nomeOp(op: string): string {
  return T.ops[op] ?? op;
}

/** Resumo de uma linha dos parâmetros do passo, para a lista da receita.
 * Opção desligada (``false``) e valor vazio ficam de fora. */
export function resumo(passo: Passo): string {
  if (passo.op === "select_range")
    return `${String(passo.start)}:${passo.end ? String(passo.end) : "…"}`;
  const partes: string[] = [];
  for (const [k, v] of Object.entries(passo)) {
    if (k === "id" || k === "op" || k === "enabled" || v == null || v === false) continue;
    if (typeof v === "string" && !v.trim()) continue;
    let texto: string;
    if (v === true) texto = T.params[k] ?? k;
    else if (Array.isArray(v)) texto = v.join(", ");
    else if (typeof v === "object")
      texto = Object.entries(v as Record<string, unknown>)
        .map(([a, b]) => `${a} → ${String(b)}`)
        .join(", ");
    else texto = String(v);
    partes.push(texto);
  }
  const s = partes.join(" · ");
  return s.length > 80 ? s.slice(0, 79) + "…" : s;
}

export function mover<X>(lista: X[], de: number, para: number): X[] {
  const nova = [...lista];
  const [item] = nova.splice(de, 1);
  nova.splice(para, 0, item);
  return nova;
}

// Leitura do JSON Schema das operações (GET /ops) para os formulários.

import type { Operacao, Passo } from "../api/cliente";

export type Schema = {
  type?: string;
  enum?: unknown[];
  const?: unknown;
  anyOf?: Schema[];
  items?: Schema;
  additionalProperties?: Schema | boolean;
  $ref?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
};
export type Defs = Record<string, Schema>;

export const FIXOS = new Set(["id", "op", "enabled"]);

export function resolver(s: Schema, defs: Defs): Schema {
  return s.$ref ? (defs[s.$ref.split("/").pop()!] ?? {}) : s;
}

export function tipoDoValor(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

export function tipoDoSchema(s: Schema): string {
  if (s.enum || s.const !== undefined) return "string";
  return s.type ?? "string";
}

export function padrao(s: Schema, defs: Defs): unknown {
  s = resolver(s, defs);
  if (s.default !== undefined) return s.default;
  if (s.anyOf) {
    const alt = s.anyOf.find((a) => resolver(a, defs).type !== "null");
    return s.anyOf.some((a) => a.type === "null") ? null : alt ? padrao(alt, defs) : null;
  }
  if (s.enum) return s.enum[0];
  if (s.const !== undefined) return s.const;
  switch (s.type) {
    case "array":
      return [];
    case "object":
      return {};
    case "boolean":
      return false;
    case "integer":
    case "number":
      return 0;
    default:
      return "";
  }
}

/** Parâmetros iniciais de um passo novo, a partir dos padrões do schema. */
export function passoNovo(op: Operacao, id: string): Passo {
  const schema = op.schema as { properties?: Record<string, Schema>; $defs?: Defs };
  const passo: Passo = { id, op: op.op };
  for (const [k, s] of Object.entries(schema.properties ?? {}))
    if (!FIXOS.has(k)) {
      const v = padrao(s, schema.$defs ?? {});
      if (v !== null) passo[k] = v;
    }
  return passo;
}

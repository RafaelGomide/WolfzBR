import createClient, { type Middleware } from "openapi-fetch";
import { T } from "../textos";
import type { components, paths } from "./schema";
import { obterToken } from "./token";

export type Projeto = components["schemas"]["Projeto"];
export type ProjetoCriado = components["schemas"]["ProjetoCriado"];
export type ProjetoResumo = components["schemas"]["ProjetoResumo"];
export type Aba = components["schemas"]["Aba"];
export type Deteccao = components["schemas"]["Deteccao"];
export type Estrutura = components["schemas"]["Estrutura"];
export type Pagina = components["schemas"]["Pagina"];
export type Perfil = components["schemas"]["Perfil"];
export type PerfilColuna = components["schemas"]["PerfilColuna"];
export type Operacao = components["schemas"]["Operacao"];
export type Exportacao = components["schemas"]["Exportacao"];
export type Reconciliacao = components["schemas"]["Reconciliacao"];
export type ContagemPasso = components["schemas"]["ContagemPasso"];
export type ColunaForaDaArea = components["schemas"]["ColunaForaDaArea"];

// A receita é validada no servidor (JSON Schema da receita); aqui só o que a
// interface usa.
export interface Passo {
  id: string;
  op: string;
  enabled?: boolean;
  [param: string]: unknown;
}
export interface Receita {
  wolfz_version: string;
  name: string;
  created_at: string;
  source: Record<string, unknown>;
  steps: Passo[];
  [campo: string]: unknown;
}

/** Erro da API no formato Problem Details (RFC 9457), com os campos extras
 * que a API manda (``step_id``, ``available_columns``, ``existing``…). */
export class ErroApi extends Error {
  status: number;
  title: string;
  detail: string;
  step_id?: string;
  available_columns?: string[];
  existing?: string[];
  errors?: string[];
  code?: string;
  etag?: string;

  constructor(status: number, corpo: Record<string, unknown>) {
    const detail = String(corpo.detail ?? corpo.title ?? T.comum.semConexao);
    super(detail);
    this.status = status;
    this.title = String(corpo.title ?? "");
    this.detail = detail;
    Object.assign(this, corpo);
  }

  get passoComErro(): boolean {
    return this.status === 422 && typeof this.step_id === "string";
  }
}

const autenticar: Middleware = {
  onRequest({ request }) {
    const token = obterToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: window.location.origin });
api.use(autenticar);

let aoPerderToken: (() => void) | null = null;
export function quandoTokenInvalido(fn: () => void) {
  aoPerderToken = fn;
}

/** Desembrulha a resposta do openapi-fetch: devolve os dados ou lança
 * ``ErroApi``. Falha de rede vira ``ErroApi`` com status 0. */
export async function chamar<D>(
  pedido: Promise<{ data?: D; error?: unknown; response: Response }>,
): Promise<D> {
  let r: { data?: D; error?: unknown; response: Response };
  try {
    r = await pedido;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ErroApi(0, { detail: T.comum.semConexao });
  }
  if (r.response.ok) return r.data as D;
  const corpo =
    r.error && typeof r.error === "object"
      ? (r.error as Record<string, unknown>)
      : { detail: String(r.error ?? r.response.statusText) };
  if (r.response.status === 401) aoPerderToken?.();
  throw new ErroApi(r.response.status, corpo);
}

export function abortado(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

/** Corpo multipart para os uploads. */
export function formulario(campos: Record<string, Blob | string | undefined>): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(campos)) if (v !== undefined) f.append(k, v);
  return f;
}

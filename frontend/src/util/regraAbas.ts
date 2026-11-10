// Regra de abas a partir das abas marcadas (F3, D8). Quem monta a regra é o
// servidor (POST /sheets/combine-rule); aqui só se pede e se mostra o que
// ela escolhe neste arquivo, que é o mesmo que o ``run`` vai ler.

import { api, chamar, type RegraAbas } from "../api/cliente";
import { useCarregar } from "./useCarregar";

export function useRegraAbas(
  marcadas: string[],
  disponiveis: string[],
  abaReceita: string | null,
): { regra?: RegraAbas; erro: unknown; carregando: boolean } {
  const ativa = marcadas.length >= 2;
  const { dados, erro, carregando } = useCarregar(
    (signal) =>
      ativa
        ? chamar(
            api.POST("/api/sheets/combine-rule", {
              body: { sheets: marcadas, available: disponiveis, recipe_sheet: abaReceita },
              signal,
            }),
          )
        : Promise.resolve(undefined),
    [marcadas, disponiveis, abaReceita, ativa],
  );
  return { regra: ativa ? dados : undefined, erro, carregando: ativa && carregando };
}

/** Pré-seleção do diálogo (ux.md §2.1): as abas visíveis com a quantidade de
 * colunas mais comum. Uma aba de totais costuma ter menos colunas. */
export function preSelecao(abas: { name: string; columns?: number | null }[]): string[] {
  const conta = new Map<number | null | undefined, number>();
  for (const a of abas) conta.set(a.columns, (conta.get(a.columns) ?? 0) + 1);
  const comum = [...conta.entries()].sort((x, y) => y[1] - x[1])[0]?.[0];
  return abas.filter((a) => a.columns === comum).map((a) => a.name);
}

/** Nome da coluna de origem quando a receita não diz outro (D6). */
export const ORIGEM_PADRAO = "aba";

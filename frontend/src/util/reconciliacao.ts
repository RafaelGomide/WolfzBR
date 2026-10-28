// Texto da contagem de linhas de cada passo (F1, ux.md §1.1). Só traduz o
// que o GET /reconciliation manda em texto: quem decide se alerta é o
// servidor (``alerta``), nunca a interface.

import type { ContagemPasso, Reconciliacao } from "../api/cliente";
import { T } from "../textos";

const R = T.reconciliacao;

export interface Leitura {
  /** O que aparece na linha do passo (sem o ⚠). */
  visivel: string;
  /** O mesmo, por extenso, para o leitor de tela. */
  fala: string;
  /** Dica ao passar o mouse. */
  dica: string;
  alerta: boolean;
}

export function pct(parte: number, todo: number): string {
  const p = todo > 0 ? (100 * parte) / todo : 0;
  return `${p.toLocaleString("pt-BR", { maximumFractionDigits: p < 10 ? 1 : 0 })}%`;
}

/** Linhas de dado que o passo tirou: sem vazias e sem título/cabeçalho. */
export function perda(c: ContagemPasso): number {
  return Math.max(0, c.entrada - c.saida - c.vazias_removidas - c.estrutura_removidas);
}

/** ``null`` quando o passo não mudou o número de linhas (não mostra nada). */
export function lerPasso(c: ContagemPasso): Leitura | null {
  const dica =
    c.vazias_removidas > 0
      ? R.dicaVazias(c.entrada, c.saida, c.vazias_removidas)
      : R.dica(c.entrada, c.saida);
  let visivel: string;
  let fala: string;
  const tirou = perda(c);
  if (c.fator != null) {
    visivel = R.fator(c.fator, c.saida);
    fala = R.falaFator(c.fator, c.saida);
  } else if (c.saida > c.entrada) {
    visivel = R.acrescentou(c.saida - c.entrada);
    fala = R.falaAcrescentou(c.saida - c.entrada);
  } else if (tirou > 0) {
    const p = pct(tirou, c.entrada);
    visivel = c.alerta ? R.tirouPct(tirou, p) : R.tirou(tirou);
    fala = c.alerta ? `${R.falaTirou(tirou)}, ${p}` : R.falaTirou(tirou);
  } else if (c.vazias_removidas > 0) {
    visivel = R.vazias(c.vazias_removidas);
    fala = R.falaVazias(c.vazias_removidas);
  } else if (c.alerta) {
    // select_range que só deixou colunas de fora: as linhas não mudaram.
    visivel = R.foraDaArea;
    fala = R.falaForaDaArea;
  } else return null;
  return { visivel, fala: c.alerta ? `${R.atencao} ${fala}` : fala, dica, alerta: c.alerta };
}

/** Estado da contagem da versão atual da receita. */
export type Contagem =
  | { tipo: "contando"; anterior?: Reconciliacao }
  | { tipo: "pronta"; dados: Reconciliacao }
  | { tipo: "erro"; erro: unknown; anterior?: Reconciliacao };

/** Linhas lidas conhecidas (a da contagem anterior serve enquanto conta:
 * elas não dependem da receita). */
export function lidas(c: Contagem): number | undefined {
  return c.tipo === "pronta" ? c.dados.linhas_lidas : c.anterior?.linhas_lidas;
}

/** Id do texto por extenso do contador (aria-describedby do nome do passo). */
export const idFala = (passo: string) => `contagem-${passo}`;

/** Leva o foco ao nome do passo, depois de selecionado (ux.md §4, item 6). */
export function focarPasso(id: string) {
  requestAnimationFrame(() => {
    const botao = document.querySelector<HTMLButtonElement>(`li[data-passo="${id}"] .passo-nome`);
    botao?.scrollIntoView({ block: "nearest" });
    botao?.focus();
  });
}

// Tema claro ou escuro. Por padrão segue o sistema (prefers-color-scheme);
// a escolha do botão da barra fica no localStorage. O script no index.html
// aplica o tema antes do React montar (sem piscar o claro) e precisa usar a
// mesma chave e o mesmo atributo daqui.

import { useSyncExternalStore } from "react";

export type Preferencia = "auto" | "claro" | "escuro";
export type Tema = "claro" | "escuro";

const CHAVE = "wolfz.tema";
const EVENTO = "wolfz-tema";
const ESCURO = "(prefers-color-scheme: dark)";

export const ORDEM: Preferencia[] = ["auto", "claro", "escuro"];

export function lerPreferencia(): Preferencia {
  try {
    const p = window.localStorage.getItem(CHAVE);
    if (p === "claro" || p === "escuro") return p;
  } catch {
    // localStorage bloqueado: segue o sistema
  }
  return "auto";
}

function doSistema(): Tema {
  return window.matchMedia?.(ESCURO).matches ? "escuro" : "claro";
}

function resolver(p: Preferencia): Tema {
  return p === "auto" ? doSistema() : p;
}

function aplicar() {
  document.documentElement.dataset.tema = resolver(lerPreferencia());
}

export function definirPreferencia(p: Preferencia) {
  try {
    if (p === "auto") window.localStorage.removeItem(CHAVE);
    else window.localStorage.setItem(CHAVE, p);
  } catch {
    // sem localStorage a escolha vale só até recarregar
  }
  aplicar();
  window.dispatchEvent(new Event(EVENTO));
}

function assinar(aviso: () => void) {
  const consulta = window.matchMedia?.(ESCURO);
  const mudouSistema = () => {
    aplicar();
    aviso();
  };
  window.addEventListener(EVENTO, aviso);
  window.addEventListener("storage", mudouSistema); // outra aba trocou
  consulta?.addEventListener("change", mudouSistema);
  return () => {
    window.removeEventListener(EVENTO, aviso);
    window.removeEventListener("storage", mudouSistema);
    consulta?.removeEventListener("change", mudouSistema);
  };
}

export function usePreferencia(): Preferencia {
  return useSyncExternalStore(assinar, lerPreferencia);
}

export function useTema(): Tema {
  return useSyncExternalStore(assinar, () => resolver(lerPreferencia()));
}

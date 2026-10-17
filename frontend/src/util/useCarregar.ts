import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { abortado } from "../api/cliente";

export interface Carga<D> {
  dados?: D;
  erro: unknown;
  carregando: boolean;
  recarregar: () => void;
}

/** Roda ``buscar`` quando as dependências mudam, cancelando o pedido
 * anterior (só o último importa). Os dados da carga anterior continuam
 * visíveis enquanto a nova não chega. */
export function useCarregar<D>(
  buscar: (signal: AbortSignal) => Promise<D>,
  deps: unknown[],
): Carga<D> {
  const [rodada, setRodada] = useState(0);
  const chave = JSON.stringify([...deps, rodada]);
  const [estado, setEstado] = useState<{ chave?: string; dados?: D; erro: unknown }>({
    erro: null,
  });
  const buscarRef = useRef(buscar);
  useLayoutEffect(() => {
    buscarRef.current = buscar;
  });

  useEffect(() => {
    const ctrl = new AbortController();
    buscarRef.current(ctrl.signal).then(
      (dados) => setEstado({ chave, dados, erro: null }),
      (erro) => {
        if (!abortado(erro)) setEstado((e) => ({ chave, dados: e.dados, erro }));
      },
    );
    return () => ctrl.abort();
  }, [chave]);

  const recarregar = useCallback(() => setRodada((r) => r + 1), []);
  const atual = estado.chave === chave;
  return {
    dados: estado.dados,
    erro: atual ? estado.erro : null,
    carregando: !atual,
    recarregar,
  };
}

// Botão da barra que troca o tema: automático → claro → escuro.

import { T } from "../textos";
import { definirPreferencia, ORDEM, usePreferencia } from "../util/tema";

export function SeletorTema() {
  const atual = usePreferencia();
  const proximo = ORDEM[(ORDEM.indexOf(atual) + 1) % ORDEM.length];
  const dica = T.tema.dica(T.tema.nomes[atual], T.tema.nomes[proximo]);
  return (
    <button
      type="button"
      className="seletor-tema"
      data-tema={atual}
      title={dica}
      aria-label={dica}
      onClick={() => definirPreferencia(proximo)}
    >
      {T.tema.botao(T.tema.nomes[atual])}
    </button>
  );
}

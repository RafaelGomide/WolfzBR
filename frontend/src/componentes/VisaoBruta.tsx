// Visão bruta da planilha (F1.H5) com a estrutura em cores: título,
// cabeçalho, dados, totais e rodapé. A área vem do passo select_range da
// receita; os totais, da detecção. Clicar e arrastar marca uma área nova,
// que vira o select_range (F1.H6).

import { CompactSelection, type GridSelection, type Theme } from "@glideapps/glide-data-grid";
import { useCallback, useMemo, useState } from "react";
import type { Deteccao, Receita } from "../api/cliente";
import { T } from "../textos";
import { deA1, indiceDaLetra, paraA1 } from "../util/a1";
import { ativo } from "../util/receita";
import { GradeDados } from "./GradeDados";

const CORES = {
  titulo: { bgCell: "#eceff3", textDark: "#5b6472" },
  cabecalho: { bgCell: "#d6e6ff", textDark: "#0b3d91" },
  totais: { bgCell: "#ffefc2", textDark: "#7a4a00" },
  rodape: { bgCell: "#efe3ff", textDark: "#55308f" },
  fora: { bgCell: "#f6f6f6", textDark: "#a0a0a0" },
} satisfies Record<string, Partial<Theme>>;

interface Area {
  l0: number;
  l1: number;
  c0: number;
  c1: number;
  cabecalho: number;
}

function areaDaReceita(receita: Receita, deteccao?: Deteccao | null): Area | null {
  const recorte = receita.steps.find((p) => p.op === "select_range" && ativo(p));
  const inicio = deA1(recorte?.start);
  if (!recorte || !inicio) return null;
  const fim = deA1(recorte.end);
  const cab = receita.steps.find((p) => p.op === "header_rows" && ativo(p));
  return {
    l0: inicio.linha,
    l1: fim?.linha ?? (deteccao ? deteccao.dados[1] - 1 : Number.MAX_SAFE_INTEGER),
    c0: inicio.col,
    c1: fim?.col ?? (deteccao ? indiceDaLetra(deteccao.colunas[1]) : Number.MAX_SAFE_INTEGER),
    cabecalho: cab ? Number(cab.n ?? 1) : 0,
  };
}

const VAZIA: GridSelection = { columns: CompactSelection.empty(), rows: CompactSelection.empty() };

export function VisaoBruta({
  projeto,
  receita,
  deteccao,
  aoUsarArea,
}: {
  projeto: string;
  receita: Receita;
  deteccao?: Deteccao | null;
  aoUsarArea: (inicio: string, fim: string) => void;
}) {
  const [selecao, setSelecao] = useState<GridSelection>(VAZIA);
  const area = useMemo(() => areaDaReceita(receita, deteccao), [receita, deteccao]);
  const totais = useMemo(() => new Set((deteccao?.totais ?? []).map((l) => l - 1)), [deteccao]);

  const tema = useCallback(
    (col: number, linha: number): Partial<Theme> | undefined => {
      if (!area) return undefined;
      if (linha < area.l0) return CORES.titulo;
      if (linha > area.l1) return CORES.rodape;
      if (col < area.c0 || col > area.c1) return CORES.fora;
      if (linha < area.l0 + area.cabecalho) return CORES.cabecalho;
      if (totais.has(linha)) return CORES.totais;
      return undefined;
    },
    [area, totais],
  );

  const r = selecao.current?.range;
  const intervalo = r ? [paraA1(r.y, r.x), paraA1(r.y + r.height - 1, r.x + r.width - 1)] : null;

  return (
    <div className="visao-bruta">
      <div className="barra-ferramentas">
        <ul className="legenda" aria-label={T.bruta.legenda}>
          {(
            [
              ["titulo", T.bruta.titulo],
              ["cabecalho", T.bruta.cabecalho],
              ["dados", T.bruta.dados],
              ["totais", T.bruta.totais],
              ["rodape", T.bruta.rodape],
              ["fora", T.bruta.foraDaArea],
            ] as const
          ).map(([k, rotulo]) => (
            <li key={k}>
              <span
                className="amostra"
                style={{ background: k === "dados" ? "#fff" : CORES[k].bgCell }}
              />
              {rotulo}
            </li>
          ))}
        </ul>
        <span className="dica">
          {intervalo ? T.bruta.selecao(`${intervalo[0]}:${intervalo[1]}`) : T.bruta.dica}
        </span>
        <button
          type="button"
          className="primario"
          disabled={!intervalo}
          onClick={() => {
            if (!intervalo) return;
            aoUsarArea(intervalo[0], intervalo[1]);
            setSelecao(VAZIA);
          }}
        >
          {T.bruta.usarSelecao}
        </button>
      </div>
      <GradeDados
        projeto={projeto}
        passo="raw"
        versao="raw"
        rotulo={T.projeto.arquivoOriginal}
        numerarLinhas
        temaCelula={tema}
        selecao={selecao}
        aoSelecionar={setSelecao}
      />
    </div>
  );
}

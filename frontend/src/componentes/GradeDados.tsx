// Grade virtualizada (F1.H7). O Glide Data Grid só desenha as células
// visíveis; as linhas vêm do GET /preview em páginas por offset. Rolagem
// rápida pede página a cada movimento: o pedido espera a rolagem parar
// (debounce) e o pedido anterior, que ficou obsoleto, é cancelado — só a
// última região pedida importa (§8.8 do design).

import DataEditor, {
  GridCellKind,
  GridColumnIcon,
  type GridCell,
  type GridColumn,
  type GridSelection,
  type Item,
  type Rectangle,
  type Theme,
} from "@glideapps/glide-data-grid";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { abortado, api, chamar, type Pagina } from "../api/cliente";
import { T } from "../textos";
import { CaixaErro, Carregando } from "./Estado";

export const PAGINA = 100;
const MAX_POR_PEDIDO = 1000; // limite do GET /preview
const ESPERA_MS = 80;

type Coluna = Pagina["columns"][number];

export interface PropsGrade {
  projeto: string;
  /** Passo do preview: id, "raw" ou undefined (receita inteira). */
  passo?: string;
  /** Muda quando a receita muda (ETag): invalida as páginas guardadas. */
  versao: string;
  rotulo: string;
  numerarLinhas?: boolean;
  temaCelula?: (col: number, linha: number) => Partial<Theme> | undefined;
  selecao?: GridSelection;
  aoSelecionar?: (s: GridSelection) => void;
  aoClicarCabecalho?: (coluna: string) => void;
  aoErrar?: (erro: unknown) => void;
}

function icone(dtype: string): GridColumnIcon {
  if (/^(Int|UInt|Float|Decimal)/.test(dtype)) return GridColumnIcon.HeaderNumber;
  if (/^(Date|Datetime)/.test(dtype)) return GridColumnIcon.HeaderDate;
  if (dtype === "Boolean") return GridColumnIcon.HeaderBoolean;
  return GridColumnIcon.HeaderString;
}

function texto(valor: unknown): string {
  if (valor == null) return "";
  if (typeof valor === "number")
    return valor.toLocaleString("pt-BR", { maximumFractionDigits: 10 });
  if (typeof valor === "boolean") return valor ? T.comum.sim : T.comum.nao;
  if (typeof valor === "string" && /^\d{4}-\d{2}-\d{2}$/.test(valor))
    return valor.split("-").reverse().join("/");
  return String(valor);
}

export function GradeDados(props: PropsGrade) {
  const { projeto, passo, versao, aoErrar } = props;
  const paginas = useRef(new Map<number, unknown[][]>());
  const pedido = useRef<AbortController | null>(null);
  const espera = useRef<number | undefined>(undefined);
  const [info, setInfo] = useState<{ colunas: Coluna[]; total: number } | null>(null);
  const [falha, setFalha] = useState<{ chave: string; erro: unknown } | null>(null);
  const [desenho, setDesenho] = useState(0);
  const [larguras, setLarguras] = useState<Record<string, number>>({});
  const avisos = useRef({ aoErrar });
  useLayoutEffect(() => {
    avisos.current = { aoErrar };
  });

  const buscar = useCallback(
    async (primeira: number, ultima: number, signal: AbortSignal) => {
      const offset = primeira * PAGINA;
      const limit = Math.min(MAX_POR_PEDIDO, (ultima - primeira + 1) * PAGINA);
      const p = await chamar(
        api.GET("/api/projects/{project_id}/preview", {
          params: { path: { project_id: projeto }, query: { step: passo, offset, limit } },
          signal,
        }),
      );
      for (let i = 0; i * PAGINA < Math.max(p.rows.length, 1); i++)
        paginas.current.set(primeira + i, p.rows.slice(i * PAGINA, (i + 1) * PAGINA));
      return p;
    },
    [projeto, passo],
  );

  const [rodada, setRodada] = useState(0);
  // Erro só vale para o passo e a versão em que aconteceu.
  const chave = `${projeto}|${passo}|${versao}|${rodada}`;
  const erro = falha?.chave === chave ? falha.erro : null;

  useEffect(() => {
    paginas.current = new Map();
    pedido.current?.abort();
    const ctrl = new AbortController();
    pedido.current = ctrl;
    buscar(0, 1, ctrl.signal).then(
      (p) => {
        setDesenho((n) => n + 1);
        setInfo({ colunas: p.columns, total: p.total_rows });
      },
      (e) => {
        if (abortado(e)) return;
        setInfo(null);
        setFalha({ chave, erro: e });
        avisos.current.aoErrar?.(e);
      },
    );
    return () => ctrl.abort();
  }, [buscar, chave]);

  useEffect(() => () => window.clearTimeout(espera.current), []);

  const regiaoMudou = useCallback(
    (r: Rectangle) => {
      window.clearTimeout(espera.current);
      espera.current = window.setTimeout(() => {
        const primeira = Math.max(0, Math.floor(r.y / PAGINA) - 1);
        const ultima = Math.floor((r.y + r.height) / PAGINA) + 1;
        const faltam: number[] = [];
        for (let i = primeira; i <= ultima; i++) if (!paginas.current.has(i)) faltam.push(i);
        if (!faltam.length) return;
        pedido.current?.abort(); // a região anterior não interessa mais
        const ctrl = new AbortController();
        pedido.current = ctrl;
        const de = faltam[0];
        const ate = Math.min(faltam[faltam.length - 1], de + MAX_POR_PEDIDO / PAGINA - 1);
        buscar(de, ate, ctrl.signal).then(
          () => setDesenho((n) => n + 1),
          (e) => {
            if (!abortado(e)) setFalha({ chave, erro: e });
          },
        );
      }, ESPERA_MS);
    },
    [buscar, chave],
  );

  const { temaCelula } = props;
  const celula = useCallback(
    ([col, linha]: Item): GridCell => {
      const pagina = paginas.current.get(Math.floor(linha / PAGINA));
      const tema = temaCelula?.(col, linha);
      if (!pagina) return { kind: GridCellKind.Loading, allowOverlay: false, themeOverride: tema };
      const valor = pagina[linha % PAGINA]?.[col];
      const t = texto(valor);
      return {
        kind: GridCellKind.Text,
        data: t,
        displayData: t,
        allowOverlay: false,
        contentAlign: typeof valor === "number" ? "right" : undefined,
        themeOverride: tema,
      };
    },
    // função nova a cada página que chega: é o que faz o Glide redesenhar
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [temaCelula, desenho, info],
  );

  const colunas: GridColumn[] = useMemo(
    () =>
      (info?.colunas ?? []).map((c) => ({
        id: c.name,
        title: c.name,
        icon: icone(c.dtype),
        width: larguras[c.name] ?? Math.min(260, Math.max(90, c.name.length * 9 + 40)),
      })),
    [info, larguras],
  );

  if (erro != null)
    return (
      <div className="grade grade-erro">
        <CaixaErro erro={erro} tentarDeNovo={() => setRodada((n) => n + 1)} />
      </div>
    );
  if (!info)
    return (
      <div className="grade">
        <Carregando />
      </div>
    );

  return (
    <div className="grade" aria-label={props.rotulo} data-total={info.total}>
      <div className="grade-barra">
        <span>{props.rotulo}</span>
        <small>{T.grade.total(info.total)}</small>
      </div>
      {info.total === 0 && <p className="dica">{T.grade.vazia}</p>}
      <div className="grade-corpo">
        <DataEditor
          columns={colunas}
          rows={info.total}
          getCellContent={celula}
          onVisibleRegionChanged={regiaoMudou}
          rowMarkers={props.numerarLinhas ? "number" : "none"}
          smoothScrollX
          smoothScrollY
          width="100%"
          height="100%"
          rangeSelect={props.aoSelecionar ? "rect" : "none"}
          columnSelect="none"
          rowSelect="none"
          gridSelection={props.selecao}
          onGridSelectionChange={props.aoSelecionar}
          onHeaderClicked={(i) => props.aoClicarCabecalho?.(colunas[i]?.title ?? "")}
          onColumnResize={(c, largura) => setLarguras((l) => ({ ...l, [c.title]: largura }))}
          getCellsForSelection
        />
      </div>
    </div>
  );
}

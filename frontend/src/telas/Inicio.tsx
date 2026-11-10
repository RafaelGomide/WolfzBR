// Tela inicial (F1.H3): arrastar arquivo e projetos recentes. Planilha com
// mais de uma aba visível pergunta qual importar (F1.H4), ou quais juntar
// (F3).

import { useMemo, useRef, useState, type DragEvent } from "react";
import { api, chamar, formulario, type Aba, type ProjetoResumo } from "../api/cliente";
import { RegraTexto } from "../componentes/AbaDaFonte";
import { CaixaErro, Carregando } from "../componentes/Estado";
import { SeletorTema } from "../componentes/SeletorTema";
import { T } from "../textos";
import { ORIGEM_PADRAO, preSelecao, useRegraAbas } from "../util/regraAbas";
import { irPara } from "../util/rota";
import { useCarregar } from "../util/useCarregar";

const PLANILHA = /\.(xlsx|xlsm|xls|ods)$/i;

function importar(arquivo: File, sheet?: string, juntar?: { sheets_regex: string | null }) {
  const combine_sheets = juntar ? JSON.stringify(juntar) : undefined;
  return chamar(
    api.POST("/api/projects", {
      body: { file: arquivo as unknown as string, sheet, combine_sheets },
      bodySerializer: () => formulario({ file: arquivo, sheet, combine_sheets }),
    }),
  );
}

function listarAbas(arquivo: File) {
  return chamar(
    api.POST("/api/sheets", {
      body: { file: arquivo as unknown as string },
      bodySerializer: () => formulario({ file: arquivo }),
    }),
  );
}

type EscolhaAba =
  { modo: "uma"; aba: string } | { modo: "juntar"; aba: string; sheets_regex: string | null };

/** Diálogo "Qual aba importar?" (F1.H4; F3, ux.md §2.1): uma aba, ou várias
 * juntas. Para juntar, a regra que vai para a receita vem do servidor e vale
 * também para este arquivo (D8); aba oculta nunca entra (D11). */
function SeletorAba({
  arquivo,
  abas,
  escolher,
  cancelar,
}: {
  arquivo: File;
  abas: Aba[];
  escolher: (escolha: EscolhaAba) => void;
  cancelar: () => void;
}) {
  const visiveis = useMemo(() => abas.filter((a) => !a.hidden), [abas]);
  const nomesVisiveis = useMemo(() => visiveis.map((a) => a.name), [visiveis]);
  const primeira = visiveis[0] ?? abas[0];
  const [modo, setModo] = useState<"uma" | "juntar">("uma");
  const [aba, setAba] = useState(primeira.name);
  const [marcadas, setMarcadas] = useState<string[]>(() => {
    const pre = preSelecao(visiveis);
    return pre.length >= 2 ? pre : nomesVisiveis;
  });
  // Na ordem do arquivo, que é a ordem da junção.
  const ordenadas = useMemo(
    () => nomesVisiveis.filter((n) => marcadas.includes(n)),
    [nomesVisiveis, marcadas],
  );
  const abaReceita = ordenadas[0] ?? null;
  const juntando = modo === "juntar";
  const { regra, erro, carregando } = useRegraAbas(
    juntando ? ordenadas : [],
    nomesVisiveis,
    abaReceita,
  );
  const linhas = visiveis
    .filter((a) => ordenadas.includes(a.name))
    .reduce((s, a) => s + (a.rows ?? 0), 0);
  const ocultas = abas.filter((a) => a.hidden).map((a) => a.name);
  const pronto = !juntando || (ordenadas.length >= 2 && !!regra && !carregando);

  function marcar(nome: string, sim: boolean) {
    setMarcadas((m) => (sim ? [...m, nome] : m.filter((x) => x !== nome)));
  }

  return (
    <div className="dialogo-fundo">
      <form
        className="dialogo"
        role="dialog"
        aria-modal="true"
        aria-label={T.abas.titulo}
        onSubmit={(e) => {
          e.preventDefault();
          if (!juntando) escolher({ modo: "uma", aba });
          else if (regra && abaReceita)
            escolher({ modo: "juntar", aba: abaReceita, sheets_regex: regra.sheets_regex });
        }}
      >
        <h2>{T.abas.titulo}</h2>
        <p>{T.abas.texto(arquivo.name)}</p>
        <fieldset className="modo-abas">
          <legend className="so-leitor">{T.abas.modo}</legend>
          <label>
            <input type="radio" name="modo" checked={!juntando} onChange={() => setModo("uma")} />
            {T.abas.umaAba}
          </label>
          <ul className="lista-abas" aria-label={T.abas.umaAba}>
            {abas.map((a) => (
              <li key={a.name}>
                <label>
                  <input
                    type="radio"
                    name="aba"
                    value={a.name}
                    checked={aba === a.name}
                    disabled={juntando}
                    onChange={() => setAba(a.name)}
                  />
                  <span>{a.name}</span>
                  {a.hidden && <em className="etiqueta">{T.abas.oculta}</em>}
                  <small>{T.abas.dimensao(a.rows, a.columns)}</small>
                </label>
              </li>
            ))}
          </ul>
          <label>
            <input type="radio" name="modo" checked={juntando} onChange={() => setModo("juntar")} />
            {T.abas.juntar}
          </label>
          <ul className="lista-abas" aria-label={T.abas.juntar}>
            {abas.map((a) => (
              <li key={a.name}>
                <label>
                  <input
                    type="checkbox"
                    checked={!a.hidden && marcadas.includes(a.name)}
                    disabled={!juntando || a.hidden}
                    onChange={(e) => marcar(a.name, e.target.checked)}
                  />
                  <span>{a.name}</span>
                  {a.hidden && <em className="etiqueta">{T.abas.naoEntra}</em>}
                  <small>{T.abas.dimensao(a.rows, a.columns)}</small>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        {juntando && (
          <div className="regra-abas" aria-live="polite">
            {ordenadas.length < 2 ? (
              <p className="dica">{T.abas.minimo}</p>
            ) : (
              <>
                <p>{T.abas.juntas(linhas)}</p>
                <p>{T.abas.colunaOrigem(ORIGEM_PADRAO)}</p>
                {erro != null && <CaixaErro erro={erro} />}
                {carregando && <p className="dica">{T.abas.calculandoRegra}</p>}
                {regra && !carregando && <RegraTexto regra={regra} />}
                {ocultas.length > 0 && <p className="dica">{T.aba.ocultas(ocultas)}</p>}
              </>
            )}
          </div>
        )}
        <div className="acoes">
          <button type="button" onClick={cancelar}>
            {T.comum.cancelar}
          </button>
          <button type="submit" className="primario" disabled={!pronto}>
            {juntando ? T.abas.importarVarias(ordenadas.length) : T.abas.importar}
          </button>
        </div>
      </form>
    </div>
  );
}

function Recentes() {
  const { dados, erro, carregando, recarregar } = useCarregar(
    (signal) => chamar(api.GET("/api/projects", { signal })),
    [],
  );
  const [erroApagar, setErroApagar] = useState<unknown>(null);

  async function apagar(p: ProjetoResumo) {
    if (!window.confirm(T.inicio.confirmarApagar(p.name ?? p.id))) return;
    setErroApagar(null);
    try {
      await chamar(
        api.DELETE("/api/projects/{project_id}", { params: { path: { project_id: p.id } } }),
      );
    } catch (e) {
      setErroApagar(e);
    }
    recarregar();
  }

  if (erro) return <CaixaErro erro={erro} tentarDeNovo={recarregar} />;
  if (carregando && !dados) return <Carregando />;
  const projetos = [...(dados ?? [])].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  );
  return (
    <section className="recentes" aria-label={T.inicio.recentes}>
      <h2>{T.inicio.recentes}</h2>
      {erroApagar != null && <CaixaErro erro={erroApagar} />}
      {projetos.length === 0 && <p className="dica">{T.inicio.nenhum}</p>}
      <ul>
        {projetos.map((p) => (
          <li key={p.id} className="projeto-item">
            <div>
              <strong>{p.name}</strong>
              <small>
                {[
                  p.format?.toUpperCase(),
                  p.sheet ? T.projeto.aba(p.sheet) : null,
                  p.rows != null ? T.comum.linhas(p.rows) : null,
                  p.created_at ? new Date(p.created_at).toLocaleString("pt-BR") : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
              {p.open_elsewhere && <em className="etiqueta aviso">{T.inicio.abertoEmOutra}</em>}
            </div>
            <div className="acoes">
              <button type="button" onClick={() => apagar(p)} disabled={p.open_elsewhere}>
                {T.inicio.apagar}
              </button>
              <button
                type="button"
                className="primario"
                onClick={() => irPara(p.id)}
                disabled={p.open_elsewhere}
              >
                {T.inicio.abrir}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Inicio() {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const [importando, setImportando] = useState<string | null>(null);
  const [erro, setErro] = useState<unknown>(null);
  const [escolha, setEscolha] = useState<{ arquivo: File; abas: Aba[] } | null>(null);

  async function receber(arquivo: File, escolhida?: EscolhaAba) {
    const sheet = escolhida?.aba;
    setErro(null);
    setEscolha(null);
    setImportando(arquivo.name);
    try {
      if (sheet === undefined && PLANILHA.test(arquivo.name)) {
        const abas = await listarAbas(arquivo);
        if (abas.filter((a) => !a.hidden).length > 1) {
          setEscolha({ arquivo, abas });
          return;
        }
      }
      const projeto = await importar(
        arquivo,
        sheet,
        escolhida?.modo === "juntar" ? { sheets_regex: escolhida.sheets_regex } : undefined,
      );
      irPara(projeto.id);
    } catch (e) {
      setErro(e);
    } finally {
      setImportando(null);
    }
  }

  function soltar(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    const arquivos = e.dataTransfer.files;
    if (arquivos.length !== 1) {
      setErro(new Error(T.inicio.umArquivoSo));
      return;
    }
    receber(arquivos[0]);
  }

  return (
    <main className="inicio">
      <header className="topo">
        <h1>{T.app.nome}</h1>
        <SeletorTema />
      </header>
      <div
        className={`area-soltar${arrastando ? " ativa" : ""}`}
        data-testid="area-soltar"
        onDragOver={(e) => {
          e.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={() => setArrastando(false)}
        onDrop={soltar}
      >
        {importando ? (
          <Carregando texto={T.inicio.importando(importando)} />
        ) : (
          <>
            <h2>{arrastando ? T.inicio.soltar : T.inicio.titulo}</h2>
            <p>{T.inicio.subtitulo}</p>
            <button type="button" className="primario" onClick={() => entrada.current?.click()}>
              {T.inicio.escolher}
            </button>
          </>
        )}
        <input
          ref={entrada}
          type="file"
          hidden
          aria-label={T.inicio.escolher}
          accept=".xlsx,.xlsm,.xls,.ods,.csv,.txt"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) receber(f);
          }}
        />
      </div>
      {erro != null && <CaixaErro erro={erro} />}
      {escolha && (
        <SeletorAba
          arquivo={escolha.arquivo}
          abas={escolha.abas}
          escolher={(e) => receber(escolha.arquivo, e)}
          cancelar={() => setEscolha(null)}
        />
      )}
      <Recentes />
    </main>
  );
}

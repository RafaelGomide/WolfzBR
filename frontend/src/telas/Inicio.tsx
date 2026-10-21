// Tela inicial (F1.H3): arrastar arquivo e projetos recentes. Planilha com
// mais de uma aba visível pergunta qual importar (F1.H4).

import { useRef, useState, type DragEvent } from "react";
import { api, chamar, formulario, type Aba, type ProjetoResumo } from "../api/cliente";
import { CaixaErro, Carregando } from "../componentes/Estado";
import { SeletorTema } from "../componentes/SeletorTema";
import { T } from "../textos";
import { irPara } from "../util/rota";
import { useCarregar } from "../util/useCarregar";

const PLANILHA = /\.(xlsx|xlsm|xls|ods)$/i;

function importar(arquivo: File, sheet?: string) {
  return chamar(
    api.POST("/api/projects", {
      body: { file: arquivo as unknown as string, sheet },
      bodySerializer: () => formulario({ file: arquivo, sheet }),
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

function SeletorAba({
  arquivo,
  abas,
  escolher,
  cancelar,
}: {
  arquivo: File;
  abas: Aba[];
  escolher: (aba: string) => void;
  cancelar: () => void;
}) {
  const primeira = abas.find((a) => !a.hidden) ?? abas[0];
  const [aba, setAba] = useState(primeira.name);
  return (
    <div className="dialogo-fundo">
      <form
        className="dialogo"
        role="dialog"
        aria-modal="true"
        aria-label={T.abas.titulo}
        onSubmit={(e) => {
          e.preventDefault();
          escolher(aba);
        }}
      >
        <h2>{T.abas.titulo}</h2>
        <p>{T.abas.texto(arquivo.name)}</p>
        <ul className="lista-abas">
          {abas.map((a) => (
            <li key={a.name}>
              <label>
                <input
                  type="radio"
                  name="aba"
                  value={a.name}
                  checked={aba === a.name}
                  onChange={() => setAba(a.name)}
                />
                <span>{a.name}</span>
                {a.hidden && <em className="etiqueta">{T.abas.oculta}</em>}
                <small>{T.abas.dimensao(a.rows, a.columns)}</small>
              </label>
            </li>
          ))}
        </ul>
        <div className="acoes">
          <button type="button" onClick={cancelar}>
            {T.comum.cancelar}
          </button>
          <button type="submit" className="primario">
            {T.abas.importar}
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

  async function receber(arquivo: File, sheet?: string) {
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
      const projeto = await importar(arquivo, sheet);
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
          escolher={(aba) => receber(escolha.arquivo, aba)}
          cancelar={() => setEscolha(null)}
        />
      )}
      <Recentes />
    </main>
  );
}

// Painel da receita (F1.H8): lista de passos; adicionar, remover,
// reordenar (arrastar ou botões), desativar e editar. O passo que falhou
// fica destacado com a mensagem e as colunas disponíveis (F1.H10).

import { useMemo, useState } from "react";
import { ErroApi, type Operacao, type Passo, type Receita } from "../api/cliente";
import { T } from "../textos";
import { ativo, mover, nomeOp, novoId, resumo } from "../util/receita";
import { passoNovo } from "../util/schema";
import { FormPasso } from "./FormPasso";
import { RevisaoMunicipios } from "./RevisaoMunicipios";

type Modo =
  | { tipo: "escolher" }
  | { tipo: "novo"; passo: Passo; posicao: number }
  | { tipo: "editar"; id: string }
  | { tipo: "revisar"; id: string }
  | null;

function errosDoPasso(erro: unknown, id: string): string[] | undefined {
  if (!(erro instanceof ErroApi)) return erro ? [String(erro)] : undefined;
  const lista = erro.errors?.length ? erro.errors : [erro.detail];
  const doPasso = lista.filter((e) => e.startsWith(`${id}.`) || e.startsWith(`${id}:`));
  return doPasso.length ? doPasso : lista;
}

function EscolherOp({
  ops,
  aoEscolher,
  aoCancelar,
}: {
  ops: Operacao[];
  aoEscolher: (op: Operacao) => void;
  aoCancelar: () => void;
}) {
  const [busca, setBusca] = useState("");
  const filtradas = useMemo(() => {
    const b = busca.trim().toLowerCase();
    return ops
      .filter((o) => !o.op.startsWith("teste_"))
      .filter((o) => !b || `${o.op} ${nomeOp(o.op)} ${o.doc}`.toLowerCase().includes(b))
      .sort((a, z) => nomeOp(a.op).localeCompare(nomeOp(z.op), "pt-BR"));
  }, [ops, busca]);
  return (
    <div className="escolher-op" role="dialog" aria-label={T.receita.escolherOp}>
      <h3>{T.receita.escolherOp}</h3>
      <input
        autoFocus
        type="search"
        placeholder={T.receita.buscarOp}
        aria-label={T.receita.buscarOp}
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
      />
      <ul>
        {filtradas.map((o) => (
          <li key={o.op}>
            <button type="button" onClick={() => aoEscolher(o)} title={o.doc}>
              <strong>{nomeOp(o.op)}</strong>
              <small>{o.op}</small>
            </button>
          </li>
        ))}
      </ul>
      <button type="button" onClick={aoCancelar}>
        {T.comum.cancelar}
      </button>
    </div>
  );
}

export function PainelReceita({
  projetoId,
  receita,
  ops,
  selecionado,
  aoSelecionar,
  erroPasso,
  colunasAntes,
  colunasDepois,
  salvar,
}: {
  projetoId: string;
  receita: Receita;
  ops: Operacao[];
  selecionado: string | null;
  aoSelecionar: (id: string | null) => void;
  erroPasso: ErroApi | null;
  colunasAntes: string[];
  colunasDepois: string[];
  salvar: (nova: Receita) => Promise<void>;
}) {
  const [modo, setModo] = useState<Modo>(null);
  const [errosForm, setErrosForm] = useState<string[] | undefined>();
  const [arrastado, setArrastado] = useState<number | null>(null);
  const porOp = useMemo(() => new Map(ops.map((o) => [o.op, o])), [ops]);
  const passos = receita.steps;

  async function trocar(steps: Passo[]) {
    try {
      await salvar({ ...receita, steps });
    } catch {
      // o erro aparece no aviso de salvamento da tela do projeto
    }
  }

  async function aplicar(passo: Passo, posicao?: number) {
    const steps =
      posicao === undefined
        ? passos.map((p) => (p.id === passo.id ? { ...passo, enabled: p.enabled } : p))
        : [...passos.slice(0, posicao), passo, ...passos.slice(posicao)];
    try {
      await salvar({ ...receita, steps });
      setModo(null);
      setErrosForm(undefined);
      aoSelecionar(passo.id);
    } catch (e) {
      setErrosForm(errosDoPasso(e, passo.id));
    }
  }

  function novo(op: Operacao) {
    const i = selecionado ? passos.findIndex((p) => p.id === selecionado) + 1 : passos.length;
    setErrosForm(undefined);
    setModo({ tipo: "novo", passo: passoNovo(op, novoId(receita)), posicao: i });
  }

  const editando = modo?.tipo === "editar" ? passos.find((p) => p.id === modo.id) : undefined;

  return (
    <aside className="painel-receita" aria-label={T.receita.titulo}>
      <div className="painel-titulo">
        <h2>{T.receita.titulo}</h2>
        <button
          type="button"
          className="primario"
          onClick={() => setModo({ tipo: "escolher" })}
          disabled={modo !== null}
        >
          + {T.receita.adicionar}
        </button>
      </div>

      {modo?.tipo === "escolher" && (
        <EscolherOp ops={ops} aoEscolher={novo} aoCancelar={() => setModo(null)} />
      )}
      {modo?.tipo === "novo" && porOp.get(modo.passo.op) && (
        <FormPasso
          key={modo.passo.id}
          operacao={porOp.get(modo.passo.op)!}
          passo={modo.passo}
          colunas={colunasDepois}
          erros={errosForm}
          titulo={T.receita.novoPasso}
          aoAplicar={(p) => aplicar(p, modo.posicao)}
          aoCancelar={() => setModo(null)}
        />
      )}

      {passos.length === 0 && <p className="dica">{T.receita.vazia}</p>}
      <ol className="passos">
        <li>
          <button
            type="button"
            className={`passo-origem${selecionado === "raw" ? " selecionado" : ""}`}
            onClick={() => aoSelecionar("raw")}
          >
            {T.projeto.arquivoOriginal}
          </button>
        </li>
        {passos.map((p, i) => {
          const comErro = erroPasso?.step_id === p.id;
          const classes = [
            "passo",
            selecionado === p.id ? "selecionado" : "",
            ativo(p) ? "" : "desativado",
            comErro ? "com-erro" : "",
            arrastado === i ? "arrastando" : "",
          ].join(" ");
          return (
            <li
              key={p.id}
              className={classes}
              data-passo={p.id}
              draggable={modo === null}
              onDragStart={(e) => {
                setArrastado(i);
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={() => setArrastado(null)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (arrastado !== null && arrastado !== i) trocar(mover(passos, arrastado, i));
                setArrastado(null);
              }}
            >
              <div className="passo-linha">
                <span className="alca" title={T.receita.arrastar} aria-hidden="true">
                  ⋮⋮
                </span>
                <button
                  type="button"
                  className="passo-nome"
                  onClick={() => aoSelecionar(p.id)}
                  aria-current={selecionado === p.id}
                >
                  <span className="passo-id">{p.id}</span> {nomeOp(p.op)}
                  {!ativo(p) && <em className="etiqueta">{T.receita.desativado}</em>}
                  <small>{resumo(p)}</small>
                </button>
              </div>
              <div className="passo-acoes">
                <button
                  type="button"
                  onClick={() => {
                    aoSelecionar(p.id);
                    setErrosForm(undefined);
                    setModo({ tipo: "editar", id: p.id });
                  }}
                  disabled={modo !== null || !porOp.has(p.op)}
                >
                  {T.receita.editar}
                </button>
                {p.op === "normalize_municipio" && (
                  <button
                    type="button"
                    onClick={() => {
                      aoSelecionar(p.id);
                      setModo({ tipo: "revisar", id: p.id });
                    }}
                    disabled={modo !== null}
                  >
                    {T.municipios.revisar}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() =>
                    trocar(passos.map((x) => (x.id === p.id ? { ...x, enabled: !ativo(x) } : x)))
                  }
                >
                  {ativo(p) ? T.receita.desativar : T.receita.ativar}
                </button>
                <button
                  type="button"
                  aria-label={`${T.receita.subir} ${p.id}`}
                  disabled={i === 0}
                  onClick={() => trocar(mover(passos, i, i - 1))}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`${T.receita.descer} ${p.id}`}
                  disabled={i === passos.length - 1}
                  onClick={() => trocar(mover(passos, i, i + 1))}
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (!window.confirm(T.receita.confirmarRemover(p.id))) return;
                    if (selecionado === p.id) aoSelecionar(null);
                    trocar(passos.filter((x) => x.id !== p.id));
                  }}
                >
                  {T.receita.remover}
                </button>
              </div>
              {comErro && erroPasso && (
                <div className="estado erro" role="alert">
                  <strong>{T.erroPasso.titulo(p.id)}</strong>
                  <p>{erroPasso.detail}</p>
                  {erroPasso.available_columns && (
                    <>
                      <p>{T.erroPasso.colunas}</p>
                      <ul className="fichas">
                        {erroPasso.available_columns.map((c) => (
                          <li key={c} className="ficha">
                            {c}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
              {modo?.tipo === "revisar" && modo.id === p.id && (
                <RevisaoMunicipios
                  projetoId={projetoId}
                  passo={p}
                  salvarManual={(manual) =>
                    salvar({
                      ...receita,
                      steps: passos.map((x) => (x.id === p.id ? { ...x, manual } : x)),
                    })
                  }
                  aoFechar={() => setModo(null)}
                />
              )}
              {editando?.id === p.id && porOp.get(p.op) && (
                <FormPasso
                  key={`${p.id}-editar`}
                  operacao={porOp.get(p.op)!}
                  passo={editando}
                  colunas={colunasAntes}
                  erros={errosForm}
                  titulo={T.receita.editarPasso(p.id)}
                  aoAplicar={(np) => aplicar(np)}
                  aoCancelar={() => setModo(null)}
                />
              )}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

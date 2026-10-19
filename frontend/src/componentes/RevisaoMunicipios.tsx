// Revisão dos municípios (F2.C4): lista os valores que o casamento com o
// IBGE não resolveu com segurança, com sugestões. Aceitar ou corrigir grava
// no "manual" do passo, que vale nas próximas execuções e entra no de-para
// exportado. Nada é aplicado sem passar por aqui ou pelo limiar do passo.

import { useState } from "react";
import { api, chamar, type Passo } from "../api/cliente";
import type { components } from "../api/schema";
import { T } from "../textos";
import { useCarregar } from "../util/useCarregar";
import { CaixaErro, Carregando } from "./Estado";

type Item = components["schemas"]["ItemRevisaoMunicipio"];
type Municipio = components["schemas"]["Municipio"];
type Manual = Record<string, string | null>;

// O que aparece sem "mostrar todos": o que precisa de olho humano.
const A_REVISAR = new Set(["revisar", "sem_correspondencia", "fuzzy", "manual"]);

function rotulo(m: Municipio): string {
  return `${m.nome} (${m.uf})`;
}

function Busca({ uf, aoEscolher }: { uf: string | null; aoEscolher: (m: Municipio) => void }) {
  const [texto, setTexto] = useState("");
  const q = texto.trim();
  const { dados } = useCarregar(
    async (signal) =>
      q.length < 2
        ? []
        : chamar(
            api.GET("/api/municipios", {
              params: { query: { q, uf: uf ?? undefined, limit: 8 } },
              signal,
            }),
          ),
    [q, uf],
  );
  return (
    <div className="busca-municipio">
      <input
        autoFocus
        type="search"
        placeholder={T.municipios.buscar}
        aria-label={T.municipios.buscar}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
      />
      {dados && dados.length > 0 && (
        <ul className="sugestoes">
          {dados.map((m) => (
            <li key={m.codigo_ibge}>
              <button type="button" className="sugestao" onClick={() => aoEscolher(m)}>
                {rotulo(m)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Linha({
  item,
  ocupado,
  definir,
}: {
  item: Item;
  ocupado: boolean;
  definir: (chave: string, codigo: string | null | undefined) => void;
}) {
  const [corrigindo, setCorrigindo] = useState(false);
  const resolvido = item.nome_ibge ? `${item.nome_ibge} (${item.codigo_ibge})` : null;
  return (
    <li className={`item-municipio status-${item.status}`}>
      <div className="item-cabeca">
        <strong>{item.valor}</strong>
        {item.uf && <span className="etiqueta">{item.uf}</span>}
        <span className={`etiqueta${item.status === "revisar" ? " aviso" : ""}`}>
          {T.municipios.status[item.status] ?? item.status}
          {item.nota != null && item.status !== "exato" ? ` · ${item.nota}` : ""}
        </span>
        <small>{T.comum.linhas(item.linhas)}</small>
      </div>
      {resolvido && <p className="dica">→ {resolvido}</p>}
      <div className="item-acoes">
        {item.status !== "manual" &&
          item.sugestoes.slice(0, 3).map((m) => (
            <button
              key={m.codigo_ibge}
              type="button"
              disabled={ocupado}
              onClick={() => definir(item.chave, m.codigo_ibge)}
            >
              {item.codigo_ibge === m.codigo_ibge ? T.municipios.confirmar : T.municipios.aceitar}{" "}
              {rotulo(m)}
              {m.nota != null ? ` · ${m.nota}` : ""}
            </button>
          ))}
        <button type="button" disabled={ocupado} onClick={() => setCorrigindo((c) => !c)}>
          {T.municipios.corrigir}
        </button>
        {item.status !== "sem_correspondencia" && item.status !== "manual" && (
          <button type="button" disabled={ocupado} onClick={() => definir(item.chave, null)}>
            {T.municipios.semCorrespondencia}
          </button>
        )}
        {(item.status === "manual" || item.status === "sem_correspondencia") && (
          <button type="button" disabled={ocupado} onClick={() => definir(item.chave, undefined)}>
            {T.municipios.desfazer}
          </button>
        )}
      </div>
      {corrigindo && (
        <Busca
          uf={item.uf ?? null}
          aoEscolher={(m) => {
            setCorrigindo(false);
            definir(item.chave, m.codigo_ibge);
          }}
        />
      )}
    </li>
  );
}

export function RevisaoMunicipios({
  projetoId,
  passo,
  salvarManual,
  aoFechar,
}: {
  projetoId: string;
  passo: Passo;
  salvarManual: (manual: Manual) => Promise<void>;
  aoFechar: () => void;
}) {
  const manual = (passo.manual as Manual | undefined) ?? {};
  const [todos, setTodos] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const { dados, erro, carregando, recarregar } = useCarregar(
    (signal) =>
      chamar(
        api.GET("/api/projects/{project_id}/steps/{step_id}/municipios", {
          params: { path: { project_id: projetoId, step_id: passo.id } },
          signal,
        }),
      ),
    // Sem o "manual" aqui: a receita muda na tela antes de o servidor salvar;
    // a lista recarrega depois do salvamento (definir).
    [projetoId, passo.id, passo.col, passo.uf_col, passo.threshold],
  );

  async function definir(chave: string, codigo: string | null | undefined) {
    // undefined desfaz a decisão manual; null marca "sem correspondência".
    const novo = { ...manual };
    if (codigo === undefined) delete novo[chave];
    else novo[chave] = codigo;
    setOcupado(true);
    try {
      await salvarManual(novo);
      recarregar();
    } catch {
      // o erro aparece no aviso de salvamento da tela do projeto
    } finally {
      setOcupado(false);
    }
  }

  const itens = dados ?? [];
  const visiveis = itens.filter((i) => todos || A_REVISAR.has(i.status));
  const pendentes = itens.filter((i) => i.status === "revisar").length;

  return (
    <div className="revisao-municipios" role="region" aria-label={T.municipios.titulo(passo.id)}>
      <h3>{T.municipios.titulo(passo.id)}</h3>
      <p className="dica">{T.municipios.explicacao}</p>
      {erro ? (
        <CaixaErro erro={erro} tentarDeNovo={recarregar} />
      ) : !dados ? (
        <Carregando />
      ) : (
        <>
          <p>
            {pendentes > 0 ? T.municipios.pendentes(pendentes) : T.municipios.nadaPendente}{" "}
            {carregando && <small>{T.comum.carregando}</small>}
          </p>
          <label className="campo-linha">
            <input type="checkbox" checked={todos} onChange={(e) => setTodos(e.target.checked)} />
            {T.municipios.mostrarTodos(itens.length)}
          </label>
          {visiveis.length === 0 ? (
            <p className="dica">{T.municipios.vazio}</p>
          ) : (
            <ul className="itens-municipio">
              {visiveis.map((i) => (
                <Linha key={i.chave} item={i} ocupado={ocupado} definir={definir} />
              ))}
            </ul>
          )}
        </>
      )}
      <div className="acoes">
        <button type="button" onClick={aoFechar}>
          {T.comum.fechar}
        </button>
      </div>
    </div>
  );
}

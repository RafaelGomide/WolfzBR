// Sugestões automáticas (F2.E3): passos propostos pelas regras sobre a tabela
// no fim da receita. Aceitar acrescenta os passos no fim; editar abre o
// formulário do passo antes; rejeitar grava no projeto e a sugestão não volta.
// Nada entra na receita sem um clique.

import { useState } from "react";
import { api, chamar, ErroApi, type Passo, type Receita } from "../api/cliente";
import type { components } from "../api/schema";
import { T } from "../textos";
import { nomeOp, numerar } from "../util/receita";
import { useCarregar } from "../util/useCarregar";
import { CaixaErro } from "./Estado";

type Sugestao = components["schemas"]["Sugestao"];

const VERIFICACAO = 50; // wolfz.core.suggest.VERIFICACAO

const pct = (x: number) =>
  x.toLocaleString("pt-BR", { style: "percent", maximumFractionDigits: 0 });

export function Sugestoes({
  projetoId,
  receita,
  versao,
  salvar,
  aoEditar,
}: {
  projetoId: string;
  receita: Receita;
  versao: string;
  salvar: (nova: Receita) => Promise<void>;
  aoEditar: (passo: Passo) => void;
}) {
  const [aberto, setAberto] = useState(true);
  const [ocupado, setOcupado] = useState(false);
  const [rodada, setRodada] = useState(0);
  const { dados, erro } = useCarregar(
    (signal) =>
      chamar(
        api.GET("/api/projects/{project_id}/suggestions", {
          params: { path: { project_id: projetoId } },
          signal,
        }),
      ),
    [projetoId, versao, rodada],
  );

  // Receita com passo que falha: as sugestões ficam para depois do conserto.
  if (erro) return erro instanceof ErroApi && erro.passoComErro ? null : <CaixaErro erro={erro} />;
  const lista = dados ?? [];
  if (lista.length === 0) return null;
  // "Aceitar todas" deixa as verificações (order 50) para depois quando há
  // outros passos: elas foram calculadas na tabela de agora, e despivotar ou
  // tirar colunas muda a tabela. Depois de salvar, voltam calculadas de novo.
  const passos = lista.filter((s) => s.kind === "passo");
  const comPasso = passos.some((s) => s.order < VERIFICACAO)
    ? passos.filter((s) => s.order < VERIFICACAO)
    : passos;

  async function acrescentar(passos: Record<string, unknown>[]) {
    setOcupado(true);
    try {
      await salvar({ ...receita, steps: [...receita.steps, ...numerar(receita, passos)] });
    } catch {
      // o erro aparece no aviso de salvamento da tela do projeto
    } finally {
      setOcupado(false);
    }
  }

  async function rejeitar(s: Sugestao) {
    setOcupado(true);
    try {
      await chamar(
        api.POST("/api/projects/{project_id}/suggestions/rejections", {
          params: { path: { project_id: projetoId } },
          body: { rule: s.rule, cols: s.cols },
        }),
      );
      setRodada((r) => r + 1);
    } finally {
      setOcupado(false);
    }
  }

  return (
    <section className="sugestoes-painel" aria-label={T.sugestoes.titulo(lista.length)}>
      <div className="sugestoes-cabeca">
        <button
          type="button"
          className="sugestoes-alternar"
          aria-expanded={aberto}
          onClick={() => setAberto((a) => !a)}
        >
          {aberto ? "▾" : "▸"} {T.sugestoes.titulo(lista.length)}
        </button>
        {aberto && comPasso.length > 1 && (
          <button
            type="button"
            className="primario"
            disabled={ocupado}
            onClick={() => acrescentar(comPasso.flatMap((s) => s.steps))}
          >
            {T.sugestoes.aceitarTodas(comPasso.length)}
          </button>
        )}
      </div>
      {aberto && (
        <ul className="sugestoes-lista">
          {lista.map((s) => (
            <li key={s.id} className={`sugestao-item${s.kind === "aviso" ? " aviso" : ""}`}>
              <div className="sugestao-titulo">
                <strong>
                  {s.kind === "aviso"
                    ? T.sugestoes.aviso
                    : s.steps.map((p) => nomeOp(String(p.op))).join(" + ")}
                </strong>
                <span className="etiqueta" title={T.sugestoes.confianca}>
                  {pct(s.confidence)}
                </span>
              </div>
              <p>{s.reason}</p>
              <div className="sugestao-acoes">
                {s.kind === "passo" ? (
                  <>
                    <button type="button" disabled={ocupado} onClick={() => acrescentar(s.steps)}>
                      {T.sugestoes.aceitar}
                    </button>
                    {s.steps.length === 1 && (
                      <button
                        type="button"
                        disabled={ocupado}
                        onClick={() => aoEditar(numerar(receita, s.steps)[0])}
                      >
                        {T.sugestoes.editar}
                      </button>
                    )}
                    <button type="button" disabled={ocupado} onClick={() => rejeitar(s)}>
                      {T.sugestoes.rejeitar}
                    </button>
                  </>
                ) : (
                  <button type="button" disabled={ocupado} onClick={() => rejeitar(s)}>
                    {T.sugestoes.entendi}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Perfil de uma coluna (F1.H11): aparece ao clicar no cabeçalho do grid.
// O perfil é calculado para todas as colunas do passo de uma vez; trocar de
// coluna no mesmo passo não pede de novo.

import { api, chamar } from "../api/cliente";
import { T } from "../textos";
import { useCarregar } from "../util/useCarregar";
import { CaixaErro, Carregando } from "./Estado";

const pct = (x: number) =>
  x.toLocaleString("pt-BR", { style: "percent", maximumFractionDigits: 1 });

// Mínimo e máximo como no Brasil: 1.234,5 e 31/12/2024 (a API manda número
// e data ISO).
function valorBr(v: number | string): string {
  if (typeof v === "number") return v.toLocaleString("pt-BR", { maximumFractionDigits: 6 });
  const data = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return data ? `${data[3]}/${data[2]}/${data[1]}` : v;
}

export function PainelPerfil({
  projeto,
  passo,
  versao,
  coluna,
  aoFechar,
}: {
  projeto: string;
  passo?: string;
  versao: string;
  coluna: string;
  aoFechar: () => void;
}) {
  const { dados, erro, carregando, recarregar } = useCarregar(
    (signal) =>
      chamar(
        api.GET("/api/projects/{project_id}/profile", {
          params: { path: { project_id: projeto }, query: { step: passo } },
          signal,
        }),
      ),
    [projeto, passo, versao],
  );
  const c = dados?.columns.find((x) => x.name === coluna);

  return (
    <aside className="painel-perfil" aria-label={T.perfil.titulo(coluna)}>
      <div className="painel-titulo">
        <h2>{T.perfil.titulo(coluna)}</h2>
        <button type="button" onClick={aoFechar} aria-label={T.comum.fechar}>
          ×
        </button>
      </div>
      {erro != null && <CaixaErro erro={erro} tentarDeNovo={recarregar} />}
      {carregando && !c && erro == null && <Carregando />}
      {c && dados && (
        <dl className="perfil">
          <dt>{T.perfil.tipo}</dt>
          <dd>
            <strong>{T.perfil.tipos[c.inferred_type] ?? c.inferred_type}</strong>
            {c.inferred_type !== "texto" && c.inferred_type !== "vazio" && (
              <small> · {T.perfil.casam(pct(c.type_rate))}</small>
            )}
          </dd>
          <dt>{T.perfil.vazios}</dt>
          <dd>
            {c.nulls.toLocaleString("pt-BR")} ({pct(c.null_pct)})
          </dd>
          <dt>{T.perfil.marcadores}</dt>
          <dd>
            {c.null_markers.toLocaleString("pt-BR")} ({pct(c.null_marker_pct)})
          </dd>
          <dt>{T.perfil.distintos}</dt>
          <dd>{c.distinct.toLocaleString("pt-BR")}</dd>
          {c.minimum != null && (
            <>
              <dt>{T.perfil.minimo}</dt>
              <dd>{valorBr(c.minimum)}</dd>
              <dt>{T.perfil.maximo}</dt>
              <dd>{c.maximum != null && valorBr(c.maximum)}</dd>
            </>
          )}
          <dt>{T.perfil.formas}</dt>
          <dd>
            <ul className="formas">
              {c.top_shapes.map((f) => (
                <li key={f.shape}>
                  <code>{f.shape}</code> <small>× {f.count.toLocaleString("pt-BR")}</small>
                </li>
              ))}
            </ul>
          </dd>
          <dt>{T.perfil.exemplos}</dt>
          <dd>
            <ul className="fichas">
              {c.examples.map((e) => (
                <li key={e} className="ficha">
                  {e}
                </li>
              ))}
            </ul>
          </dd>
        </dl>
      )}
      {dados?.is_sample && (
        <p className="dica">{T.perfil.amostra(dados.sampled_rows, dados.total_rows)}</p>
      )}
    </aside>
  );
}

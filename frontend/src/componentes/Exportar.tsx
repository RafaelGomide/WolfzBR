// Tela de exportação (F1.H12, F1.I): formatos, opções do CSV, pasta de
// saída, confirmação quando já existem arquivos com os mesmos nomes (F0.A6)
// e aviso de células que podem virar fórmula (F0.A9). Formato que depende de
// extra não instalado (Tableau, F3.A1) aparece desabilitado com a instrução.

import { useState } from "react";
import { api, chamar, ErroApi, type Exportacao } from "../api/cliente";
import { T } from "../textos";
import { useCarregar } from "../util/useCarregar";
import { CaixaErro, Carregando } from "./Estado";

type Formato = "csv" | "parquet" | "xlsx" | "powerquery" | "python" | "hyper" | "pbip";
type Separador = "," | ";" | "\t";
const FORMATOS: Formato[] = ["csv", "xlsx", "parquet", "powerquery", "python", "pbip", "hyper"];
const SEPARADORES: Separador[] = [";", ",", "\t"];

export function Exportar({ projeto, aoFechar }: { projeto: string; aoFechar: () => void }) {
  const [formatos, setFormatos] = useState<Set<Formato>>(new Set(["csv"]));
  const [pasta, setPasta] = useState("");
  // Padrão do CSV: o que abre direto no Excel em português.
  const [separador, setSeparador] = useState<Separador>(";");
  const [virgulaDecimal, setVirgulaDecimal] = useState(true);
  const [neutralizar, setNeutralizar] = useState(false);
  const [calendario, setCalendario] = useState(false);
  const { dados: disponiveis } = useCarregar(
    (signal) => chamar(api.GET("/api/export-formats", { signal })),
    [],
  );
  // Enquanto a lista não chega, nada fica desabilitado: a API recusa o que faltar.
  const instalar = (f: Formato) =>
    disponiveis?.find((d) => d.format === f && !d.available)?.install ?? null;
  const [estado, setEstado] = useState<
    | { tipo: "editando" }
    | { tipo: "exportando" }
    | { tipo: "existe"; arquivos: string[] }
    | { tipo: "erro"; erro: unknown }
    | { tipo: "pronto"; resultado: Exportacao }
  >({ tipo: "editando" });

  async function exportar(overwrite: boolean) {
    setEstado({ tipo: "exportando" });
    try {
      const resultado = await chamar(
        api.POST("/api/projects/{project_id}/exports", {
          params: { path: { project_id: projeto } },
          body: {
            formats: FORMATOS.filter((f) => formatos.has(f) && !instalar(f)),
            output_dir: pasta.trim() || null,
            overwrite,
            csv_separator: separador,
            decimal_comma: virgulaDecimal,
            neutralize_formulas: neutralizar,
            pbip_calendar: calendario,
          },
        }),
      );
      setEstado({ tipo: "pronto", resultado });
    } catch (e) {
      if (e instanceof ErroApi && e.status === 409 && e.existing)
        setEstado({ tipo: "existe", arquivos: e.existing });
      else setEstado({ tipo: "erro", erro: e });
    }
  }

  const alternar = (f: Formato) =>
    setFormatos((s) => {
      const n = new Set(s);
      if (n.has(f)) n.delete(f);
      else n.add(f);
      return n;
    });

  const ocupado = estado.tipo === "exportando";
  const formulas =
    estado.tipo === "pronto" && !estado.resultado.neutralized
      ? (estado.resultado.formula_cells ?? 0)
      : 0;

  return (
    <div className="dialogo-fundo">
      <form
        className="dialogo"
        role="dialog"
        aria-modal="true"
        aria-label={T.exportar.titulo}
        onSubmit={(e) => {
          e.preventDefault();
          exportar(false);
        }}
      >
        <h2>{T.exportar.titulo}</h2>
        <fieldset disabled={ocupado}>
          <legend>{T.exportar.formatos}</legend>
          {FORMATOS.map((f) => {
            const comando = instalar(f);
            return (
              <div key={f}>
                <label className="opcao">
                  <input
                    type="checkbox"
                    checked={formatos.has(f) && !comando}
                    disabled={comando !== null}
                    onChange={() => alternar(f)}
                  />
                  {T.exportar.nomes[f]}
                </label>
                {comando && (
                  <small className="dica">
                    {T.exportar.instalar} <code>{comando}</code>
                  </small>
                )}
              </div>
            );
          })}
        </fieldset>

        {formatos.has("csv") && (
          <fieldset disabled={ocupado}>
            <legend>{T.exportar.opcoesCsv}</legend>
            <label className="opcao">
              {T.exportar.separador}
              <select value={separador} onChange={(e) => setSeparador(e.target.value as Separador)}>
                {SEPARADORES.map((s) => (
                  <option key={s} value={s}>
                    {T.exportar.separadores[s]}
                  </option>
                ))}
              </select>
            </label>
            <label className="opcao">
              <input
                type="checkbox"
                checked={virgulaDecimal}
                onChange={(e) => setVirgulaDecimal(e.target.checked)}
              />
              {T.exportar.virgulaDecimal}
            </label>
            <label className="opcao">
              <input
                type="checkbox"
                checked={neutralizar}
                onChange={(e) => setNeutralizar(e.target.checked)}
              />
              {T.exportar.neutralizar}
            </label>
            <small className="dica">{T.exportar.neutralizarDica}</small>
          </fieldset>
        )}

        {formatos.has("pbip") && (
          <fieldset disabled={ocupado}>
            <legend>{T.exportar.opcoesPbip}</legend>
            <label className="opcao">
              <input
                type="checkbox"
                checked={calendario}
                onChange={(e) => setCalendario(e.target.checked)}
              />
              {T.exportar.calendario}
            </label>
            <small className="dica">{T.exportar.calendarioDica}</small>
          </fieldset>
        )}

        <label className="campo">
          <span className="rotulo">{T.exportar.pasta}</span>
          <input
            type="text"
            value={pasta}
            onChange={(e) => setPasta(e.target.value)}
            disabled={ocupado}
          />
          <small className="dica">{T.exportar.pastaDica}</small>
        </label>

        {ocupado && <Carregando texto={T.exportar.exportando} />}
        {estado.tipo === "erro" && <CaixaErro erro={estado.erro} />}
        {estado.tipo === "existe" && (
          <div className="estado aviso" role="alert">
            <strong>{T.exportar.existe}</strong>
            <ul>
              {estado.arquivos.map((a) => (
                <li key={a}>
                  <code>{a}</code>
                </li>
              ))}
            </ul>
            <button type="button" className="perigo" onClick={() => exportar(true)}>
              {T.exportar.sobrescrever}
            </button>
          </div>
        )}
        {estado.tipo === "pronto" && (
          <div className="estado sucesso" role="status">
            <strong>{T.exportar.pronto(estado.resultado.rows)}</strong>
            <ul>
              {estado.resultado.files.map((a) => (
                <li key={a}>
                  <code>{a}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {formulas > 0 && (
          <div className="estado aviso" role="alert">
            {T.exportar.avisoFormulas(formulas)}
          </div>
        )}
        {formatos.size === 0 && <p className="dica">{T.exportar.nenhumFormato}</p>}

        <div className="acoes">
          <button type="button" onClick={aoFechar}>
            {T.comum.fechar}
          </button>
          <button type="submit" className="primario" disabled={formatos.size === 0 || ocupado}>
            {T.exportar.exportar}
          </button>
        </div>
      </form>
    </div>
  );
}

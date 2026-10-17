// Tela de exportação (F1.H12): formatos, pasta de saída e confirmação
// quando já existem arquivos com os mesmos nomes (F0.A6: falha por padrão).

import { useState } from "react";
import { api, chamar, ErroApi, type Exportacao } from "../api/cliente";
import { T } from "../textos";
import { CaixaErro, Carregando } from "./Estado";

type Formato = "csv" | "parquet" | "xlsx" | "powerquery" | "python";
const DISPONIVEIS: Formato[] = ["csv", "parquet", "powerquery", "python"];
const EM_BREVE: Formato[] = ["xlsx"];

export function Exportar({ projeto, aoFechar }: { projeto: string; aoFechar: () => void }) {
  const [formatos, setFormatos] = useState<Set<Formato>>(new Set(["csv"]));
  const [pasta, setPasta] = useState("");
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
          body: { formats: [...formatos], output_dir: pasta.trim() || null, overwrite },
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
        <fieldset disabled={estado.tipo === "exportando"}>
          <legend>{T.exportar.formatos}</legend>
          {DISPONIVEIS.map((f) => (
            <label key={f} className="opcao">
              <input type="checkbox" checked={formatos.has(f)} onChange={() => alternar(f)} />
              {T.exportar.nomes[f]}
            </label>
          ))}
          {EM_BREVE.map((f) => (
            <label key={f} className="opcao desabilitada">
              <input type="checkbox" disabled />
              {T.exportar.nomes[f]} <em className="etiqueta">{T.exportar.emBreve}</em>
            </label>
          ))}
        </fieldset>
        <label className="campo">
          <span className="rotulo">{T.exportar.pasta}</span>
          <input
            type="text"
            value={pasta}
            onChange={(e) => setPasta(e.target.value)}
            disabled={estado.tipo === "exportando"}
          />
          <small className="dica">{T.exportar.pastaDica}</small>
        </label>

        {estado.tipo === "exportando" && <Carregando texto={T.exportar.exportando} />}
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
        {formatos.size === 0 && <p className="dica">{T.exportar.nenhumFormato}</p>}

        <div className="acoes">
          <button type="button" onClick={aoFechar}>
            {T.comum.fechar}
          </button>
          <button
            type="submit"
            className="primario"
            disabled={formatos.size === 0 || estado.tipo === "exportando"}
          >
            {T.exportar.exportar}
          </button>
        </div>
      </form>
    </div>
  );
}

// Aba de origem da receita e o padrão para o arquivo do mês seguinte (F2.F4):
// 'DEZEMBRO_2025' hoje, 'JANEIRO_2026' no próximo. A importação já propõe o
// padrão; aqui ele aparece e pode ser trocado ou desligado.

import { useState } from "react";
import type { Receita } from "../api/cliente";
import { T } from "../textos";

type Fonte = { sheet?: string | null; match?: { sheet_name_regex?: string | null } | null };

export function AbaDaFonte({
  receita,
  salvar,
}: {
  receita: Receita;
  salvar: (nova: Receita) => Promise<void>;
}) {
  const fonte = receita.source as Fonte;
  const atual = fonte.match?.sheet_name_regex ?? "";
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(atual);
  const [erro, setErro] = useState<string | null>(null);
  if (!fonte.sheet) return null;

  async function gravar(padrao: string) {
    const limpo = padrao.trim();
    try {
      await salvar({
        ...receita,
        source: { ...receita.source, match: limpo ? { sheet_name_regex: limpo } : null },
      });
      setEditando(false);
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="aba-fonte">
      <span>
        {T.aba.rotulo} <strong>{fonte.sheet}</strong>
      </span>
      {!editando && (
        <>
          <small>
            {atual ? (
              <>
                {T.aba.tambem} <code>{atual}</code>
              </>
            ) : (
              T.aba.soEsta
            )}
          </small>
          <button
            type="button"
            onClick={() => {
              setValor(atual);
              setEditando(true);
            }}
          >
            {T.aba.editar}
          </button>
        </>
      )}
      {editando && (
        <form
          className="aba-fonte-form"
          onSubmit={(e) => {
            e.preventDefault();
            void gravar(valor);
          }}
        >
          <label className="campo">
            <span className="rotulo">{T.aba.padrao}</span>
            <input
              value={valor}
              onChange={(e) => setValor(e.target.value)}
              placeholder={T.aba.exemplo}
            />
          </label>
          <small className="dica">{T.aba.dica}</small>
          {erro && <small className="erro-texto">{erro}</small>}
          <div className="acoes">
            <button type="button" onClick={() => setEditando(false)}>
              {T.comum.cancelar}
            </button>
            <button type="submit" className="primario">
              {T.comum.salvar}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

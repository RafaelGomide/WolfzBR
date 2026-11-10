// Aba de origem da receita e o padrão para o arquivo do mês seguinte (F2.F4):
// 'DEZEMBRO_2025' hoje, 'JANEIRO_2026' no próximo. A importação já propõe o
// padrão; aqui ele aparece e pode ser trocado ou desligado.
//
// Com várias abas juntas (F3, ux.md §2.2 e §2.3), o bloco vira "Abas": quais
// abas entram, a regra para os próximos arquivos, a coluna de origem e o
// aviso persistente de abas com colunas diferentes. Quem escolhe as abas é a
// regra gravada na receita (D8); as abas e as diferenças vêm do servidor.

import { useMemo, useState } from "react";
import type { Aba, Divergencia, Receita, RegraAbas } from "../api/cliente";
import { T } from "../textos";
import type { Contagem } from "../util/reconciliacao";
import { ORIGEM_PADRAO, useRegraAbas } from "../util/regraAbas";
import { CaixaErro } from "./Estado";

type Juntar = { sheets_regex?: string | null; origin_col?: string | null };
type Fonte = {
  sheet?: string | null;
  match?: { sheet_name_regex?: string | null } | null;
  combine_sheets?: Juntar | null;
};

const MAX_ABAS = 5;
const MAX_COLUNAS = 3;

/** O que a regra escolhe nos próximos arquivos e, se souber, neste. */
export function RegraTexto({ regra }: { regra: Pick<RegraAbas, "sheets_regex" | "matches"> }) {
  return (
    <>
      <p>
        {regra.sheets_regex == null ? (
          T.aba.proximasTodas
        ) : (
          <>
            {T.aba.proximasPadrao} <code>{regra.sheets_regex}</code>
          </>
        )}
      </p>
      {regra.matches.length > 0 && <p>{T.abas.regraEscolhe(regra.matches)}</p>}
    </>
  );
}

function colunas(lista: string[]): string {
  return lista.length > MAX_COLUNAS
    ? T.aba.maisColunas(lista.slice(0, MAX_COLUNAS), lista.length - MAX_COLUNAS)
    : lista.join(", ");
}

/** Linhas de uma aba: primeiro os nomes quase iguais ("Viraram duas
 * colunas"), depois o que falta e o que sobra. Os nomes quase iguais também
 * vêm em ``falta``/``a_mais`` (desta e das outras abas): não se repetem. */
function linhasDaAba(d: Divergencia, ja: Set<string>): string[] {
  const quase = d.quase_iguais.map((q) => ({ nesta: q.nesta, nasOutras: q.nas_outras }));
  const falta = d.falta.filter((c) => !ja.has(c));
  const aMais = d.a_mais.filter((c) => !ja.has(c));
  const linhas = quase.map((q) => T.aba.quaseIgual(d.parte, q.nesta, q.nasOutras));
  if (falta.length && aMais.length)
    linhas.push(T.aba.faltaEAMais(d.parte, colunas(falta), colunas(aMais)));
  else if (falta.length) linhas.push(T.aba.falta(d.parte, colunas(falta)));
  else if (aMais.length) linhas.push(T.aba.aMais(d.parte, colunas(aMais)));
  return linhas;
}

/** Aviso de abas com colunas diferentes (U6): sem "Fechar", some quando as
 * abas passam a ter as mesmas colunas. */
function AvisoDivergencias({ divergencias }: { divergencias: Divergencia[] }) {
  if (divergencias.length === 0) return null;
  const ja = new Set(divergencias.flatMap((d) => d.quase_iguais.flatMap((q) => Object.values(q))));
  const primeiras = divergencias.slice(0, MAX_ABAS);
  const resto = divergencias.slice(MAX_ABAS);
  const lista = (ds: Divergencia[]) => (
    <ul>
      {ds.flatMap((d) => linhasDaAba(d, ja).map((l) => <li key={`${d.parte}|${l}`}>{l}</li>))}
    </ul>
  );
  return (
    <div className="aviso-abas aviso">
      <p>
        <span className="icone" aria-hidden="true">
          ⚠{" "}
        </span>
        <strong>{T.reconciliacao.atencao}</strong> {T.aba.diferentes}
      </p>
      {lista(primeiras)}
      {resto.length > 0 && (
        <details>
          <summary>
            {T.aba.maisAbas(resto.length)} · {T.aba.verTodas}
          </summary>
          {lista(resto)}
        </details>
      )}
      <p>{T.aba.ficaVazia}</p>
    </div>
  );
}

function EditarAbas({
  receita,
  juntar,
  abasDoArquivo,
  marcadasAgora,
  salvar,
  fechar,
}: {
  receita: Receita;
  juntar: Juntar;
  abasDoArquivo: Aba[];
  marcadasAgora: string[];
  salvar: (nova: Receita) => Promise<void>;
  fechar: () => void;
}) {
  const fonte = receita.source as Fonte;
  const visiveis = useMemo(
    () => abasDoArquivo.filter((a) => !a.hidden).map((a) => a.name),
    [abasDoArquivo],
  );
  const [marcadas, setMarcadas] = useState(() => (marcadasAgora.length ? marcadasAgora : visiveis));
  const ordenadas = useMemo(
    () => visiveis.filter((n) => marcadas.includes(n)),
    [visiveis, marcadas],
  );
  const [usarOrigem, setUsarOrigem] = useState(juntar.origin_col !== null);
  const [origem, setOrigem] = useState(juntar.origin_col ?? ORIGEM_PADRAO);
  const [erro, setErro] = useState<unknown>(null);
  const {
    regra,
    erro: erroRegra,
    carregando,
  } = useRegraAbas(ordenadas, visiveis, fonte.sheet ?? null);
  const pronto = ordenadas.length >= 2 && !!regra && !carregando;

  async function gravar() {
    if (!regra) return;
    try {
      await salvar({
        ...receita,
        source: {
          ...receita.source,
          combine_sheets: {
            ...juntar,
            sheets_regex: regra.sheets_regex,
            origin_col: usarOrigem ? origem.trim() || ORIGEM_PADRAO : null,
          },
        },
      });
      fechar();
    } catch (e) {
      setErro(e);
    }
  }

  return (
    <form
      className="aba-fonte-form"
      aria-label={T.aba.escolherAbas}
      onSubmit={(e) => {
        e.preventDefault();
        void gravar();
      }}
    >
      <fieldset>
        <legend>{T.aba.escolherAbas}</legend>
        <ul className="lista-abas">
          {abasDoArquivo.map((a) => (
            <li key={a.name}>
              <label>
                <input
                  type="checkbox"
                  checked={!a.hidden && marcadas.includes(a.name)}
                  disabled={a.hidden}
                  onChange={(e) =>
                    setMarcadas((m) =>
                      e.target.checked ? [...m, a.name] : m.filter((x) => x !== a.name),
                    )
                  }
                />
                <span>{a.name}</span>
                {a.hidden && <em className="etiqueta">{T.abas.naoEntra}</em>}
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <div aria-live="polite">
        {ordenadas.length < 2 && <p className="dica">{T.abas.minimo}</p>}
        {ordenadas.length >= 2 && carregando && <p className="dica">{T.abas.calculandoRegra}</p>}
        {ordenadas.length >= 2 && regra && !carregando && <RegraTexto regra={regra} />}
      </div>
      {erroRegra != null && <CaixaErro erro={erroRegra} />}
      <label className="campo-check">
        <input
          type="checkbox"
          checked={usarOrigem}
          onChange={(e) => setUsarOrigem(e.target.checked)}
        />
        {T.aba.usarColunaOrigem}
      </label>
      {usarOrigem && (
        <label className="campo">
          <span className="rotulo">{T.aba.nomeColunaOrigem}</span>
          <input value={origem} onChange={(e) => setOrigem(e.target.value)} />
        </label>
      )}
      {erro != null && <CaixaErro erro={erro} />}
      <div className="acoes">
        <button type="button" onClick={fechar}>
          {T.comum.cancelar}
        </button>
        <button type="submit" className="primario" disabled={!pronto}>
          {T.comum.salvar}
        </button>
      </div>
    </form>
  );
}

function AbasJuntas({
  receita,
  juntar,
  abasDoArquivo,
  contagem,
  salvar,
}: {
  receita: Receita;
  juntar: Juntar;
  abasDoArquivo: Aba[];
  contagem: Contagem;
  salvar: (nova: Receita) => Promise<void>;
}) {
  const [editando, setEditando] = useState(false);
  // Enquanto recalcula, vale a contagem anterior: as abas não piscam.
  const dados = contagem.tipo === "pronta" ? contagem.dados : contagem.anterior;
  const nomes = dados?.partes.map((p) => p.origem) ?? [];
  // As ocultas que o servidor apontou; sem elas (o projeto não guarda as
  // ocultas), as que a lista de abas do arquivo marca como ocultas.
  const ocultas = dados?.abas_ocultas.length
    ? dados.abas_ocultas
    : abasDoArquivo.filter((a) => a.hidden).map((a) => a.name);
  return (
    <div className="aba-fonte abas-juntas">
      <span>
        {T.aba.rotuloVarias}{" "}
        {nomes.length > 0 && <strong>{T.aba.listaVarias(nomes, nomes.length)}</strong>}
        {" · "}
        {juntar.origin_col === null
          ? T.aba.semColunaOrigem
          : T.aba.colunaOrigem(juntar.origin_col ?? ORIGEM_PADRAO)}
      </span>
      {!editando && (
        <>
          <small>
            {juntar.sheets_regex == null ? (
              T.aba.proximasTodas
            ) : (
              <>
                {T.aba.proximasPadrao} <code>{juntar.sheets_regex}</code>
              </>
            )}
          </small>
          <button type="button" onClick={() => setEditando(true)}>
            {T.aba.editar}
          </button>
        </>
      )}
      {ocultas.length > 0 && <small className="dica">{T.aba.ocultas(ocultas)}</small>}
      {contagem.tipo !== "erro" && <AvisoDivergencias divergencias={dados?.divergencias ?? []} />}
      {editando && (
        <EditarAbas
          receita={receita}
          juntar={juntar}
          abasDoArquivo={abasDoArquivo}
          marcadasAgora={nomes}
          salvar={salvar}
          fechar={() => setEditando(false)}
        />
      )}
    </div>
  );
}

export function AbaDaFonte({
  receita,
  abasDoArquivo,
  contagem,
  salvar,
}: {
  receita: Receita;
  abasDoArquivo: Aba[];
  contagem: Contagem;
  salvar: (nova: Receita) => Promise<void>;
}) {
  const fonte = receita.source as Fonte;
  const atual = fonte.match?.sheet_name_regex ?? "";
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(atual);
  const [erro, setErro] = useState<string | null>(null);
  if (fonte.combine_sheets)
    return (
      <AbasJuntas
        receita={receita}
        juntar={fonte.combine_sheets}
        abasDoArquivo={abasDoArquivo}
        contagem={contagem}
        salvar={salvar}
      />
    );
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

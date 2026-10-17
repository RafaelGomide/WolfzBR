// Formulário de um passo, montado a partir do JSON Schema da operação
// (GET /ops, F1.H9). Formulários próprios e simples: o catálogo só usa
// texto, número, sim/não, enum, lista, mapa e alternativas (anyOf).

import { useId, useState } from "react";
import type { Operacao, Passo } from "../api/cliente";
import { T } from "../textos";
import { nomeOp } from "../util/receita";
import {
  FIXOS,
  padrao,
  resolver,
  tipoDoSchema,
  tipoDoValor,
  type Defs,
  type Schema,
} from "../util/schema";

// Parâmetros cujo valor é nome de coluna: o campo sugere as colunas da tabela.
const DE_COLUNA = new Set(["cols", "col", "by", "index", "mapping", "types"]);

function Lista({
  valor,
  item,
  defs,
  colunas,
  mudar,
  rotulo,
}: {
  valor: unknown[];
  item: Schema;
  defs: Defs;
  colunas?: string[];
  mudar: (v: unknown[]) => void;
  rotulo: string;
}) {
  const [novo, setNovo] = useState("");
  const lista = useId();
  const s = resolver(item, defs);
  if (s.type === "string" && !s.enum) {
    const adicionar = () => {
      const t = novo.trim();
      if (t && !valor.includes(t)) mudar([...valor, t]);
      setNovo("");
    };
    const sugestoes = (colunas ?? []).filter((c) => !valor.includes(c));
    return (
      <div className="lista-campo">
        <ul className="fichas">
          {valor.length === 0 && <li className="dica">{T.form.nenhumItem}</li>}
          {valor.map((v, i) => (
            <li key={`${String(v)}-${i}`} className="ficha">
              {String(v)}
              <button
                type="button"
                aria-label={`${T.form.removerItem} ${String(v)}`}
                onClick={() => mudar(valor.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <div className="linha">
          <input
            aria-label={rotulo}
            list={sugestoes.length ? lista : undefined}
            value={novo}
            onChange={(e) => setNovo(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                adicionar();
              }
            }}
          />
          <button type="button" onClick={adicionar}>
            {T.form.adicionarItem}
          </button>
          {sugestoes.length > 0 && (
            <datalist id={lista}>
              {sugestoes.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          )}
        </div>
        {(sugestoes.length > 1 || valor.length > 0) && (
          <div className="linha">
            {sugestoes.length > 1 && (
              <button type="button" onClick={() => mudar([...valor, ...sugestoes])}>
                {T.form.adicionarTodas(sugestoes.length)}
              </button>
            )}
            {valor.length > 0 && (
              <button type="button" onClick={() => mudar([])}>
                {T.form.limpar}
              </button>
            )}
          </div>
        )}
        {sugestoes.length > 0 && sugestoes.length <= 40 && (
          <div className="sugestoes">
            {sugestoes.map((c) => (
              <button
                key={c}
                type="button"
                className="sugestao"
                onClick={() => mudar([...valor, c])}
              >
                + {c}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="lista-campo">
      {valor.map((v, i) => (
        <div key={i} className="linha">
          <Campo
            schema={item}
            defs={defs}
            valor={v}
            rotulo={`${rotulo} ${i + 1}`}
            mudar={(nv) => mudar(valor.map((x, j) => (j === i ? nv : x)))}
          />
          <button type="button" onClick={() => mudar(valor.filter((_, j) => j !== i))}>
            {T.form.removerItem}
          </button>
        </div>
      ))}
      <button type="button" onClick={() => mudar([...valor, padrao(item, defs)])}>
        {T.form.adicionarItem}
      </button>
    </div>
  );
}

function Mapa({
  valor,
  item,
  defs,
  colunas,
  mudar,
  rotulo,
}: {
  valor: Record<string, unknown>;
  item: Schema;
  defs: Defs;
  colunas?: string[];
  mudar: (v: Record<string, unknown>) => void;
  rotulo: string;
}) {
  const lista = useId();
  const pares = Object.entries(valor);
  const [nova, setNova] = useState("");
  const adicionar = () => {
    const k = nova.trim();
    if (k && !(k in valor)) mudar({ ...valor, [k]: padrao(item, defs) });
    setNova("");
  };
  return (
    <div className="mapa-campo">
      {colunas && (
        <datalist id={lista}>
          {colunas.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      )}
      {pares.map(([k, v]) => (
        <div key={k} className="linha">
          <input aria-label={`${rotulo}: ${T.form.chave}`} value={k} readOnly />
          <span aria-hidden="true">→</span>
          <Campo
            schema={item}
            defs={defs}
            valor={v}
            rotulo={`${rotulo}: ${T.form.valor} ${k}`}
            mudar={(nv) => mudar({ ...valor, [k]: nv })}
          />
          <button
            type="button"
            aria-label={`${T.form.removerItem} ${k}`}
            onClick={() => mudar(Object.fromEntries(pares.filter(([x]) => x !== k)))}
          >
            ×
          </button>
        </div>
      ))}
      <div className="linha">
        <input
          aria-label={`${rotulo}: ${T.form.chave}`}
          list={lista}
          value={nova}
          onChange={(e) => setNova(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              adicionar();
            }
          }}
        />
        <button type="button" onClick={adicionar}>
          {T.form.adicionarItem}
        </button>
      </div>
    </div>
  );
}

function Campo({
  schema,
  defs,
  valor,
  mudar,
  rotulo,
  colunas,
  anulavel = false,
}: {
  schema: Schema;
  defs: Defs;
  valor: unknown;
  mudar: (v: unknown) => void;
  rotulo: string;
  colunas?: string[];
  anulavel?: boolean;
}) {
  const lista = useId();
  const s = resolver(schema, defs);

  if (s.anyOf) {
    const alts = s.anyOf.map((a) => resolver(a, defs)).filter((a) => a.type !== "null");
    const nulo = s.anyOf.length !== alts.length;
    if (alts.length === 1)
      return (
        <Campo
          schema={alts[0]}
          defs={defs}
          valor={valor}
          mudar={mudar}
          rotulo={rotulo}
          colunas={colunas}
          anulavel={nulo}
        />
      );
    const atual = Math.max(
      0,
      alts.findIndex((a) => tipoDoSchema(a) === tipoDoValor(valor)),
    );
    return (
      <div className="alternativas">
        <select
          aria-label={`${rotulo}: ${T.form.tipo}`}
          value={atual}
          onChange={(e) => mudar(padrao(alts[Number(e.target.value)], defs))}
        >
          {alts.map((a, i) => (
            <option key={i} value={i}>
              {T.form.alternativas[tipoDoSchema(a)] ?? tipoDoSchema(a)}
            </option>
          ))}
        </select>
        <Campo
          schema={alts[atual]}
          defs={defs}
          valor={valor}
          mudar={mudar}
          rotulo={rotulo}
          colunas={colunas}
        />
      </div>
    );
  }

  if (s.const !== undefined)
    return (
      <input
        type="checkbox"
        aria-label={rotulo}
        checked={valor === s.const}
        onChange={(e) => mudar(e.target.checked ? s.const : null)}
      />
    );

  if (s.enum)
    return (
      <select
        aria-label={rotulo}
        value={valor == null ? "" : String(valor)}
        onChange={(e) =>
          mudar(e.target.value === "" ? null : s.enum!.find((x) => String(x) === e.target.value))
        }
      >
        {(anulavel || valor == null) && <option value="">{T.form.vazio}</option>}
        {s.enum.map((x) => (
          <option key={String(x)} value={String(x)}>
            {String(x)}
          </option>
        ))}
      </select>
    );

  switch (s.type) {
    case "boolean":
      return (
        <input
          type="checkbox"
          aria-label={rotulo}
          checked={valor === true}
          onChange={(e) => mudar(e.target.checked)}
        />
      );
    case "integer":
    case "number":
      return (
        <input
          type="number"
          aria-label={rotulo}
          min={s.minimum}
          max={s.maximum}
          step={s.type === "integer" ? 1 : "any"}
          value={valor == null ? "" : String(valor)}
          onChange={(e) =>
            mudar(e.target.value === "" ? (anulavel ? null : 0) : Number(e.target.value))
          }
        />
      );
    case "array":
      return (
        <Lista
          valor={Array.isArray(valor) ? valor : []}
          item={s.items ?? {}}
          defs={defs}
          colunas={colunas}
          mudar={mudar}
          rotulo={rotulo}
        />
      );
    case "object":
      return (
        <Mapa
          valor={valor && typeof valor === "object" ? (valor as Record<string, unknown>) : {}}
          item={typeof s.additionalProperties === "object" ? s.additionalProperties : {}}
          defs={defs}
          colunas={colunas}
          mudar={mudar}
          rotulo={rotulo}
        />
      );
    default:
      return (
        <>
          <input
            type="text"
            aria-label={rotulo}
            value={valor == null ? "" : String(valor)}
            list={colunas?.length ? lista : undefined}
            onChange={(e) => mudar(e.target.value === "" && anulavel ? null : e.target.value)}
          />
          {colunas && colunas.length > 0 && (
            <datalist id={lista}>
              {colunas.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          )}
        </>
      );
  }
}

export function FormPasso({
  operacao,
  passo,
  colunas,
  erros,
  titulo,
  aoAplicar,
  aoCancelar,
}: {
  operacao: Operacao;
  passo: Passo;
  colunas: string[];
  erros?: string[];
  titulo: string;
  aoAplicar: (p: Passo) => void;
  aoCancelar: () => void;
}) {
  const [rascunho, setRascunho] = useState<Passo>(passo);
  const schema = operacao.schema as {
    properties?: Record<string, Schema>;
    required?: string[];
    $defs?: Defs;
  };
  const defs = schema.$defs ?? {};
  const obrigatorios = new Set(schema.required ?? []);

  function aplicar() {
    const limpo: Passo = { id: rascunho.id, op: rascunho.op };
    for (const [k, v] of Object.entries(rascunho)) if (v !== null && v !== undefined) limpo[k] = v;
    aoAplicar(limpo);
  }

  return (
    <form
      className="form-passo"
      aria-label={titulo}
      onSubmit={(e) => {
        e.preventDefault();
        aplicar();
      }}
    >
      <h3>
        {titulo}: {nomeOp(operacao.op)}
      </h3>
      {operacao.doc && <p className="dica">{operacao.doc}</p>}
      {Object.entries(schema.properties ?? {})
        .filter(([k]) => !FIXOS.has(k))
        .map(([k, s]) => {
          const rotulo = T.params[k] ?? resolver(s, defs).title ?? k;
          return (
            <div
              key={k}
              className={`campo${resolver(s, defs).type === "boolean" ? " booleano" : ""}`}
            >
              <span className="rotulo">
                {rotulo}
                {obrigatorios.has(k) && <abbr title="obrigatório"> *</abbr>}
              </span>
              <Campo
                schema={s}
                defs={defs}
                valor={rascunho[k]}
                rotulo={rotulo}
                colunas={DE_COLUNA.has(k) ? colunas : undefined}
                mudar={(v) => setRascunho((r) => ({ ...r, [k]: v }))}
              />
            </div>
          );
        })}
      {erros && erros.length > 0 && (
        <div className="estado erro" role="alert">
          <strong>{T.form.erros}</strong>
          <ul>
            {erros.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="acoes">
        <button type="button" onClick={aoCancelar}>
          {T.comum.cancelar}
        </button>
        <button type="submit" className="primario">
          {T.comum.aplicar}
        </button>
      </div>
    </form>
  );
}

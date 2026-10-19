// Tela do projeto: receita à esquerda, grades no centro, perfil à direita.
// Cada edição salva a receita inteira (PUT com If-Match, gravação atômica no
// servidor); os salvamentos vão em fila para cada um usar a ETag do
// anterior.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  chamar,
  ErroApi,
  type Deteccao,
  type Operacao,
  type Passo,
  type Projeto,
  type Receita,
} from "../api/cliente";
import { CaixaErro, Carregando } from "../componentes/Estado";
import { Exportar } from "../componentes/Exportar";
import { GradeDados } from "../componentes/GradeDados";
import { PainelPerfil } from "../componentes/PainelPerfil";
import { PainelReceita } from "../componentes/PainelReceita";
import { VisaoBruta } from "../componentes/VisaoBruta";
import { T } from "../textos";
import { novoId, passoAnterior } from "../util/receita";
import { irPara } from "../util/rota";
import { useCarregar } from "../util/useCarregar";

type Salvamento =
  { tipo: "ocioso" | "salvando" | "salvo" | "conflito" } | { tipo: "erro"; erro: unknown };

function useColunas(projeto: string, passo: string | undefined, versao: string): string[] {
  const { dados } = useCarregar(
    (signal) =>
      chamar(
        api.GET("/api/projects/{project_id}/preview", {
          params: { path: { project_id: projeto }, query: { step: passo, limit: 1 } },
          signal,
        }),
      ),
    [projeto, passo, versao],
  );
  return dados?.columns.map((c) => c.name) ?? [];
}

/** ``enabled`` só vai para o servidor quando é ``false``. */
function limpar(p: Passo): Passo {
  const { enabled, ...resto } = p;
  return enabled === false ? { ...resto, enabled } : resto;
}

function Editor({
  projeto,
  ops,
  deteccao,
}: {
  projeto: Projeto;
  ops: Operacao[];
  deteccao: Deteccao | null;
}) {
  const id = projeto.id;
  const [receita, setReceita] = useState(projeto.recipe as Receita);
  const [versao, setVersao] = useState(projeto.etag);
  const etag = useRef(projeto.etag);
  const salva = useRef(projeto.recipe as Receita);
  const fila = useRef<Promise<void>>(Promise.resolve());
  const [salvamento, setSalvamento] = useState<Salvamento>({ tipo: "ocioso" });
  const [aba, setAba] = useState<"original" | "antesdepois">("original");
  const [sel, setSel] = useState<string | null>(null);
  const [erroPasso, setErroPasso] = useState<ErroApi | null>(null);
  const [perfil, setPerfil] = useState<{ coluna: string; passo?: string } | null>(null);
  const [exportando, setExportando] = useState(false);

  const salvar = useCallback(
    (nova: Receita): Promise<void> => {
      const limpa = { ...nova, steps: nova.steps.map(limpar) };
      setReceita(limpa);
      setSalvamento({ tipo: "salvando" });
      const vez = fila.current
        .catch(() => undefined)
        .then(async () => {
          try {
            const r = await chamar(
              api.PUT("/api/projects/{project_id}/recipe", {
                params: { path: { project_id: id }, header: { "if-match": etag.current } },
                body: limpa,
              }),
            );
            etag.current = r.etag;
            salva.current = r.recipe as Receita;
            setReceita(r.recipe as Receita);
            setVersao(r.etag);
            setSalvamento({ tipo: "salvo" });
          } catch (e) {
            setReceita(salva.current);
            setSalvamento(
              e instanceof ErroApi && e.status === 409
                ? { tipo: "conflito" }
                : { tipo: "erro", erro: e },
            );
            throw e;
          }
        });
      fila.current = vez;
      return vez;
    },
    [id],
  );

  async function recarregarReceita() {
    const p = await chamar(
      api.GET("/api/projects/{project_id}", { params: { path: { project_id: id } } }),
    );
    etag.current = p.etag;
    salva.current = p.recipe as Receita;
    setReceita(p.recipe as Receita);
    setVersao(p.etag);
    setSalvamento({ tipo: "ocioso" });
  }

  // Confere a receita inteira a cada versão: um passo que falha fica
  // destacado mesmo que não seja o selecionado (F1.H10).
  useEffect(() => {
    const ctrl = new AbortController();
    chamar(
      api.GET("/api/projects/{project_id}/preview", {
        params: { path: { project_id: id }, query: { limit: 1 } },
        signal: ctrl.signal,
      }),
    ).then(
      () => setErroPasso(null),
      (e) => {
        if (e instanceof ErroApi) setErroPasso(e.passoComErro ? e : null);
      },
    );
    return () => ctrl.abort();
  }, [id, versao]);

  const existe = sel === "raw" || receita.steps.some((p) => p.id === sel);
  const atual = existe ? sel : null;
  const depois = atual ?? undefined;
  const antes =
    atual === null ? "raw" : atual === "raw" ? undefined : passoAnterior(receita, atual);

  function selecionar(passo: string | null) {
    setSel(passo);
    setAba("antesdepois");
  }

  function usarArea(inicio: string, fim: string) {
    const recorte = receita.steps.find((p) => p.op === "select_range");
    const steps = recorte
      ? receita.steps.map((p) => {
          if (p !== recorte) return p;
          const { end_detect: _descartado, ...resto } = p;
          void _descartado;
          return { ...resto, start: inicio, end: fim };
        })
      : [{ id: novoId(receita), op: "select_range", start: inicio, end: fim }, ...receita.steps];
    salvar({ ...receita, steps }).catch(() => undefined);
  }

  function usarTabela(passos: Record<string, unknown>[]) {
    const steps = passos.map((p, i) => ({ ...p, id: `s${i + 1}` }) as Passo);
    salvar({ ...receita, steps }).catch(() => undefined);
  }

  // Colunas antes e depois do passo selecionado, para os formulários. Vêm
  // do cache do preview (limit=1) e não dependem de a grade estar na tela.
  const colunasAntes = useColunas(id, antes ?? "raw", versao);
  const colunasDepois = useColunas(id, depois, versao);

  const aoErrar = (e: unknown) => {
    if (e instanceof ErroApi && e.passoComErro) setErroPasso(e);
  };

  return (
    <div className="projeto">
      <header className="topo">
        <button type="button" onClick={() => irPara(null)}>
          ← {T.comum.voltar}
        </button>
        <div className="titulo-projeto">
          <h1>{projeto.name}</h1>
          <small>
            {[
              projeto.source.sheet ? T.projeto.aba(projeto.source.sheet) : null,
              T.comum.linhas(projeto.raw.rows),
            ]
              .filter(Boolean)
              .join(" · ")}
          </small>
        </div>
        <span className="salvamento" role="status">
          {salvamento.tipo === "salvando" && T.projeto.salvando}
          {salvamento.tipo === "salvo" && T.projeto.salvo}
        </span>
        <button type="button" className="primario" onClick={() => setExportando(true)}>
          {T.projeto.exportar}
        </button>
      </header>

      {salvamento.tipo === "conflito" && (
        <CaixaErro erro={T.projeto.conflito}>
          <button type="button" onClick={() => recarregarReceita().catch(() => undefined)}>
            {T.projeto.recarregarReceita}
          </button>
        </CaixaErro>
      )}
      {salvamento.tipo === "erro" && (
        <CaixaErro erro={salvamento.erro} titulo={T.projeto.erroSalvar} />
      )}

      <div className="corpo">
        <PainelReceita
          projetoId={id}
          versao={versao}
          receita={receita}
          ops={ops}
          selecionado={atual}
          aoSelecionar={selecionar}
          erroPasso={erroPasso}
          colunasAntes={colunasAntes}
          colunasDepois={colunasDepois}
          salvar={salvar}
        />
        <section className="centro">
          <div className="abas" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={aba === "original"}
              onClick={() => setAba("original")}
            >
              {T.projeto.original}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={aba === "antesdepois"}
              onClick={() => setAba("antesdepois")}
            >
              {T.projeto.antesDepois}
            </button>
          </div>
          {aba === "original" ? (
            <VisaoBruta
              projeto={id}
              receita={receita}
              deteccao={deteccao}
              aoUsarArea={usarArea}
              aoUsarTabela={usarTabela}
            />
          ) : (
            <div className="antes-depois">
              {antes !== undefined && (
                <GradeDados
                  key={`antes-${antes}`}
                  projeto={id}
                  passo={antes}
                  versao={versao}
                  rotulo={
                    atual === null ? T.projeto.arquivoOriginal : T.projeto.antesDoPasso(atual)
                  }
                  numerarLinhas={antes === "raw"}
                  aoClicarCabecalho={(c) => setPerfil({ coluna: c, passo: antes })}
                  aoErrar={aoErrar}
                />
              )}
              <GradeDados
                key={`depois-${depois ?? "fim"}`}
                projeto={id}
                passo={depois}
                versao={versao}
                rotulo={
                  depois === undefined
                    ? T.projeto.receitaInteira
                    : depois === "raw"
                      ? T.projeto.arquivoOriginal
                      : T.projeto.depoisDoPasso(depois)
                }
                numerarLinhas={depois === "raw"}
                aoClicarCabecalho={(c) => setPerfil({ coluna: c, passo: depois })}
                aoErrar={aoErrar}
              />
            </div>
          )}
        </section>
        {perfil && (
          <PainelPerfil
            projeto={id}
            passo={perfil.passo}
            versao={versao}
            coluna={perfil.coluna}
            aoFechar={() => setPerfil(null)}
          />
        )}
      </div>
      {exportando && <Exportar projeto={id} aoFechar={() => setExportando(false)} />}
    </div>
  );
}

export function TelaProjeto({ id }: { id: string }) {
  const { dados, erro, recarregar } = useCarregar(
    (signal) =>
      Promise.all([
        chamar(
          api.GET("/api/projects/{project_id}", { params: { path: { project_id: id } }, signal }),
        ),
        chamar(api.GET("/api/ops", { signal })),
        chamar(
          api.GET("/api/projects/{project_id}/structure", {
            params: { path: { project_id: id } },
            signal,
          }),
        ),
      ]),
    [id],
  );

  if (erro != null)
    return (
      <div className="tela-centro">
        <CaixaErro erro={erro} tentarDeNovo={recarregar}>
          <button type="button" onClick={() => irPara(null)}>
            {T.comum.voltar}
          </button>
        </CaixaErro>
      </div>
    );
  if (!dados)
    return (
      <div className="tela-centro">
        <Carregando />
      </div>
    );
  const [projeto, ops, estrutura] = dados;
  return <Editor projeto={projeto} ops={ops} deteccao={estrutura.detection ?? null} />;
}

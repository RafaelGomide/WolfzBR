// Contagem de linhas por passo (F1, ux.md §1): contador na linha do passo,
// chamada de alerta no topo do painel e faixa de resumo no "Antes e depois".
// O alerta usa os quatro sinais do ux.md §4 (Atenção:, ⚠, borda, cor de
// aviso) e só aparece onde o servidor mandou ``alerta: true``.

import type { ContagemPasso, Reconciliacao } from "../api/cliente";
import { ErroApi } from "../api/cliente";
import { T } from "../textos";
import { nomeOp } from "../util/receita";
import { idFala, lerPasso, lidas, pct, perda, type Contagem } from "../util/reconciliacao";

const R = T.reconciliacao;
const MAX_LINHAS = 3;

/** Contador à direita do nome do passo. O texto visível fica escondido do
 * leitor de tela, que recebe a versão por extenso (via aria-describedby
 * no nome do passo). */
export function ContadorPasso({
  contagem,
  passo,
  ativo,
}: {
  contagem: Contagem;
  passo: string;
  ativo: boolean;
}) {
  if (!ativo) return null;
  if (contagem.tipo === "contando")
    return (
      <span className="contador contando" id={idFala(passo)}>
        {R.contando}
      </span>
    );
  if (contagem.tipo !== "pronta") return null;
  const c = contagem.dados.passos.find((x) => x.id === passo);
  const leitura = c && lerPasso(c);
  if (!leitura) return null;
  return (
    <>
      <span
        className={`contador${leitura.alerta ? " alerta" : ""}`}
        title={leitura.dica}
        aria-hidden="true"
      >
        {leitura.alerta && <span className="icone">⚠ </span>}
        {leitura.visivel}
      </span>
      <span className="so-leitor" id={idFala(passo)}>
        {leitura.fala}. {leitura.dica}
      </span>
    </>
  );
}

/** Linhas lidas ao lado do "Arquivo original", ou o aviso de que a
 * contagem falhou (nunca esconder em silêncio). */
export function ContagemOrigem({
  contagem,
  tentarDeNovo,
}: {
  contagem: Contagem;
  tentarDeNovo: () => void;
}) {
  if (contagem.tipo === "erro")
    return (
      <span className="contagem-falhou">
        <span
          title={contagem.erro instanceof ErroApi ? contagem.erro.detail : String(contagem.erro)}
        >
          {R.indisponivel}
        </span>
        <button type="button" onClick={tentarDeNovo}>
          {T.comum.tentarDeNovo}
        </button>
      </span>
    );
  const n = lidas(contagem);
  return <span className="contador">{n === undefined ? R.contando : R.lidas(n)}</span>;
}

function tipoDoAlerta(c: ContagemPasso): "perda" | "multiplicacao" | "outro" {
  if (c.motivo === "multiplicacao") return "multiplicacao";
  return perda(c) > 0 ? "perda" : "outro";
}

function cabecalhoChamada(alertas: ContagemPasso[]): string {
  const tipos = new Set(alertas.map(tipoDoAlerta));
  const n = alertas.length;
  if (tipos.size === 1 && tipos.has("perda")) return R.chamada(n);
  if (tipos.size === 1 && tipos.has("multiplicacao")) return R.chamadaMais(n);
  return R.chamadaGeral(n);
}

/** Chamada no topo do painel quando algum passo alerta (U4). Não tem
 * "Fechar" (D5): some quando o alerta deixa de existir. O ``role=status``
 * fica sempre na página e o texto dele só depende de quantos passos
 * alertam, para o leitor de tela só anunciar quando esse número muda. */
export function ChamadaAlerta({
  contagem,
  aoVerPasso,
}: {
  contagem: Contagem;
  aoVerPasso: (id: string) => void;
}) {
  // Enquanto recalcula, a chamada anterior fica: sumir e voltar a cada
  // edição faria o leitor de tela anunciar de novo.
  const dados = contagem.tipo === "pronta" ? contagem.dados : contagem.anterior;
  const alertas = contagem.tipo === "erro" ? [] : (dados?.passos.filter((c) => c.alerta) ?? []);
  const visiveis = alertas.slice(0, MAX_LINHAS);
  return (
    <div className={alertas.length ? "chamada-alerta aviso" : "chamada-alerta vazia"}>
      <p role="status" aria-live="polite">
        {alertas.length > 0 && (
          <>
            <span className="icone" aria-hidden="true">
              ⚠{" "}
            </span>
            <strong>{R.atencao}</strong> {cabecalhoChamada(alertas)}
          </>
        )}
      </p>
      {visiveis.length > 0 && (
        <ul>
          {visiveis.map((c) => (
            <li key={c.id}>
              <span>{R.chamadaPasso(c.id, nomeOp(c.op), lerPasso(c)?.visivel ?? "")}</span>
              {dados?.colunas_fora_da_area
                .filter((f) => f.passo === c.id)
                .map((f) => (
                  <span key={f.letra} className="coluna-fora">
                    {R.colunaFora(f.letra, f.cabecalho, f.celulas, f.area, f.passo)}
                  </span>
                ))}
              <button type="button" onClick={() => aoVerPasso(c.id)}>
                {R.verPasso}
              </button>
            </li>
          ))}
          {alertas.length > MAX_LINHAS && <li>{R.eMais(alertas.length - MAX_LINHAS)}</li>}
        </ul>
      )}
    </div>
  );
}

function Atencao({ texto }: { texto: string }) {
  return (
    <p>
      <span className="icone" aria-hidden="true">
        ⚠{" "}
      </span>
      <strong>{R.atencao}</strong> {texto}
    </p>
  );
}

/** Frase do alerta da receita inteira: perda total ou multiplicação. */
function AlertaTotal({
  dados,
  gravadas,
  aoVerPasso,
}: {
  dados: Reconciliacao;
  gravadas: number;
  aoVerPasso: (id: string) => void;
}) {
  const lidasN = dados.linhas_lidas;
  if (gravadas > lidasN) {
    const multiplicaram = dados.passos.filter((c) => c.fator != null || c.saida > c.entrada);
    const op = multiplicaram.at(-1)?.op;
    return (
      <>
        <Atencao texto={R.totalMultiplicou(Math.round(gravadas / Math.max(1, lidasN)))} />
        {op && (
          <p>
            {R.multiplicouEm(
              multiplicaram.map((c) => c.id),
              nomeOp(op),
            )}
          </p>
        )}
      </>
    );
  }
  const total = dados.passos.reduce((s, c) => s + perda(c), 0);
  const maior = dados.passos.reduce<ContagemPasso | undefined>(
    (m, c) => (perda(c) > (m ? perda(m) : 0) ? c : m),
    undefined,
  );
  return (
    <>
      <Atencao texto={R.totalPerda(pct(total, lidasN))} />
      {maior && (
        <p>
          {R.maiorParte(maior.id, nomeOp(maior.op))}{" "}
          <button type="button" onClick={() => aoVerPasso(maior.id)}>
            {R.verPasso}
          </button>
        </p>
      )}
    </>
  );
}

/** Faixa do "Antes e depois" (U3): linhas antes → depois do que está na
 * tela, sempre visível, com a perda total em destaque quando alerta. */
export function FaixaContagem({
  contagem,
  passo,
  aoVerPasso,
}: {
  contagem: Contagem;
  /** ``null`` = receita inteira; ``"raw"`` = só o arquivo original. */
  passo: string | null;
  aoVerPasso: (id: string) => void;
}) {
  const origem = T.projeto.arquivoOriginal;
  if (contagem.tipo === "erro")
    return (
      <div className="faixa-contagem">
        <p>{R.indisponivel}</p>
      </div>
    );
  const n = lidas(contagem);
  const lidasTexto = n === undefined ? `${origem} ${R.contando}` : R.faixaAntes(origem, n);
  if (passo === "raw")
    return (
      <div className="faixa-contagem">
        <p>{lidasTexto}</p>
      </div>
    );
  if (contagem.tipo === "contando") {
    const antes = passo === null ? lidasTexto : `${T.projeto.antesDoPasso(passo)} ${R.contando}`;
    const depois = passo === null ? T.projeto.receitaInteira : T.projeto.depoisDoPasso(passo);
    return (
      <div className="faixa-contagem">
        <p>
          {antes} → {depois} {R.contando}
        </p>
      </div>
    );
  }
  const dados = contagem.dados;

  if (passo !== null) {
    const c = dados.passos.find((x) => x.id === passo);
    if (!c) return null;
    const leitura = lerPasso(c);
    return (
      <div className={`faixa-contagem${c.alerta ? " aviso alerta" : ""}`}>
        {c.alerta && leitura && <Atencao texto={`${leitura.visivel}.`} />}
        <p>
          {R.faixaAntes(T.projeto.antesDoPasso(passo), c.entrada)} →{" "}
          {R.faixaAntes(T.projeto.depoisDoPasso(passo), c.saida)}
          {leitura && !c.alerta && <> · {leitura.visivel}</>}
        </p>
      </div>
    );
  }

  const gravadas = dados.linhas_gravadas;
  if (gravadas == null)
    return (
      <div className="faixa-contagem">
        <p>{lidasTexto}</p>
      </div>
    );
  const diferenca = dados.linhas_lidas - gravadas;
  const vazias = dados.passos.reduce((s, c) => s + c.vazias_removidas, 0);
  let resumo = "";
  if (diferenca > 0)
    resumo = `−${diferenca.toLocaleString("pt-BR")}${vazias > 0 ? ` (${R.faixaVazias(vazias)})` : ""}`;
  else if (diferenca < 0) resumo = `+${(-diferenca).toLocaleString("pt-BR")}`;
  return (
    <div className={`faixa-contagem${dados.alerta ? " aviso alerta" : ""}`}>
      {dados.alerta && <AlertaTotal dados={dados} gravadas={gravadas} aoVerPasso={aoVerPasso} />}
      <p>
        {lidasTexto} → {R.faixaAntes(T.projeto.receitaInteira, gravadas)}
        {resumo && <> · {resumo}</>}
      </p>
    </div>
  );
}

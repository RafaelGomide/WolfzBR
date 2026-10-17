// Estados de carregamento e erro (F1.H13): toda chamada à API mostra um dos
// dois enquanto não há dados; nenhuma tela fica em branco.

import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErroApi } from "../api/cliente";
import { T } from "../textos";

export function Carregando({ texto = T.comum.carregando }: { texto?: string }) {
  return (
    <div className="estado carregando" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {texto}
    </div>
  );
}

function mensagemDeErro(erro: unknown): string {
  if (erro instanceof ErroApi) return erro.detail;
  if (erro instanceof Error) return erro.message;
  return String(erro);
}

export function CaixaErro({
  erro,
  titulo,
  tentarDeNovo,
  children,
}: {
  erro: unknown;
  titulo?: string;
  tentarDeNovo?: () => void;
  children?: ReactNode;
}) {
  const titulo_ = titulo ?? (erro instanceof ErroApi && erro.title ? erro.title : undefined);
  return (
    <div className="estado erro" role="alert">
      {titulo_ && <strong>{titulo_}</strong>}
      <p>{mensagemDeErro(erro)}</p>
      {erro instanceof ErroApi && erro.errors && erro.errors.length > 1 && (
        <ul>
          {erro.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {children}
      {tentarDeNovo && (
        <button type="button" onClick={tentarDeNovo}>
          {T.comum.tentarDeNovo}
        </button>
      )}
    </div>
  );
}

/** Última barreira: um erro de renderização mostra uma mensagem em vez de
 * deixar a página branca. */
export class Barreira extends Component<{ children: ReactNode }, { erro: unknown }> {
  state = { erro: null as unknown };

  static getDerivedStateFromError(erro: unknown) {
    return { erro };
  }

  componentDidCatch(erro: unknown, info: ErrorInfo) {
    console.error(erro, info.componentStack);
  }

  render() {
    if (this.state.erro == null) return this.props.children;
    return (
      <div className="tela-centro">
        <CaixaErro erro={this.state.erro} titulo={T.app.erroInesperado}>
          <p>{T.app.erroInesperadoDica}</p>
          <button type="button" onClick={() => window.location.reload()}>
            {T.app.recarregar}
          </button>
        </CaixaErro>
      </div>
    );
  }
}

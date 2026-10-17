import { useEffect, useState } from "react";
import { quandoTokenInvalido } from "./api/cliente";
import { lerToken } from "./api/token";
import { T } from "./textos";
import { Inicio } from "./telas/Inicio";
import { TelaProjeto } from "./telas/Projeto";
import { useProjetoDaUrl } from "./util/rota";

function SemToken({ invalido }: { invalido: boolean }) {
  return (
    <div className="tela-centro">
      <div className="cartao">
        <h1>{T.token.titulo}</h1>
        <p>{invalido ? T.token.invalido : T.token.texto}</p>
        <pre>{T.token.comando}</pre>
      </div>
    </div>
  );
}

export function App() {
  const [token] = useState(lerToken);
  const [invalido, setInvalido] = useState(false);
  const projeto = useProjetoDaUrl();

  useEffect(() => quandoTokenInvalido(() => setInvalido(true)), []);

  if (!token || invalido) return <SemToken invalido={invalido} />;
  return projeto ? <TelaProjeto key={projeto} id={projeto} /> : <Inicio />;
}

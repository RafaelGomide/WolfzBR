// Token de sessão (F1.H2). Vem no fragmento da URL de abertura
// (#token=...), que o navegador não envia ao servidor. Fica só nesta
// variável: nada de localStorage, sessionStorage ou cookie. O fragmento
// continua na barra de endereço para que F5 não derrube a sessão; a chave
// troca a cada execução do WolfzBR.

let token: string | null = null;

export function lerToken(): string | null {
  const t = new URLSearchParams(window.location.hash.slice(1)).get("token");
  if (t) token = t;
  return token;
}

export function obterToken(): string | null {
  return token;
}

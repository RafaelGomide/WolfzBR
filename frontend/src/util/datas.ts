// Data e data e hora como no Brasil, para mostrar o que a API manda em ISO
// (a grade e o perfil). Só formata: o valor guardado não muda.

const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?)?$/;

/** ``2026-01-31`` → ``31/01/2026``; ``2026-01-31T14:35:00`` →
 * ``31/01/2026 14:35`` (segundos e fração só quando não são zero). Outro
 * texto passa igual. */
export function dataBr(v: string): string {
  const m = ISO.exec(v);
  if (!m) return v;
  const [, ano, mes, dia, h, min, seg = "00", fracao = ""] = m;
  const data = `${dia}/${mes}/${ano}`;
  if (h === undefined) return data;
  const temFracao = Number(fracao) > 0;
  const segundos =
    seg !== "00" || temFracao ? `:${seg}${temFracao ? fracao.replace(".", ",") : ""}` : "";
  return `${data} ${h}:${min}${segundos}`;
}

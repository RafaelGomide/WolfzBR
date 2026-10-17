// "Rota" da interface no fragmento da URL, ao lado do token:
// #token=...&projeto=<id>. F5 reabre o mesmo projeto.

import { useEffect, useState } from "react";

function params(): URLSearchParams {
  return new URLSearchParams(window.location.hash.slice(1));
}

export function projetoDaUrl(): string | null {
  return params().get("projeto");
}

export function irPara(projeto: string | null) {
  const p = params();
  if (projeto) p.set("projeto", projeto);
  else p.delete("projeto");
  window.location.hash = p.toString();
}

export function useProjetoDaUrl(): string | null {
  const [id, setId] = useState(projetoDaUrl);
  useEffect(() => {
    const ouvir = () => setId(projetoDaUrl());
    window.addEventListener("hashchange", ouvir);
    return () => window.removeEventListener("hashchange", ouvir);
  }, []);
  return id;
}

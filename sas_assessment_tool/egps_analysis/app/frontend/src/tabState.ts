import { useState, type Dispatch, type SetStateAction } from "react";

// Estado de UI que sobrevive à troca de abas: o App monta/desmonta as views
// condicionalmente, então useState local perde filtros/ordenação a cada cross-nav
// (achado P1 do critique 2026-08-28). Módulo singleton por chave — de propósito NÃO
// persiste em reload (recarregar = começar limpo); só cura a perda no cross-nav.
// Evolução natural (anotada, não feita): serializar na querystring p/ visões
// compartilháveis por link.
const store = new Map<string, unknown>();

export function useTabState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [v, setV] = useState<T>(() => (store.has(key) ? (store.get(key) as T) : initial));
  const set: Dispatch<SetStateAction<T>> = (u) =>
    setV((prev) => {
      const next = typeof u === "function" ? (u as (p: T) => T)(prev) : u;
      store.set(key, next);
      return next;
    });
  return [v, set];
}

// Escreve no store de fora de um componente. Usado pelo cross-nav do Resumo: a view de
// destino ainda não está montada (o App monta uma view por vez), então ela lê este valor
// no initializer do useState ao montar. Não notifica quem já está montado — de propósito:
// o único caso de uso é "prepare o filtro e navegue".
export function setTabState<T>(key: string, value: T): void {
  store.set(key, value);
}

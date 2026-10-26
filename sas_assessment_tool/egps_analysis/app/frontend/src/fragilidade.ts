// Fragilidade da sanitização derivada: a frase do aviso permanente da aba Inputs —
// lógica PURA, testável sob `node --experimental-strip-types` (`.tsx` não roda: o JSX
// não é removido). A conta inteira vem do backend (_fragilidade_sanitizacao); aqui mora
// só o texto, que precisa de plural correto porque fica na tela o tempo todo.
import type { SanFragilidade } from "./types";

/** "N chaves estão fora da fila só porque M EGPs estão fora do escopo; se qualquer um
 * deles entrar, elas voltam."
 *
 * A exclusividade da régua é medida contra o ESCOPO ATIVO, não contra o corpus (spec
 * §3.4.16) — decisão consciente da gestão, ciente de que chaves voltam sozinhas. O
 * aviso existe para esse preço não ficar implícito.
 *
 * `null` quando não há nada a avisar: aviso permanente é o que SEMPRE aparece quando
 * vale, não o que aparece sempre. */
export function avisoFragilidade(f?: SanFragilidade | null): string | null {
  if (!f || !f.n_chaves || !f.n_egps) return null;
  const umaChave = f.n_chaves === 1;
  const umEgp = f.n_egps === 1;
  return `${f.n_chaves} ${umaChave ? "chave está" : "chaves estão"} fora da fila só porque `
    + `${f.n_egps} ${umEgp ? "EGP está" : "EGPs estão"} fora do escopo; `
    + `se ${umEgp ? "ele" : "qualquer um deles"} entrar, `
    + `${umaChave ? "ela volta" : "elas voltam"}.`;
}

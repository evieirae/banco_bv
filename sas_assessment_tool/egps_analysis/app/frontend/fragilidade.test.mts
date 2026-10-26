import assert from "node:assert/strict";
import { avisoFragilidade } from "./src/fragilidade.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const f = (n_chaves: number, n_egps: number) =>
  ({ n_chaves, n_egps, chaves: [], por_egp: [] });

check("a frase diz N chaves e M EGPs", () => {
  assert.equal(
    avisoFragilidade(f(73, 12)),
    "73 chaves estão fora da fila só porque 12 EGPs estão fora do escopo; se qualquer um deles entrar, elas voltam.",
  );
});
check("singular não fica torto (1 chave / 1 EGP)", () => {
  assert.equal(
    avisoFragilidade(f(1, 1)),
    "1 chave está fora da fila só porque 1 EGP está fora do escopo; se ele entrar, ela volta.",
  );
});
check("sem fragilidade não há aviso — o aviso é permanente, não decorativo", () => {
  assert.equal(avisoFragilidade(f(0, 0)), null);
  assert.equal(avisoFragilidade(undefined), null);
  assert.equal(avisoFragilidade(null), null);
});
check("EGP sem chave não gera frase (dado incoerente não vira aviso)", () => {
  assert.equal(avisoFragilidade(f(0, 3)), null);
});

console.log(`\n${pass} testes OK`);

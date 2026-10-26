import assert from "node:assert/strict";
import { podeEscrever } from "./src/escrita.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const LEITURA = { somente_leitura: true };
const ESCRITA = { somente_leitura: false };

check("AWS em modo leitura: ninguém vê escrita, nem gestão/admin", () => {
  assert.equal(podeEscrever(LEITURA, { user: "a@x", papel: "gestao" }), false);
  assert.equal(podeEscrever(LEITURA, { user: "a@x", papel: "admin" }), false);
});
check("leitor não vê escrita mesmo com o app gravável", () => {
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "leitor" }), false);
});
check("gestão e admin com o app gravável veem", () => {
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "gestao" }), true);
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "admin" }), true);
});
check("Databricks: /api/me sem papel e config sem somente_leitura → como antes", () => {
  assert.equal(podeEscrever({}, { user: "a@x" }), true);
  assert.equal(podeEscrever({}, { user: null }), true);
});
check("antes de config/me chegarem não oferece escrita", () => {
  assert.equal(podeEscrever(undefined, { user: "a@x" }), false);
  assert.equal(podeEscrever(ESCRITA, undefined), false);
});
check("/api/me falhou: vale só o modo do app", () => {
  assert.equal(podeEscrever(ESCRITA, undefined, true), true);
  assert.equal(podeEscrever(LEITURA, undefined, true), false);
});
console.log(`${pass} ok`);

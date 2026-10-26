import assert from "node:assert/strict";
import { iniciais, fotoKey, montarOrganograma, PAPEIS, PAPEL_GRUPO } from "./src/organograma.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("iniciais: 1ª + última palavra", () => {
  assert.equal(iniciais("Silas Moura"), "SM");
  assert.equal(iniciais("João Marcos Cunha"), "JC");
});
check("iniciais: uma palavra e espaços extras", () => {
  assert.equal(iniciais("Cher"), "CH");
  assert.equal(iniciais("  Ana  Beatriz  "), "AB");
});
check("fotoKey: sanitiza email (@→_at_, .→_, .png)", () => {
  assert.equal(fotoKey("guilherme.zanotelli@indicium.tech"), "guilherme_zanotelli_at_indicium_tech.png");
  assert.equal(fotoKey("bob@indicium.ai"), "bob_at_indicium_ai.png");
});
check("fotoKey: vazio/sem @ → null", () => {
  assert.equal(fotoKey(""), null);
  assert.equal(fotoKey("   "), null);
  assert.equal(fotoKey("semarroba"), null);
});
check("PAPEIS: 8 cargos, todos mapeados a um grupo", () => {
  assert.equal(PAPEIS.length, 8);
  assert.ok(PAPEIS.every((p) => PAPEL_GRUPO[p]));
});
check("montarOrganograma: agrupa por papel, na ordem canônica, filtrando", () => {
  const grupos = montarOrganograma([
    { nome: "Silas", email: "s@x.ai", organograma: true, papel: "Delivery Manager" },
    { nome: "Lucas", email: "l@x.ai", organograma: true, papel: "Tech Lead" },
    { nome: "Hiroto", email: "h@x.ai", organograma: true, papel: "DE" },
    { nome: "Sergio", email: "se@x.ai", organograma: true, papel: "AE" },
    { nome: "ForaFlag", email: "f@x.ai", organograma: false, papel: "DE" },     // organograma=false
    { nome: "SemPapel", email: "sp@x.ai", organograma: true, papel: null },     // sem papel
    { nome: "PapelX", email: "px@x.ai", organograma: true, papel: "Faxineiro" }, // papel desconhecido
  ]);
  assert.deepEqual(grupos.map((g) => g.titulo),
    ["Time de Gestão", "Lideranças Técnicas", "Time de Desenvolvimento"]);
  assert.deepEqual(grupos.map((g) => g.pessoas.length), [1, 1, 2]); // Gestão1, Lider1, Dev2 (DE+AE)
});
check("montarOrganograma: vazio quando ninguém marcado", () => {
  assert.deepEqual(montarOrganograma([{ nome: "X", email: "x@x.ai", organograma: false }]), []);
});
console.log(`\n${pass} testes OK`);

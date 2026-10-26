// Rotas do SPA depois da aposentadoria da aba "EGPs Atualizados" (ticket 11).
//
// A aba saiu da barra, mas o link antigo (/egps-atualizados, com ou sem versao_id) NÃO
// pode quebrar: cai no DEFAULT_VIEW, exatamente como /arquivos-macros e /ingestao caíram
// quando as abas Macros e Ingestão foram removidas (2026-08-24). O teste também trava o
// que NÃO pode ser levado junto: o alias /escopo-migracao e o deep-link /egps/<id>.
import assert from "node:assert/strict";
import { TABS, DEFAULT_VIEW, parsePath, pathFor } from "./src/routes.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("a aba EGPs Atualizados saiu da barra", () => {
  assert.equal(TABS.some((t) => t.slug === "egps-atualizados"), false);
  assert.equal(TABS.some((t) => t.label === "EGPs Atualizados"), false);
});

check("o link antigo não leva a lugar nenhum quebrado", () => {
  assert.deepEqual(parsePath("/egps-atualizados"), { view: DEFAULT_VIEW, egp: null });
});

check("o deep-link antigo de uma versão também cai no Resumo, sem id pendurado", () => {
  // /egps-atualizados/<versao_id> era rota de detalhe; sem a view, o 2º segmento não
  // pode virar `egp` — abriria o Resumo tentando destacar um id que não é de EGP.
  assert.deepEqual(
    parsePath("/egps-atualizados/Cobran%C3%A7as__ROI%402026-09-23"),
    { view: DEFAULT_VIEW, egp: null });
});

check("o alias /escopo-migracao segue apontando para EGPs", () => {
  assert.deepEqual(parsePath("/escopo-migracao"), { view: "readiness", egp: null });
});

check("o deep-link de EGP continua inteiro", () => {
  assert.deepEqual(parsePath("/egps/Cobran%C3%A7as__ROI"),
                   { view: "readiness", egp: "Cobranças__ROI" });
  assert.equal(pathFor("readiness", "Cobranças__ROI"), "/egps/Cobran%C3%A7as__ROI");
});

console.log(`\n${pass} testes OK`);

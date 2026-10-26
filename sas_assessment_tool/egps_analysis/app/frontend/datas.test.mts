// fmtTsBR: timestamp gravado em UTC (current_timestamp() do warehouse, STRING sem sufixo
// de zona) -> hora de São Paulo na UI. Regressão do bug "log das horas +3h".
import assert from "node:assert/strict";
import { fmtBR, fmtTsBR } from "./src/diasUteis.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("UTC sem sufixo -> -3h em SP (caso real do bug)", () => {
  // linha real da sas_gestao_status: comentário feito 16:51 aparecia como 19:51
  assert.equal(fmtTsBR("2026-07-27 19:51:38.841223"), "27/07/26 16:51");
  assert.equal(fmtTsBR("2026-07-27 19:05:30.434491"), "27/07/26 16:05");
});
check("short=false mantém o ano com 4 dígitos", () => {
  assert.equal(fmtTsBR("2026-07-27 19:51:38.841223", false), "27/07/2026 16:51");
});
check("vira o dia p/ trás quando o UTC já passou da meia-noite", () => {
  assert.equal(fmtTsBR("2026-08-01 02:30:00"), "31/07/26 23:30");
});
check("meia-noite SP é 00:00 (h23, nunca 24:00)", () => {
  assert.equal(fmtTsBR("2026-07-27 03:00:00"), "27/07/26 00:00");
});
check("aceita 'T' e sufixo Z explícito", () => {
  assert.equal(fmtTsBR("2026-08-12T18:02:34.312Z"), "12/08/26 15:02");
  assert.equal(fmtTsBR("2026-07-27T19:51:38"), "27/07/26 16:51");
});
check("aceita offset explícito (não reconverte)", () => {
  assert.equal(fmtTsBR("2026-07-27T16:51:38-03:00"), "27/07/26 16:51");
});
check("segundos opcionais", () => {
  assert.equal(fmtTsBR("2026-07-27T19:51"), "27/07/26 16:51");
});
check("vazio -> travessão; formato inesperado -> string crua", () => {
  assert.equal(fmtTsBR(null), "—");
  assert.equal(fmtTsBR(undefined), "—");
  assert.equal(fmtTsBR(""), "—");
  assert.equal(fmtTsBR("sem data"), "sem data");
});
check("fmtBR (date-only, já em SP) segue sem deslocar", () => {
  assert.equal(fmtBR("2026-07-27"), "27/07/2026");
  assert.equal(fmtBR("2026-07-27", true), "27/07/26");
});
console.log(`\n${pass} testes OK`);

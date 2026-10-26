import assert from "node:assert/strict";
import {
  buildKanbanColunas, kanbanColKeyOf, STATUS_DESPRIORIZADO, STATUS_DESATUALIZADO,
} from "./src/kanbanColunas.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const ETAPAS = new Set(["Validação em DES"]);
const linha = (id: string) => ({ id, etapa: "Validação em DES" }) as never;
const rr = (status: string) => new Map([["A__x", { status } as never]]);

check("desatualizado vira coluna própria, sobrepondo a etapa", () => {
  assert.equal(
    kanbanColKeyOf(linha("A__x"), "egp", ETAPAS,
      { separarDespriorizados: true, readiness: rr(STATUS_DESATUALIZADO) }),
    STATUS_DESATUALIZADO);
});
check("despriorizado VENCE desatualizado (só cabe um status)", () => {
  assert.equal(
    kanbanColKeyOf(linha("A__x"), "egp", ETAPAS,
      { separarDespriorizados: true, readiness: rr(STATUS_DESPRIORIZADO) }),
    STATUS_DESPRIORIZADO);
});
check("sem status especial, o card fica na coluna da etapa", () => {
  assert.equal(
    kanbanColKeyOf(linha("A__x"), "egp", ETAPAS,
      { separarDespriorizados: true, readiness: rr("Em Andamento") }),
    "Validação em DES");
});
check("a coluna Desatualizado existe no board de EGP", () => {
  const keys = buildKanbanColunas("egp", { separarDespriorizados: true }).map((c) => c.key);
  assert.ok(keys.includes(STATUS_DESATUALIZADO));
  // fantasma: só aparece quando tem card, como as demais colunas de desfecho
  const col = buildKanbanColunas("egp", { separarDespriorizados: true })
    .find((c) => c.key === STATUS_DESATUALIZADO);
  assert.equal(col?.fantasma, true);
});
check("sem separarDespriorizados, nenhuma coluna de status aparece", () => {
  const keys = buildKanbanColunas("egp").map((c) => c.key);
  assert.ok(!keys.includes(STATUS_DESATUALIZADO));
  assert.ok(!keys.includes(STATUS_DESPRIORIZADO));
});

console.log(`\n${pass} testes OK`);

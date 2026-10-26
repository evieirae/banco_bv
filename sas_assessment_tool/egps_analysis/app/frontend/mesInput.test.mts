import assert from "node:assert/strict";
import { mesesPorChave, mesesDoInput } from "./src/mesInput.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

// Plano: base em M4 e M1/M3; o extra herda M2 do antecessor (mesOf = plano + extras).
const mesOfPlano = new Map([["Base_M4", 4], ["Base_M1", 1], ["Base_M3", 3]]);
const mesOf = new Map([...mesOfPlano, ["Extra_M2", 2]]);
const pares = [
  { projeto: "Base_M4", chave_canonica: "RENEG_ACAO" },
  { projeto: "Extra_M2", chave_canonica: "RENEG_ACAO" },
  { projeto: "Extra_M2", chave_canonica: "SO_DO_EXTRA" },
  { projeto: "Base_M3", chave_canonica: "safra_202501" },
  { projeto: "Base_M1", chave_canonica: "safra_202502" },
  { projeto: "Sem_mes", chave_canonica: "ORFAO" },
];
const plano = mesesPorChave(pares, mesOfPlano);
const todos = mesesPorChave(pares, mesOf);

check("compartilhado fica com o mês do PLANO, não com o do extra (93 x 85, 13/10/2026)", () => {
  assert.deepEqual(mesesDoInput(["RENEG_ACAO"], false, plano, todos), new Set([4]));
});

check("exclusivo de extra usa o mês do extra — senão sumiria de todo filtro de mês", () => {
  assert.deepEqual(mesesDoInput(["SO_DO_EXTRA"], true, plano, todos), new Set([2]));
});

check("família junta os meses das safras", () => {
  assert.deepEqual(mesesDoInput(["familia::X", "safra_202501", "safra_202502"], false, plano, todos),
    new Set([1, 3]));
});

check("sem consumidor com mês: conjunto vazio (o filtro de mês o derruba)", () => {
  assert.deepEqual(mesesDoInput(["ORFAO"], false, plano, todos), new Set());
});

console.log(`\n${pass} testes OK`);

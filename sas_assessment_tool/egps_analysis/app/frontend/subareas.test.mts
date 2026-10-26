import assert from "node:assert/strict";
import { normNome, mapaSubarea, subareaDe, subareasDe, ordenarSubareas, SEM_SUBAREA } from "./src/subareas.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const CADASTRO = [
  { nome: "Joao Carneiro", subarea: "Estratégia - cartões" },
  { nome: "Letícia Domingos Duarte", subarea: "Estratégia - rodas" },
  { nome: "Cristiano", subarea: "MIS" },
  { nome: "Não localizado", subarea: "" },   // cadastrado SEM sub-área
];

check("normNome: caixa, espaço duplo e acento não separam a pessoa", () => {
  assert.equal(normNome("  Joao  Carneiro "), normNome("joao carneiro"));
  assert.equal(normNome("Letícia Domingos Duarte"), normNome("Leticia Domingos Duarte"));
});
check("normNome: vazio/null → string vazia", () => {
  assert.equal(normNome(null), "");
  assert.equal(normNome("   "), "");
});
check("subareaDe: resolve pelo nome normalizado", () => {
  const m = mapaSubarea(CADASTRO);
  assert.equal(subareaDe("joao  CARNEIRO", m), "Estratégia - cartões");
  assert.equal(subareaDe("Leticia Domingos Duarte", m), "Estratégia - rodas");
});
check("subareaDe: fora do cadastro, vazio ou sem sub-área → null", () => {
  const m = mapaSubarea(CADASTRO);
  assert.equal(subareaDe("Fulano Novo", m), null);
  assert.equal(subareaDe("", m), null);
  assert.equal(subareaDe(null, m), null);
  assert.equal(subareaDe("Não localizado", m), null);  // cadastrado, mas sem sub-área
});
check("subareasDe: multi-valorado, deduplicado, sem sub-área vira bucket", () => {
  const m = mapaSubarea(CADASTRO);
  assert.deepEqual(subareasDe(["Cristiano", "Cristiano"], m), ["MIS"]);
  assert.deepEqual(subareasDe([], m), [SEM_SUBAREA]);
  assert.deepEqual(subareasDe(["Fulano Novo"], m), [SEM_SUBAREA]);
  assert.deepEqual(new Set(subareasDe(["Cristiano", "Fulano"], m)), new Set(["MIS", SEM_SUBAREA]));
});
check("ordenarSubareas: alfabética pt-BR com 'Sem sub-área' por último", () => {
  assert.deepEqual(
    ordenarSubareas([SEM_SUBAREA, "MIS", "Operações", "Digital", "MIS"]),
    ["Digital", "MIS", "Operações", SEM_SUBAREA]);
});
// BOM (CSV do Excel), NEL e separadores de registro (export de mainframe) chegam colados no
// nome ao copiar/colar. O Python os come no strip(); se o JS não comesse, o mesmo nome
// resolveria uma sub-área aqui e outra chave no cadastro. Contrato verificado por fuzz
// diferencial contra _norm_nome_bv (4k casos).
check("normNome: invisíveis nas pontas não criam pessoa nova", () => {
  const esperado = normNome("Joao Carneiro");
  for (const inv of ["\ufeff", "\u0085", "\u001c", "\u001f", "\u200b", "\u00a0"]) {
    assert.equal(normNome(inv + "Joao Carneiro"), esperado, JSON.stringify(inv));
    assert.equal(normNome("Joao Carneiro" + inv), esperado, JSON.stringify(inv));
  }
});
check("normNome: invisíveis no meio viram um espaço", () => {
  assert.equal(normNome("Joao\u0085Carneiro"), "joao carneiro");
  assert.equal(normNome("Joao\u001cCarneiro"), "joao carneiro");
});
check("normNome: marca de classe 0 é removida (como no Python)", () => {
  assert.equal(normNome("a\u0e31b"), "ab");
});
console.log(`\n${pass} testes OK`);

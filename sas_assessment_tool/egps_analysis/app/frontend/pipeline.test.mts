import assert from "node:assert/strict";
import { baldeEgp, contaNoTotalEgp, PHANTOM_ETAPAS_MIGRACAO, SEG, STATUS_PROJETO,
  STATUS_PROJETO_EDITAVEL, STATUS_DERIVADO_VINCULO, opcoesStatusEgp } from "./src/pipeline.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("escopo e dependência sempre contam", () => {
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "" }), true);
  assert.equal(contaNoTotalEgp({ tipo: "dependencia", etapa: null }), true);
});
check("ex-dependência sem etapa NÃO conta (fica listada com badge)", () => {
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "" }), false);
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: null }), false);
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia" }), false);
});
check("ex-dependência com etapa FANTASMA não conta", () => {
  for (const et of PHANTOM_ETAPAS_MIGRACAO) {
    assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: et }), false, et);
  }
});
check("ex-dependência com etapa real conta", () => {
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "Conversão do Código" }), true);
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "Migrado" }), true);
});
// --- a linha de base congelada manda, quando o backend a serve (ticket 21) ---
check("com na_linha_base, é ELA que decide — não a etapa viva", () => {
  // o critério "189" (ex-dependência só conta com etapa real) foi ABSORVIDO pela lista
  // congelada: a ex que estava contabilizada no dia da foto entrou nela e lá fica, mesmo
  // que a etapa dela tenha sido limpa depois. Sem isto a tabela diverge do card por drift.
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "", na_linha_base: true }), true);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Migrado", na_linha_base: false }), false);
});
check("extra nunca conta, esteja como estiver a lista", () => {
  assert.equal(contaNoTotalEgp({ tipo: "escopo", e_extra: true, na_linha_base: false }), false);
});
check("sem o campo (payload antigo) vale o critério anterior — nada quebra", () => {
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "" }), false);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "" }), true);
});

check("baldeEgp: lê status, não etapa", () => {
  assert.equal(baldeEgp("Migrado"), "migrado");
  assert.equal(baldeEgp("Despriorizado e Contabilizado"), "despriorizado");
  assert.equal(baldeEgp("Em Andamento"), "a_migrar");
});
check("baldeEgp: sem status ainda é trabalho a fazer", () => {
  assert.equal(baldeEgp(null), "a_migrar");
  assert.equal(baldeEgp(undefined), "a_migrar");
  assert.equal(baldeEgp(""), "a_migrar");
});
// A tabela por sub-área depende disto p/ a linha fechar com o total: é o que as colunas
// antigas ("Bloqueados"/"Inputs faltando") não faziam.
check("baldeEgp: partição exaustiva de STATUS_PROJETO (nada fica de fora)", () => {
  const baldes = new Set(STATUS_PROJETO.map(baldeEgp));
  assert.deepEqual(baldes, new Set(["migrado", "despriorizado", "a_migrar"]));
  assert.equal(STATUS_PROJETO.filter((s) => baldeEgp(s) === "migrado").length, 1);
  assert.equal(STATUS_PROJETO.filter((s) => baldeEgp(s) === "despriorizado").length, 1);
});
check("Desatualizado é LIDO, nunca GRAVADO: fora do vocabulário de escrita", () => {
  // O PATCH do backend valida contra o STATUS_PROJETO dele (6 valores, sem o derivado);
  // oferecer o 7º num <select> de edição era um 400 garantido — ticket 20.
  assert.ok(STATUS_PROJETO.includes(STATUS_DERIVADO_VINCULO), "segue no vocabulário de leitura (filtro/cor/Kanban)");
  assert.ok(!STATUS_PROJETO_EDITAVEL.includes(STATUS_DERIVADO_VINCULO));
  assert.equal(STATUS_PROJETO_EDITAVEL.length, STATUS_PROJETO.length - 1);
});
check("o select não oferece Desatualizado — mas também não fica vazio quando já é o valor", () => {
  assert.ok(!opcoesStatusEgp("Em Andamento").some((o) => o.value === STATUS_DERIVADO_VINCULO));
  assert.ok(!opcoesStatusEgp(null).some((o) => o.value === STATUS_DERIVADO_VINCULO));
  const desatualizado = opcoesStatusEgp(STATUS_DERIVADO_VINCULO);
  assert.equal(desatualizado[0].value, STATUS_DERIVADO_VINCULO);
  assert.equal(desatualizado[0].disabled, true, "visível para exibir, travado para gravar");
  assert.ok(desatualizado.slice(1).every((o) => !o.disabled));
});


check("extra NÃO conta no total base (sucessor de qualquer vínculo, e casca)", () => {
  // Espelha _contaveis/total_egps no backend (§3.1.2, 28/09/2026): o que chegou depois da
  // linha de base conta à parte, no contador próprio — nunca dentro do total.
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES", e_extra: true }), false);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES", e_extra: false }), true);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES" }), true);
});
check("espelhamento é outro eixo: e_sucessor sozinho não tira do total", () => {
  // Sucessor de um Substituído espelha nada (e_sucessor=false) e mesmo assim é extra;
  // quem decide a contagem é e_extra, quem decide espelhar é o tipo do vínculo.
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Migrado", e_sucessor: true, e_extra: true }), false);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Migrado", e_sucessor: false, e_extra: true }), false);
});
check("Desatualizado é status conhecido, com cor, e não é Migrado", () => {
  assert.ok(STATUS_PROJETO.includes("Desatualizado"));
  assert.ok(SEG["Desatualizado"], "precisa de cor no SEG, senão a banda sai sem estilo");
  assert.notEqual(SEG["Desatualizado"].bg, SEG["Migrado"].bg);
});
check("ex-dependência: o denominador lê a etapa GRAVADA, não a espelhada", () => {
  // Espelha _ex_deps_contab/_prio_contabiliza no backend (spec §4): uma ex-dependência sem
  // etapa NÃO entra no total só porque ganhou sucessor — se entrasse, o número subiria
  // sozinho e o card do backend (que lê a gravada) diria outra coisa que a lista.
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "Validação em DES", etapa_real: "" }), false);
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "Validação em DES", etapa_real: null }), false);
  // e o inverso: gravada real + espelho vazio (sucessor recém-chegado) segue contando
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "", etapa_real: "Conversão do Código" }), true);
  // linha sem vínculo: etapa_real == etapa, nada muda
  assert.equal(contaNoTotalEgp({ tipo: "ex_dependencia", etapa: "Migrado", etapa_real: "Migrado" }), true);
});
console.log(`\n${pass} testes OK`);

import assert from "node:assert/strict";
import { sugereFecharAntecessor, TIPO_SUBSTITUIDO, STATUS_FECHAMENTO, TIPOS_VINCULO,
  TIPO_ATUALIZADO, TIPO_UNIFICADO, TIPO_AJUDA, vinculoCompleto, baseAtu,
  sucessoresCandidatos, sucessorSugerido, mensagemErroVinculo,
  RECORTES, recorteApi, passaNoRecorte } from "./src/vinculo.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const linha = (over: Record<string, unknown> = {}) =>
  ({ vinculo_tipo: TIPO_SUBSTITUIDO, sucessor: "A__novo", status: "Em Andamento", ...over }) as never;

check("Substituído sugere fechar o antecessor", () => {
  assert.equal(sugereFecharAntecessor(linha()), true);
});
check("Atualizado e Unificado não sugerem nada (o antecessor segue vivo, espelhando)", () => {
  assert.equal(sugereFecharAntecessor(linha({ vinculo_tipo: "Atualizado" })), false);
  assert.equal(sugereFecharAntecessor(linha({ vinculo_tipo: "Unificado" })), false);
});
check("sem vínculo não sugere", () => {
  assert.equal(sugereFecharAntecessor(linha({ vinculo_tipo: null })), false);
  assert.equal(sugereFecharAntecessor(linha({ sucessor: null })), false);
  assert.equal(sugereFecharAntecessor(undefined), false);
});
check("já fechado não sugere de novo (a sugestão some quando a gestão aplica)", () => {
  assert.equal(sugereFecharAntecessor(linha({ status: STATUS_FECHAMENTO })), false);
});
check("a sugestão é UI: nada aqui escreve status", () => {
  const r = linha();
  sugereFecharAntecessor(r);
  assert.equal((r as unknown as { status: string }).status, "Em Andamento");
});

// --- ignição do vínculo (ticket 20) ----------------------------------------
check("os 3 tipos, com o acento que o servidor exige", () => {
  assert.deepEqual(TIPOS_VINCULO, ["Atualizado", "Substituído", "Unificado"]);
  // acento é significativo: "Substituido" leva 400 do backend (vinculos.tipo_valido)
  assert.ok(!TIPOS_VINCULO.includes("Substituido"));
  TIPOS_VINCULO.forEach((t) => assert.ok(TIPO_AJUDA[t], `sem ajuda para ${t}`));
});
check("vínculo pela metade não é vínculo", () => {
  assert.equal(vinculoCompleto(TIPO_ATUALIZADO, "Cobranças__x__ATU20260901"), true);
  assert.equal(vinculoCompleto(TIPO_ATUALIZADO, "   "), false);
  assert.equal(vinculoCompleto("", "Cobranças__x__ATU20260901"), false);
  assert.equal(vinculoCompleto("Atualizacao", "Cobranças__x__ATU20260901"), false);
});
check("baseAtu: a chave da ABA embutida na chave do CORPUS", () => {
  assert.equal(baseAtu("Cobranças__COLCHAO_ACORDO_CL__ATU20260910"), "Cobranças__COLCHAO_ACORDO_CL");
  // projeto comum do corpus não nasceu de versão recebida
  assert.equal(baseAtu("Cobranças__COLCHAO_ACORDO_CL"), null);
  assert.equal(baseAtu(""), null);
});
const CORPUS = ["Cobranças__A", "Cobranças__A__ATU20260910", "Cobranças__B__ATU20260901",
  "Cobranças__B__ATU20260910", "Riscos__C"];
check("sugestão de sucessor: casa a chave antiga com o projeto do corpus", () => {
  assert.equal(sucessorSugerido("Cobranças__A", CORPUS), "Cobranças__A__ATU20260910");
});
check("sem alvo no corpus não há sugestão (o pipeline ainda não rodou)", () => {
  assert.equal(sucessorSugerido("Cobranças__Z", CORPUS), null);
  assert.equal(sucessorSugerido(null, CORPUS), null);
  assert.equal(sucessorSugerido("", CORPUS), null);
});
check("duas versões no corpus: o app NÃO adivinha, só lista (cadeia é do humano)", () => {
  assert.equal(sucessorSugerido("Cobranças__B", CORPUS), null);
  assert.deepEqual(sucessoresCandidatos("Cobranças__B", CORPUS),
    ["Cobranças__B__ATU20260901", "Cobranças__B__ATU20260910"]);
});
check("erro do servidor vira texto legível — as 4 guardas", () => {
  const err = (s: number, d: string) => new Error(`${s} {"detail":"${d}"}`);
  assert.equal(mensagemErroVinculo(err(403, "Restrito ao grupo de gestão (bv_users).")),
    "Restrito ao grupo de gestão (bv_users).");
  assert.match(mensagemErroVinculo(err(404, "sucessor 'X' não está no corpus — rode o pipeline")),
    /não está no corpus/);
  assert.match(mensagemErroVinculo(err(409, "EGP com status Migrado não recebe sucessor")),
    /Migrado/);
  assert.match(mensagemErroVinculo(err(400, "tipo de vínculo inválido: Xpto")), /inválido/);
});
check("erro sem detail reconhecível não some — falha silenciosa é o bug do ticket 20", () => {
  assert.equal(mensagemErroVinculo(new Error("500 Internal Server Error")), "500 Internal Server Error");
  assert.notEqual(mensagemErroVinculo(null), "");
  assert.notEqual(mensagemErroVinculo(undefined), "");
});
check("aspas escapadas dentro do detail não truncam a mensagem", () => {
  assert.equal(mensagemErroVinculo(new Error('404 {"detail":"sucessor \\"X\\" fora"}')),
    'sucessor "X" fora');
});
check("Atualizado e Unificado espelham; Substituído fecha — a ajuda diz isso", () => {
  assert.match(TIPO_AJUDA[TIPO_ATUALIZADO], /espelho/);
  assert.match(TIPO_AJUDA[TIPO_UNIFICADO], /espelha/);
  assert.match(TIPO_AJUDA[TIPO_SUBSTITUIDO], /escopo/);
});

// --- recorte da aba EGPs: os dois filtros novos (ticket 21) ------------------
const ROW = (over: Record<string, unknown> = {}) => ({ e_extra: false, ...over }) as never;

check("o seletor tem os 5 recortes, com os dois novos no fim", () => {
  assert.deepEqual(RECORTES.map((r) => r.id),
    ["indi", "indi_deps", "base", "indi_deps_extras", "extras"]);
});
check("os recortes novos leem o MESMO payload do indi_deps (filtro é da tela)", () => {
  // uma consulta só: duas chamadas ao backend para o mesmo recorte é como a tela e o
  // contador passam a discordar.
  assert.equal(recorteApi("extras"), "indi_deps");
  assert.equal(recorteApi("indi_deps_extras"), "indi_deps");
  assert.equal(recorteApi("indi_deps"), "indi_deps");
  assert.equal(recorteApi("indi"), "indi");
  assert.equal(recorteApi("base"), "base");
});
check("Indicium + dependências NÃO mostra extra (é o recorte dos 193)", () => {
  assert.equal(passaNoRecorte("indi_deps", ROW()), true);
  assert.equal(passaNoRecorte("indi_deps", ROW({ e_extra: true })), false);
});
check("só os extras mostra SÓ extra", () => {
  assert.equal(passaNoRecorte("extras", ROW({ e_extra: true })), true);
  assert.equal(passaNoRecorte("extras", ROW()), false);
});
check("Indicium + dependências + extras mostra os dois", () => {
  assert.equal(passaNoRecorte("indi_deps_extras", ROW()), true);
  assert.equal(passaNoRecorte("indi_deps_extras", ROW({ e_extra: true })), true);
});
check("os recortes antigos seguem sem filtrar por extra", () => {
  for (const r of ["indi", "base"] as const) {
    assert.equal(passaNoRecorte(r, ROW()), true);
    assert.equal(passaNoRecorte(r, ROW({ e_extra: true })), true);
  }
});

console.log(`\n${pass} testes OK`);

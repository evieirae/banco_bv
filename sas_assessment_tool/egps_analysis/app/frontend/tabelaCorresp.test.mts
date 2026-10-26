// tabelaModernizada: do texto livre de "Tbl. Corresp." (observacao) só o nome da tabela entra
// no card; notas (colapso de aliases, regras) ficam de fora. Casos reais do dev (2026-10).
import assert from "node:assert/strict";
import { tabelaModernizada } from "./src/tabelaCorresp.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("nome puro", () => {
  assert.equal(tabelaModernizada("bv-pdbd-prd.trusted_corp_cobranca.tb_ltv_novo"),
    "bv-pdbd-prd.trusted_corp_cobranca.tb_ltv_novo");
  assert.equal(tabelaModernizada("trusted_corp_cobranca.tbbasileia"), "trusted_corp_cobranca.tbbasileia");
});
check("arquivo de origem / tabela: fica só a tabela", () => {
  assert.equal(
    tabelaModernizada("R.014.M1691.REFIN.REGATI.D260618.H231236.TXT / trusted_dbcobranca.tbcartoesserasa"),
    "trusted_dbcobranca.tbcartoesserasa");
});
check("tabela seguida de nota de unificação: só a tabela", () => {
  assert.equal(
    tabelaModernizada("bv-pdbd-prd.trusted_corp_cobranca.tb_ltv_novo Unificado em 1 input por tabela física. Aliases de libname absorvidos: LTV."),
    "bv-pdbd-prd.trusted_corp_cobranca.tb_ltv_novo");
});
check("nota sem tabela some", () => {
  assert.equal(tabelaModernizada("Unificado em 1 input por tabela física. Aliases de libname absorvidos: AUX_DU, ZDU."), null);
  assert.equal(tabelaModernizada("Despriorizado, pq o projeto que consome esse dado foi despriorizado."), null);
  assert.equal(tabelaModernizada("models/workspace/corp_cobranca/03_intermediate/int_geral_aux_base_cyber.sql"), null);
});
check("várias tabelas, sem repetir", () => {
  assert.equal(
    tabelaModernizada("prd:bv-pdbd-prd.trusted_x.tb_a prd:bv-pdbd-prd.trusted_x.tb_b bv-pdbd-prd.trusted_x.tb_a"),
    "bv-pdbd-prd.trusted_x.tb_a  ·  bv-pdbd-prd.trusted_x.tb_b");
});
check("vazio/nulo", () => {
  assert.equal(tabelaModernizada(null), null);
  assert.equal(tabelaModernizada(""), null);
});

console.log(`${pass} checks passed`);

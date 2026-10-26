// "Tbl. Corresp." de um input = coluna `observacao` do monitor, que é TEXTO LIVRE: guarda tanto
// o nome da tabela modernizada quanto notas (colapso de aliases, regras, comentários). Nos
// cards só interessa o nome da tabela — as notas continuam na aba Inputs.
// Nome de tabela modernizada = `[projeto.]trusted_<dataset>.<tabela>` (ex.:
// bv-pdbd-prd.trusted_corp_cobranca.tb_ltv_novo, trusted_corp_cobranca.tbbasileia).
const RE_TABELA = /(?:[\w-]+\.)?trusted_\w+\.\w+/g;

export function tabelaModernizada(texto: string | null | undefined): string | null {
  if (!texto) return null;
  const achados = Array.from(new Set(texto.match(RE_TABELA) ?? []));
  return achados.length ? achados.join("  ·  ") : null;
}

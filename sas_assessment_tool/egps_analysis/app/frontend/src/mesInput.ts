// Mês de priorização de cada INPUT, para o filtro de mês da aba Inputs. Puro (sem rede/
// estado) para ser testável com `node mesInput.test.mts`.
//
// O input herda os meses dos EGPs que o leem (n:n). A régua é a do funil de ingestão por
// mês do Resumo: o input que a linha de base e um extra leem PERTENCE à linha de base e
// tem só o mês do plano; o mês do extra (o do antecessor) vale apenas para o que SÓ extra
// lê (`so_de_extra`), que sem ele sumiria de qualquer filtro de mês. Antes, no recorte
// "+ extras", o compartilhado ganhava também o mês do extra e a aba discordava do Resumo
// (M1+M2 / A Receber: 93 x 85 em 13/10/2026, os 8 lidos pela base em M4 e por extra em M2).

export type MesesPorChave = Map<string, Set<number>>;

/** {chave de safra: meses dos EGPs que a leem}. `mesOf` decide quais EGPs dão mês. */
export function mesesPorChave(
  pares: { projeto: string; chave_canonica: string }[], mesOf: Map<string, number>,
): MesesPorChave {
  const m: MesesPorChave = new Map();
  for (const p of pares) {
    const mes = mesOf.get(p.projeto);
    if (mes == null) continue;
    const s = m.get(p.chave_canonica);
    if (s) s.add(mes); else m.set(p.chave_canonica, new Set([mes]));
  }
  return m;
}

/** Meses do input. `chaves` = `chavesDoInput(r)` (a família traz as safras: os pares de
 * /api/inputs-egps são no grão de safra). */
export function mesesDoInput(
  chaves: string[], soDeExtra: boolean | undefined, porPlano: MesesPorChave, comExtras: MesesPorChave,
): Set<number> {
  const fonte = soDeExtra ? comExtras : porPlano;
  const out = new Set<number>();
  for (const k of chaves) for (const mes of fonte.get(k) ?? []) out.add(mes);
  return out;
}

// Quem vê controle de escrita (ADR 0005, Fase 1). Puro — testável sob node (escrita.test.mts);
// o hook que lê o cache do React Query mora em usePodeEscrever.ts.
//
// Na AWS o app de prod roda em modo leitura (`somente_leitura`) e o papel `leitor` não grava
// nunca: o backend recusa a escrita com 403, então a tela nem oferece o controle. No
// Databricks `somente_leitura` é false e `/api/me` não traz papel — tudo fica como antes.
export type MeResposta = { user: string | null; papel?: string | null };

export function podeEscrever(
  cfg: { somente_leitura?: boolean } | null | undefined,
  me: MeResposta | null | undefined,
  meFalhou = false,
): boolean {
  if (!cfg) return false;                // config ainda não chegou: não oferece escrita
  if (cfg.somente_leitura) return false;
  if (meFalhou) return true;             // sem /api/me vale só o modo do app (o backend ainda barra)
  if (!me) return false;
  return me.papel !== "leitor";
}

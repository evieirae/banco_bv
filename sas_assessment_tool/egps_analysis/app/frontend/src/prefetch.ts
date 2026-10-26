import type { QueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { gestaoApi } from "./gestaoApi";
import type { AppConfig } from "./types";

// Aquece o cache das abas em segundo plano (disparado pelo App DEPOIS que a aba visível
// assenta — ver App.tsx). Cada entrada DEVE espelhar EXATAMENTE o queryKey + queryFn do
// useQuery da view — senão aquece um slot diferente e a aba rebusca mesmo assim. Mantenha
// em sincronia com as views. (Lineage fica de fora: busca via useEffect/api direto.)
//
// Custo: ~13 queries de warehouse por load (16 na gestão); roda em paralelo e em background.
// prefetchQuery não rebusca dado ainda fresco (respeita staleTime) nem lança em erro.
// Fora de propósito (2026-10): audit?limit=1000 (Histórico), indicium e lineage/search 5000
// (Escopo / vínculo) — pesados e raramente abertos; pagam a busca só quando a aba abre.
export function prefetchAllTabs(qc: QueryClient, cfg: AppConfig) {
  const P = (queryKey: unknown[], queryFn: () => Promise<unknown>, staleTime?: number) =>
    void qc.prefetchQuery({ queryKey, queryFn, ...(staleTime != null ? { staleTime } : {}) });

  // ORDEM IMPORTA: o navegador limita ~6 conexões simultâneas por host (Vite dev = HTTP/1.1),
  // então os prefetches rodam em ONDAS de ~6. As queries MAIS LENTAS vêm primeiro p/ pegarem
  // a 1ª onda e não ficarem presas atrás das leves — senão a aba mais pesada (EGPs /
  // egp-readiness) é a última a esquentar. Ordem ↓ por latência medida no dev warehouse (morno).
  // Os tempos abaixo são de "indi_deps" (o recorte default desde 2026-08): o fecho transitivo
  // custa ~3x o recorte "indi" antigo — inputs saiu das leves (7,8s -> 20s) e subiu de onda.
  //
  // Abas visíveis a todos os usuários — PESADAS primeiro:
  P(["egp-readiness", "indi_deps"], () => api.egpReadiness("indi_deps"));  // EGPs        (~27s)
  P(["landing"], api.landing);                                   // Resumo      (~23s)
  P(["inputs", "indi_deps"], () => api.inputs({ scope: "indi_deps", categoria: [], origem: [], etapa: [], status: [], area: [], responsavel: [], mes: [], q: "", divergence: false, bloqueador: false, exDeps: false, semExtras: false, extra: false, pendentes: false, safra: false })); // Inputs (~20s)
  P(["funis"], api.funis);                                       // Resumo      (~11s)
  P(["priorizacao"], () => api.priorizacao(), 60_000);           // Priorização (~10s) / mesPlan
  P(["resumo"], api.resumo);                                     // Resumo      (~9s)
  // ... e as leves:
  P(["analistas"], () => api.analistas());                       // Inputs / EGPs
  P(["responsaveis-bv"], () => api.responsaveisBv());            // sub-área BV (todas as abas)
  P(["blocking"], () => api.blocking());                         // Inputs (tag bloqueador)
  P(["outputs", "indi_deps"], () => api.outputs("indi_deps"));             // Outputs     (~3s)
  P(["inputs-egps", "indi_deps"], () => api.inputsEgps("indi_deps", []));  // Inputs (+ export)
  P(["scope-egps", "indi_deps", []], () => api.scopeEgps("indi_deps", [])); // Inputs
  // (["analistas"] acima também serve os dropdowns da Gestão via `select: usuariosGestao`)
  P(["egps-atualizados"], api.egpsAtualizados);                  // catálogo do vínculo no detalhe do EGP (leve)

  // Abas restritas ao grupo de gestão — senão essas queries só dariam 403 e não há aba p/ aquecer.
  if (cfg.is_gestao) {
    P(["analistas", "all"], () => api.analistas(true));          // Gestão (analistas)
    P(["responsaveis-bv", "all"], () => api.responsaveisBv(true)); // Gestão (cadastro)
    P(["gestao", "egp"], () => gestaoApi.listRows("egp"));       // Gestão (default entity=egp)
  }
}

# Propagação reativa de status no Painel SAS — design

**Data:** 2026-06-16 · **App:** `egps_analysis/app` (React/TS + FastAPI, Databricks App)

## Problema
Ao editar `status_humano` no Monitoramento, as superfícies derivadas (cards do
Monitoramento, funil/origem do Resumo, cards por EGP) só refletem a mudança ao
trocar de aba (remonta + rebusca), com flicker de `carregando…`. Queremos
atualização **ao vivo**: edição propaga instantaneamente, sem reload.

## Escopo
Em sincronia ao editar: **Cards do Monitoramento (MetricsBar)**, **Resumo (funil + origem)**,
**EGPs (detalhe por EGP)**. Fora de escopo agora: Linhagem, Prontidão, Ondas, Histórico, Prioridades.

## Abordagem (aprovada): TanStack Query
Os agregados são calculados no servidor (SQL sobre a Delta). "Ao vivo" = após o
`PATCH`, invalidar/rebuscar o que depende, com cache compartilhado entre abas.

- `QueryClientProvider` no `App.tsx`. Cache persiste entre trocas de aba → mantém a
  renderização condicional atual; ao remontar serve cache na hora (sem flicker) e
  revalida em background.
- **Query keys:** `['inputs', filters]`, `['metrics', scope]`, `['resumo']`, `['egp', projeto]`.
  `config`/`me` permanecem como estão.
- **Edição = `useMutation`:**
  - `onMutate`: update otimista da linha em `['inputs', …]` (linha permanece visível
    mesmo se deixar de casar o filtro — igual ao comportamento atual).
  - `mutationFn`: `api.patch(...)`.
  - `onSuccess`: `invalidateQueries(['metrics'])`, `(['resumo'])`, `(['egp'])`.
  - `onError`: rollback do cache otimista + erro visível.
- Invalida `['egp']` inteiro (um input pertence a vários EGPs; só o EGP aberto está em cache → barato).

## Arquivos
`package.json` (+`@tanstack/react-query`), `App.tsx` (provider), `MonitorView.tsx`
(metrics/inputs → `useQuery`; patch → `useMutation`), `ResumoView.tsx` (`useQuery['resumo']`),
`EgpView.tsx` (`useQuery['egp', projeto]`).

## Erros & teste
Estados de erro do React Query + rollback otimista no `onError`. Sem test runner no
front hoje → verificação **manual no dev local** (editar status → card muda na hora →
trocar p/ Resumo/EGP e conferir número correto sem flicker). Build (`tsc -b && vite build`)
deve passar. `vitest` fica como melhoria futura opcional.

# Atribuição de área do input (`area_principal`) — funil por área do Resumo

**Data:** 2026-07-08 · **Status:** implementado; validado em dev + simulado contra lineage de prod (read-only); aguardando promoção pra prod.

## Problema

O funil por área do Resumo conta inputs por `area_principal` (1 área por input distinto). Um
input pode estar ligado a várias áreas, então a aba Inputs (multi-área) e o Resumo (área única)
divergiam — ex.: **Jurídico 30 na aba Inputs, 18 no Resumo**.

A regra antiga escolhia `area_principal` pela área mais frequente nas ocorrências do input
(`area_count`) mesmo quando **nenhum EGP** daquela área consumia o input. Jurídico não tem EGP no
escopo real, mas herdava 18 inputs por esse fallback.

## Regra nova — lastreada no FRONTIER

O objeto correto é o **escopo real de trabalho = frontier**: o escopo alvo (EGPs marcados,
`escopo_indi = true`) **∪ as dependências transitivas** upstream (EGPs fora do escopo dos quais
os do escopo dependem — a visão "+Dependências"). Cada input é atribuído à **área do EGP do
frontier que o consome**; uma dependência conta com a área do próprio nó (`sas_lineage_nodes.area`).

Sobre `votes` = `{área -> nº de EGPs do frontier que consomem o input}`:

1. `votes` vazio (nenhum EGP do frontier consome) → `"(sem área)"`.
2. `Cobrança` entre as candidatas → `Cobrança` (preferência de negócio; canônico de
   "Cobranças"/"Cobrança Varejo" via `AREA_CANON` no publish).
3. senão → área com **maior nº de EGPs**.
4. empate → **ordem alfabética**.

**Jurídico → 0 sse e só se não houver EGP de Jurídico no frontier** (nem escopo nem dependência).
Em prod hoje isso vale (os 18 eram o fallback). Se uma dependência de Jurídico existir no frontier
(caso do lineage mais denso de dev), seus inputs viram Jurídico legitimamente.

### Exemplos (do pedido)

- X ligado a Cobrança e Riscos, ambos com EGP no frontier → **Cobrança** (regra 2).
- Y ligado a Cobrança (0 EGPs), Riscos e Finanças (com EGP, empate) → **Finanças** (regras 3/4).

## Implementação

`area_principal` é **derivado**, não do CSV estático — a fonte da verdade é o estado vivo do app
(escopo ativo + linhagem + escolhas de produtor). Autoridade única: **`recompute_escopo`** no
backend (`app/backend/main.py`), que já re-deriva `escopo_indi` e o funil e agora também
`area_principal`, via **`_recompute_area_principal(exec_fn)`**:

- **`_frontier_via(exec_fn)`** reproduz `_frontier_egps("indi_deps", [])` sem depender de OBO
  (reusa `_prune_edges`/`_filter_vias_resolvidas_res`/`_dep_of_map`/`_transitive_upstream`, lendo
  os dados via `exec_fn`). Necessário porque `recompute_escopo` roda tanto como usuário (OBO,
  `run_sql`) quanto como SP (ingest em background, `ingest.sp_exec`). Verificado idêntico ao
  `_frontier_egps` em prod.
- **`_pick_area(votes)`** aplica a regra acima (`AREA_PREF = "Cobrança"`).
- Escrita: `UPDATE … = '(sem área)'` (reset) + `UPDATE` por área com IN-list em blocos de 400 —
  tudo dentro de `MODIFY` (sem CREATE/MERGE), como o resto do recompute.

Roda em: edição de escopo (endpoint, OBO) e no fim do `_ingest_job` (SP, após o publish).
**Promoção/dev-apply** = rodar `recompute_escopo` (ou só `_recompute_area_principal`) contra o
schema alvo — não precisa de republish completo.

O **publish** (`publish_to_databricks.py`, 2 cópias) grava um `area_principal` **inicial**
(`escolhe_area_principal`, base CSV escopo-only) e removeu o fallback `area_count`; esse valor é
**transitório** — o `recompute_escopo` (frontier) sobrescreve. Para um publish manual via CLI sem
recompute em seguida, rodar o recompute depois. Teste da regra de desempate:
`app/pipeline/test_area_principal.py`.

## Fora de escopo

- Aba Inputs continua multi-área — não muda.
- Fonte hardcoded no prod: **descartada** — usa o schema alvo (dev testa isolado antes de prod).
- **Diferença de lineage prod↔dev:** prod (~1.733 edges) e dev (~3.991 edges, publish mais novo)
  têm frontiers diferentes → contagens por área diferem entre os ambientes. A promoção seguirá o
  lineage de prod. (Qual lineage é o "certo" é uma questão de dado, separada desta regra.)

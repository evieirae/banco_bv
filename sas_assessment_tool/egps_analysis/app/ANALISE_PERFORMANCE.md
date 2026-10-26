# Análise de Performance — App `monitoramento-sas`

> Análise técnica do painel de Modernização SAS (FastAPI + SQL Warehouse via Statement Execution API, OBO por request; frontend React/TS/Vite). Foco em **latência percebida** e **ROI honesto** das otimizações. Todos os achados são fundamentados em `file:line` ou medição empírica; onde uma recomendação não se sustenta, está marcada como tal.

---

## 1. Arquitetura atual e modelo de latência do request

### O caminho de um page-load até o dado

```
Browser (React/Vite SPA, 1 chunk de 857 KB)
   │  fetch /api/<endpoint>  (React Query, staleTime 15s)
   ▼
Databricks App (container FastAPI, uvicorn single-process)
   │  _OBOAuthMiddleware lê X-Forwarded-Access-Token  (main.py:192)
   │  handler SÍNCRONO no threadpool do Starlette  (43 handlers, 0 async — main.py:176 é o único async, no middleware)
   │  para CADA statement do endpoint:
   │     run_sql() → _client() → _user_client(token)  ⇒ WorkspaceClient NOVO por chamada (main.py:140-160, "sem cache de propósito")
   ▼
SQL Warehouse "monitoramento-sas" (id 5922c26f81f1bbdd — app.yaml:14)
   │  statement_execution.execute_statement(disposition=INLINE, format=JSON_ARRAY, wait_timeout="50s")  (main.py:215-222)
   │  poll get_statement() com time.sleep(1) enquanto PENDING/RUNNING  (main.py:226)
   │  ⚠ se o warehouse estava em auto-stop, o 1º statement paga o spin-up
   ▼
Delta (bv_dev_db.monitoramento_sas) — tabelas quase-estáticas (full-replace só no publish) + 4 superfícies editáveis ao vivo
```

### Características que definem o modelo de latência

- **O custo dominante é I/O, não CPU.** As tabelas são minúsculas (a maior fonte estática, `06_prontidao_tabela.csv`, tem ~81 k linhas / 14 MB; os agregados publicados — ~230 EGPs de escopo, ~1,9 k arestas, ~1,2 k ondas — são ordens de magnitude menores). O trabalho Python pós-query (loops sobre milhares de dicts, BFS sobre grafo de ~1,9 k arestas) roda em micros-a-milissegundos. O tempo é gasto em **fila + spin-up + round-trip + poll** do Statement Execution API.
- **Fan-out serial de statements por endpoint.** Cada endpoint dispara N `run_sql` **sequenciais**, sem batching nem paralelismo:
  - `/api/landing` — **8 statements** (main.py:387-417) + fecho transitivo (BFS) em Python (main.py:399-410)
  - `/api/egp` (detalhe) — 5-6 (main.py:670-695)
  - `/api/egp-pipeline` (PATCH) — 4-6, incluindo **2 DDL** `CREATE TABLE IF NOT EXISTS` no hot path (main.py:726-731)
  - `/api/resumo` — 3 (main.py:858+); `/api/funis` — 3 (main.py:437-460); `/api/inputs` — 2 (count + SELECT LIMIT 20000 INLINE, main.py:310-314)
- **Auth OBO por request, por design.** `_user_client(token)` constrói um `WorkspaceClient` novo a cada `run_sql` (main.py:140-160). É uma decisão de **segurança correta** (token de vida curta; revogação/expiração reflete na hora). O custo de construir o SDK é desprezível frente ao round-trip SQL — porém são **N construções por endpoint** porque `run_sql` chama `_client()` a cada statement.
- **Zero cache de dados.** Os únicos `@lru_cache` são `_sp_client` (main.py:140, client do service principal) e `_ensure_prio_table` (main.py:910, guard de DDL). **Nenhum** cacheia resultado de query. Toda navegação de aba re-executa SQL ao vivo.
- **Freshness ao vivo é um requisito de produto, não acidente.** O "status efetivo" (`_eff_status`, main.py:67-90) mistura coluna **editável por humano** (`status_humano` em `sas_inputs_monitor`) com o auto do publish. `/api/metrics` recalcula **AO VIVO** de propósito (comentário main.py:262) para que editar um status reflita nos cards imediatamente. O front reforça isso: React Query com `staleTime: 15_000` + `refetchOnWindowFocus: true` (App.tsx:18) e `invalidateQueries` nas mutações. **Qualquer otimização tem de preservar essa freshness.**
- **Superfícies de escrita ao vivo (mudam fora do republish):** colunas humanas em `sas_inputs_monitor` (PATCH `/api/inputs`), `sas_egp_pipeline`, `sas_egp_prioridades`, e `sas_escopo` — esta última dispara `recompute_escopo()` (main.py:507-538), **10 statements UPDATE/DELETE/INSERT em massa** a cada add/remove de escopo, re-derivando `escopo_indi` em nodes/egp_inputs/inputs_monitor/resumo e reconstruindo o funil.

### Frontend

- Build empírico (reproduzido): **1 único chunk** `static/assets/index-BBV1Ni88.js` = **857 KB raw (~271 KB gzip)** + 27 KB CSS. Vite emite aviso `>500 KB`.
- As **8 views** são importadas **eager** em `App.tsx:4-11` e renderizadas por flag (`App.tsx:195-202`). Sem `React.lazy`, sem `manualChunks` em `vite.config.ts` (confirmado: só `base:"./"`, `outDir:"../static"`).
- **~metade do bundle é Cytoscape** (core min 423,8 KB + fcose 55,9 KB + expand-collapse 30,6 KB), importado **exclusivamente** por `LineageView.tsx:2-4` (grep confirma: só esse arquivo + um `.d.ts` de tipos). Mesmo assim **100% dos usuários** baixam o grafo na 1ª visita, ainda que ~7/8 nunca abram a aba Linhagem.

---

## 2. Diagnóstico — gargalos reais, rankeados

| # | Gargalo | Evidência | Severidade |
|---|---------|-----------|------------|
| **1** | **Cold start do SQL Warehouse (auto-stop).** O 1º statement após o cool-down paga o spin-up. É a maior fonte de **latência percebida** na 1ª interação após ociosidade. | `app.yaml:14` fixa o warehouse; `README.md:50-51` diz textualmente que ele "precisa estar ligado (ou liga sozinho na 1ª query)" → auto-stop confirmado. ⚠ **O rótulo "serverless" NÃO é comprovável no repo** (é config do workspace); a magnitude (segundos vs minutos) depende disso. | **Alta** |
| **2** | **Fan-out de N round-trips serializados por endpoint.** `landing` = 8, `egp` = 5-6, `resumo`/`funis` = 3. Mesmo com warehouse morno, são N round-trips + poll de 1s cada — latência que aquecer o warehouse **não** elimina. | `run_sql` chamado 8× em `main.py:387-417`; cada um é `execute_statement` independente (main.py:215-222). Não há paralelismo. | **Alta** |
| **3** | **Zero cache de leitura** para dado quase-estático, com pontos de mutação explícitos. Toda visita de aba re-paga o custo cheio. | Único `@lru_cache` em `_sp_client` (main.py:140) e `_ensure_prio_table` (main.py:910); nenhum cacheia query. | **Alta** (com ressalvas de segurança, ver §4) |
| **4** | **Re-agregação ao vivo + BFS em Python** que poderia ser parcialmente precomputada. `landing` refaz o fecho transitivo do grafo sobre **todas** as arestas a cada GET. | DFS/while-stack em `main.py:399-410`; SELECT de todas as edges em `main.py:394`. | **Média–Alta** |
| **5** | **Bundle único de 857 KB**, metade Cytoscape, carregado eager para todos. Penaliza o TTI/first-load de quem nunca abre Linhagem. | Build empírico; imports estáticos `App.tsx:4-11`; cytoscape só em `LineageView.tsx:2-4`. | **Média–Alta** |
| **6** | **DDL no hot path de PATCH.** `/api/egp-pipeline` roda 2× `CREATE TABLE IF NOT EXISTS` por request, antes do MERGE. | `main.py:726-731`; as tabelas já são criadas no publish (`publish_to_databricks.py:699-703`). | **Média** |
| **7** | **Estáticos servidos sem GZip nem `Cache-Control`.** O cliente baixa 857 KB crus se o proxy não comprimir; assets têm content-hash mas não são marcados imutáveis. | `add_middleware` só registra `_OBOAuthMiddleware` (main.py:192); nenhum `GZipMiddleware`. `_SPAStaticFiles` (main.py:1048) só faz fallback de SPA, não seta headers de cache. | **Média** |
| **8** | **`recompute_escopo()` = 10 statements full-table** por add/remove de escopo. Transfere latência para o clique humano. | `main.py:507-538` (8 UPDATE de tabela inteira + DELETE + INSERT…GROUP BY). | **Média** |
| **9** | **Tabelas grandes sem virtualização** (ReadinessView, IndiciumView busca até 5000 linhas). Jank ao filtrar/ordenar. | `ReadinessView.tsx:168` `.map(...)`; `IndiciumView.tsx:24` busca 5000, `:111` `.map(...)`. Só `InputsTable` usa `useVirtualizer`. | **Média–Baixa** |
| **10** | **`/api/inputs` materializa até 20 k linhas INLINE em JSON** por request. Risco de teto INLINE (~25 MiB) + pico de memória. | `READ_CAP=20000` (main.py:125); SELECT LIMIT 20000 INLINE (main.py:311-314). | **Baixa–Média** |
| **11** | **Handlers 100% síncronos** com `time.sleep(1)` bloqueante segurando thread do pool durante a espera. | 43 handlers `def`, 0 `async def` de endpoint; `time.sleep(1)` em `main.py:226`. | **Baixa** (volume de usuários pequeno) |
| **12** | **Lógica de agregação duplicada** entre `publish_to_databricks.py` (Python) e `main.py` (SQL), mantida em sincronia **à mão** ("mantenha os dois conjuntos idênticos"). Risco de drift. | `recompute_escopo` em main.py:516-538 é cópia textual de `publish_to_databricks.py:716-744`. | **Média** (manutenção) |

---

## 3. Oportunidades — priorizadas por impacto × esforço

| Ação | Impacto | Esforço | Detalhe concreto |
|------|:------:|:------:|------------------|
| **Subir auto-stop do warehouse (ou mantê-lo morno)** | **Alto** | **Trivial** | Config de 1 ajuste no workspace. Mata o cold start (gargalo #1) para uso em rajadas de poucos usuários. **Medir antes** o tipo do warehouse e quanto do p95 é spin-up. |
| **Lazy-load `LineageView` (React.lazy + Suspense)** | **Alto** | **Baixo** | `App.tsx:201` → `const LineageView = React.lazy(() => import('./components/LineageView').then(m => ({default: m.LineageView})))` (precisa do `.then` porque o export é **nomeado**, não default) + `<Suspense fallback>`. **Medido empiricamente:** first-load cai de **271 → 81 KB gzip**; Cytoscape vira chunk separado de 190 KB gzip, baixado só ao abrir Linhagem. Adicionar ErrorBoundary p/ falha de chunk após redeploy (ver §4). |
| **Adicionar GZip + `Cache-Control` imutável** | **Médio** | **Baixo** | `app.add_middleware(GZipMiddleware, minimum_size=1000)`; em `_SPAStaticFiles.get_response`, setar `Cache-Control: public, max-age=31536000, immutable` para `/assets/*` (hash no nome) e `no-cache` para `index.html`. |
| **Tirar DDL do hot path do PATCH** | **Médio** | **Baixo** | Mover os 2 `CREATE TABLE IF NOT EXISTS` (main.py:726-731) para um `_ensure_pipe_table()` com `@lru_cache(maxsize=1)` (igual a `_ensure_prio_table`), ou confiar no publish que já as cria. |
| **Fundir os N statements em 1-2 queries (CTE)** | **Alto** | **Médio** | `landing`/`egp`/`resumo`: consolidar count+SELECT em CTEs únicas; mover o **fecho transitivo para SQL** (CTE recursiva sobre `sas_lineage_edges`, lendo `escopo_indi` **vigente**) em vez do while-stack Python. Corta de N×RTT para ~1-2×RTT **sem** introduzir staleness. |
| **Construir o `WorkspaceClient` OBO 1× por request** | **Baixo** | **Baixo** | Guardar o client no contextvar ao lado do token (middleware) e reusar em todos os `run_sql` do mesmo request. Mantém a segurança; corta N construções de SDK por endpoint. |
| **Cache em memória com TTL curto + invalidação no PATCH** | **Médio–Alto** | **Médio** | **APENAS com ressalvas** (ver §4): chave de cache **deve incluir a identidade OBO** (não vazar dados entre usuários); TTL curto (≤15-30s) para cobrir o republish out-of-band; invalidar em **todas** as mutações (inputs, escopo, pipeline, prioridades). **Não** usar "TTL maior para tabelas estáticas" — elas mudam no republish sem hook no app. |
| **Virtualizar ReadinessView / IndiciumView** | **Médio–Baixo** | **Médio** | Aplicar o padrão de `InputsTable` (`useVirtualizer`); `@tanstack/react-virtual` já é dependência (custo zero de bundle). |
| **Paginação server-side em `/api/inputs`** | **Baixo–Médio** | **Médio** | LIMIT/OFFSET ou keyset (`qtd_projetos`, `artifact`) em páginas de centenas de linhas; para export grande, `disposition=EXTERNAL_LINKS`. Reduz risco de teto INLINE e pico de memória. |
| **Calibrar `refetchOnWindowFocus`/`staleTime` por query** | **Baixo** | **Baixo** | Per-query `staleTime` de minutos para catálogos grandes (nodes-all/indicium/landing) p/ não rebuscar 5000 linhas a cada alt-tab. |
| **Centralizar a definição de cada agregado num módulo SQL compartilhado** | **Médio** | **Médio** | Eliminar a duplicação publish×backend (#12) — uma fonte de verdade gera o SQL usado nos dois lados. |

---

## 4. Vereditos explícitos e honestos

### Trocar de linguagem (Go/Rust)? — **NÃO. Teatro de performance.**

O gargalo é **I/O** (fila + spin-up + round-trip + poll ao warehouse), não CPU Python. O trabalho de CPU no backend é desprezível: BFS sobre grafo de ~1,9 k arestas, loops sobre poucos milhares de dicts, JSON pequeno — micros a poucos ms. Reescrever em Go/Rust **não toca** o tempo dominante e ainda joga fora o ecossistema maduro (databricks-sdk, OBO já resolvido, FastAPI/pydantic). **ROI negativo.**

### Mudar o padrão/arquitetura de leitura?

- **(a) Cache em memória + invalidação no PATCH/TTL — FAZER, com forte ressalva.** É bom ROI, **mas a recomendação ingênua tem 3 furos comprovados:**
  1. **Segurança/OBO.** As queries de leitura batem em tabelas **fixas e compartilhadas** sem filtro por `current_user()` (current_user só aparece em writes de auditoria). O OBO existe para **autorização** (Unity Catalog), não para escopo de linha. Uma chave de cache `(endpoint, params)` **sem a identidade do usuário** serviria resultado de A para B e contornaria a checagem de permissão do UC. A chave **precisa** incluir o principal OBO — o que num app multiusuário reduz a taxa de cache-hit.
  2. **Republish out-of-band.** `publish_to_databricks.py` escreve Delta **fora** do app, sem hook de invalidação. "TTL maior para tabelas estáticas (lineage/resumo/funil)" está **errado**: elas mudam no republish e ficariam stale até o TTL. TTL curto (≤15-30s) é obrigatório.
  3. **Freshness de edição humana.** `/api/metrics`, `landing`, `resumo`, `waves`, `readiness` dependem de `status_humano` editado ao vivo (e `escopo_indi`, mutado em runtime por `recompute_escopo`). Cache stale **mostra números errados** logo após uma edição multiusuário, contradizendo o contrato "reflete na hora".
  - Detalhe: `/api/config` (main.py:569) **não** se beneficia — retorna só constantes em memória, nem toca o warehouse.

- **(b) Materializar agregados no publish — FAZER de forma SELETIVA, não como proposto.** Só vale para o que **não** depende de edição humana ao vivo.
  - ❌ **Precomputar os 10 escalares da `landing` num `sas_landing_metrics` de 1 linha no publish quebra a freshness:** itens 2/3/5/6/7 dependem de `escopo_indi`, que é reescrito **em runtime** por `recompute_escopo()` (main.py:507-538) a cada add/del de escopo — sem republish. Uma tabela só do publish ficaria stale imediatamente. (Não existe `sas_landing*` no publish hoje; confirmado.)
  - ✅ **O que é viável:** materializar o **fecho transitivo por-nó** (independente de escopo, pois `sas_lineage_edges` é full-replace estável entre publishes) e aplicar o filtro de escopo em query-time; e **fundir os 8 statements em 1-2 CTEs** movendo o BFS para SQL recursivo. Isso corta round-trips e CPU **sem** staleness.
  - ⚠️ **Materializar `eff_status` como coluna persistida** (proposta de uma das lentes) é **parcialmente redundante e arriscada:** `item4` da landing já é um `count_if` inline (main.py:389) — materializar não corta round-trip; e duplicaria a lógica de normalização legada de `_eff_status` em 3 lugares (publish MERGE, PATCH, recompute), com risco de drift. Além disso, transformar os 4 dashboards em "SELECT * FROM tabela_do_endpoint" exigiria **4 agregações com 4 grãos de GROUP BY diferentes** mantidas em sincronia, e o recompute por PATCH **não é barato/incremental** — replicaria o padrão **full-table** do `recompute_escopo`, transferindo latência do dashboard (cacheável/invalidável no React Query) para o **clique humano** (não cacheável). Pode **piorar** a UX percebida.

- **(c) Store local embarcado (DuckDB/SQLite/Parquet) — NÃO. Refutado.**
  1. **O JOIN estático×editável NÃO é residual; é o padrão dominante.** Quase toda métrica deriva de `status_humano` via `_eff_status` (CASE em SQL, **não** coluna materializada) — `/api/egp-readiness`, `/api/egp`, `/api/waves`, `/api/resumo`, `/api/prioridades` todas fazem LEFT JOIN do estático contra o editável. A maioria das telas precisaria do JOIN cross-store remoto×local, não de leitura local pura.
  2. **As telas mais quentes leem da superfície editável:** `/api/inputs` (lista principal) lê só de `sas_inputs_monitor`; `/api/metrics` (KPIs) é **AO VIVO de propósito** (main.py:262). Store local + TTL quebra a edição refletir na hora.
  3. **Limite de deploy:** README:82 confirma **10 MB por arquivo** no `databricks sync`; a fonte estática maior (`06_prontidao`, 14 MB) **estoura**. O canal é sync de **código**, não pipeline de dado — acopla dado a redeploy.
  4. **Dependência nova:** `requirements.txt` não tem duckdb/pyarrow.
  5. **OBO/UC bypass:** um store local read-only roda como **service principal**, compartilhado, e **não respeita** os grants SELECT per-user do Unity Catalog → vazamento de privilégio em ambiente multiusuário.
  - Núcleo aproveitável (mínimo): cachear localmente **apenas** `edges`/`nodes` para `lineage/graph` e `neighbors`, que são genuinamente read-only e estáticas — **se e somente se** os grants forem uniformes. Não a generalização.

- **(d) Warehouse pequeno always-on vs serverless com auto-stop maior — TRADE-OFF real, provavelmente vale.** Decisão de **custo**, não técnica. Para painel interno de poucos usuários, trocar um custo fixo baixo e previsível por latência constante (ou só subir o auto-stop) é a mudança de **maior impacto percebido por menor esforço**. **Medir o cold start real primeiro** — e confirmar se o warehouse é serverless ou clássico, pois isso muda a magnitude (segundos vs ~2-5 min) e o custo always-on.

### Trocar o framework de frontend (Preact/Svelte/Solid)? — **NÃO.**

O peso do bundle é dominado por uma lib de **visualização de grafo** (Cytoscape, ~424 KB), não por React (react+react-dom min ~140 KB). Migrar economizaria poucas dezenas de KB, **não tocaria** nos ~424 KB do grafo, e custaria reescrever ~15 componentes + a integração React Query + a virtualização. O frontend **não é gargalo de latência** — ele espera o backend, que espera o warehouse. O caminho correto é arquitetural **dentro** do stack: lazy-load do grafo + GZip + virtualização (lib já presente). Se o grafo virar gargalo crítico no futuro, a alavanca é trocar a **engine de render** (core mínimo do Cytoscape / sigma.js / regl) — não o framework de UI.

> **Princípio transversal de todos os vereditos:** o que **depende de edição humana** (`status_humano`, `escopo_indi`) **precisa continuar ao vivo** (lido na hora ou recomputado em runtime, sob OBO/MODIFY com DELETE+INSERT — usuários OBO não têm CREATE). O que vem **só do grafo/publish** pode ser precomputado/cacheado. Misturar os dois congela números que o produto exige frescos.

---

## 5. Roadmap em fases

### Fase 0 — Instrumentar (pré-requisito, esforço trivial)
**Antes de qualquer obra maior**, instrumentar `run_sql` para logar, por statement: **spin-up (cold)** vs **tempo de fila** vs **execução** vs **N×round-trip serial**. Sem baseline de p95 não dá para saber quanto do gargalo é cold start (#1) vs fan-out (#2). É a recomendação transversal de duas das quatro lentes.
**Ganho:** dados para decidir; evita otimização especulativa.

### Fase 1 — Quick wins (baixo esforço, alto/médio impacto)
1. **Subir o auto-stop do warehouse** (ou avaliar always-on 2X-Small) — confirmar tipo do warehouse primeiro.
2. **Lazy-load `LineageView`** (React.lazy + Suspense + ErrorBoundary p/ chunk stale após redeploy).
3. **GZip + `Cache-Control: immutable`** nos estáticos.
4. **Tirar a DDL do PATCH** (`_ensure_pipe_table` com `@lru_cache`).
5. **`WorkspaceClient` OBO 1× por request.**

**Ganho esperado:** mata o cold start percebido (Fase 0 confirma); first-load de **271 → ~81 KB gzip** (medido) para ~7/8 dos usuários; visitas recorrentes baixam zero JS (cache imutável); PATCH de pipeline perde 2 statements de DDL; endpoints multi-statement perdem N construções de SDK.

### Fase 2 — Reduzir round-trips e calibrar cliente (médio esforço, alto impacto)
1. **Fundir os N statements em 1-2 CTEs** em `landing`/`egp`/`resumo`/`funis`; **mover o fecho transitivo para SQL recursivo** (lendo `escopo_indi` vigente — sem staleness).
2. **Virtualizar** ReadinessView / IndiciumView (lib já incluída).
3. **Calibrar `staleTime`/`refetchOnWindowFocus`** por tipo de query no front.

**Ganho esperado:** `landing` de 8×RTT → ~1-2×RTT (e BFS sai do Python para o motor SQL); menos jank e re-renders nas tabelas grandes; menos refetch de payloads de 5000 linhas a cada alt-tab. Tudo **preservando** a freshness ao vivo.

### Fase 3 — Cache + materialização seletiva (médio esforço, médio-alto impacto)
1. **Cache em memória com TTL curto (≤15-30s)**, **chaveado por identidade OBO** + endpoint + params, **invalidado em TODAS as mutações** (inputs, escopo, pipeline, prioridades). Process-local basta (cada réplica aquece sozinha; YAGNI Redis nesta escala).
2. **Precomputar no publish APENAS o que não depende de edição humana** (ex.: fecho transitivo por-nó), aplicando o filtro de escopo em query-time.
3. **Centralizar a definição de cada agregado** num módulo SQL compartilhado publish×backend (elimina o drift do #12).
4. **Paginação server-side em `/api/inputs`** (e `EXTERNAL_LINKS` para export).

**Ganho esperado:** corta a maioria do tráfego repetido ao warehouse sem violar segurança nem freshness; remove o risco de divergência card-vs-republish; elimina o risco de teto INLINE / pico de memória em `/api/inputs`.

### Fora de escopo / YAGNI (não fazer sem evidência que prove o contrário)
- Reescrever backend em Go/Rust.
- Store local embarcado (DuckDB/SQLite/Parquet) — viola limite de deploy + OBO/UC + freshness.
- Trocar framework de frontend.
- Migrar handlers para async (o threadpool de 40 threads absorve bem o volume atual; fundir queries já alivia a pressão — revalidar a propagação do contextvar OBO seria custo extra de baixo retorno hoje).
- Materializar `eff_status` como coluna persistida + 4 tabelas-de-endpoint com recompute full-table no PATCH — transfere latência para o clique humano e duplica lógica; só reconsiderar se a medição provar que os SELECTs-com-JOIN ao vivo são o gargalo (improvável dado o volume).

---

## 6. Implementado (2026-06)

O que saiu da análise acima e foi de fato implantado (e o que **não** foi, de propósito).

### Fase 0 — Instrumentação ✅
`run_sql` e o middleware logam latência: linhas `[perf] stmt …` (por statement) e `[perf] req …` (por request). Baseline para medir antes/depois sem chutar.

### Tier 1 — Caminho de escrita do status (PATCH) ✅
Foco no "editar status leva 7-12s":
- **DDL fora do hot-path:** `_ensure_pipe_table()` com `@functools.lru_cache(maxsize=1)` — o `CREATE TABLE IF NOT EXISTS` saiu do PATCH de `egp-pipeline` (rodava a cada clique).
- **Sem re-SELECT no `patch_input`:** o PATCH faz 1 pré-SELECT (13 colunas, incl. `origem`) e **monta a linha de retorno em Python**, em vez de um 2º SELECT pós-MERGE. (Bug corrigido junto: o retorno antigo omitia `origem` → a coluna piscava em branco após editar o status, até o refetch.)

**Medido:** ~7-12s → **~5-6s**. O piso restante é Delta (writes ~3.5s) + auditoria (~2.4s) — só cai mais com escrita **assíncrona** da auditoria (Tier 2, não feito).

### Cache em memória do grafo de linhagem ✅
`/api/lineage/{areas,graph,neighbors}` usam cache em processo:
- **Chave inclui o hash do token OBO** — cada usuário só recebe o que pode ver (não vaza entre identidades).
- **TTL 5 min** + teto de 256 entradas (evicção simples).
- **Invalidação por geração:** `recompute_escopo()` faz `_lineage_gen += 1` + limpa o cache; um hit só vale se a geração capturada **antes** do `produce()` ainda é a vigente — fecha a corrida read-after-write (uma leitura concorrente não repõe valor stale após mutação de escopo).
- Process-local de propósito (1 processo por app — ver `app.yaml`); YAGNI Redis nesta escala.

### Manutenção das tabelas Delta ✅ (com consentimento)
`OPTIMIZE` nas tabelas operacionais (compactou `egp_pipeline` 19→1 arquivo; audits 134→1 / 45→1) + `autoOptimize` habilitado. **Escrita em tabela de produção → exige consentimento humano explícito** (foi pedido e dado).

### Não implementado (de propósito, por ora)
Fase 2 (fundir os N statements de `landing`/`egp`/`resumo`/`funis` em CTEs; fecho transitivo em SQL recursivo; virtualizar Readiness/Indicium), lazy-load do Cytoscape, e Tier 2 (auditoria assíncrona → status ~4s). Disponíveis como próximos passos — ver Fases 1-3 acima.
---

## 7. Implementado (2026-08) — paralelização + caches por geração

Branch `perf/parallel-statements-and-cache` (base develop). Ataca o gargalo #2 (fan-out
serial) sem fusão de CTEs: os N statements de um endpoint continuam existindo, mas rodam
**em paralelo** e os resultados intermediários/finais ficam **cacheados por geração**.

**Vocabulário fixado nesta rodada:** *morno* = warehouse já ligado (custo estrutural do
código); *frio* = 1ª query após auto-stop (custo do warehouse, não do código);
*gen-frio* = processo quente mas caches invalidados por uma edição (pior caso real de
navegação). Invariante inegociável: **edição humana reflete na hora** — toda mutação
bumpa a geração; nenhum cache serve dado pré-edição.

### O que mudou (tudo em `backend/main.py`)

- **`_parallel(*thunks)`** — executa leituras independentes em `ThreadPoolExecutor`
  (teto `_PAR_MAX = 8` statements simultâneos por request), propagando o contexto do
  request (token OBO + acumulador `[perf]`) via `contextvars.copy_context()`. Exceção
  re-levanta no caller (mesma semântica do serial).
- **Ondas de paralelismo** em `/api/egp-readiness`, `/api/egp`, `/api/gestao/rows`,
  `_egp_readiness_rows` (6 leituras ∥), `_gestao_extras` (3 ∥), `_edges_pruned` (3 ∥),
  `_frontier_egps` (3 ∥), `_ex_deps` (2 ∥).
- **Caches por geração novos** (mesmo padrão OBO+TTL+gen do cache de linhagem):
  `_edges_pruned`, `_egps_fora_backlog`, `_frontier_egps`, `_ex_deps`, `_ex_deps_contab`
  em `_cache_lineage`; **payload inteiro** de `egp-readiness`/`egp`/`gestao_rows` em
  `_cache_endpoint` (dict próprio). Efeito colateral positivo: `landing`/`resumo`/
  `funis`/`scope-egps`/`priorizacao` melhoram de carona (usam os mesmos helpers).
- **`_bump_gen()` em TODAS as mutações que faltavam:** `egp-pipeline` (T_PIPE!),
  `output-pipeline`, `gestao/status`, `gestao/bv` (add/del), `gestao/datas`. Sem isso o
  cache de payload violaria a freshness (T_PIPE alimenta readiness/frontier/gestão).
- **`_ensure_gestao_tables` com `lru_cache`** — rodava 3 CREATE TABLE por request da
  Gestão.

### Medido (dev local → warehouse dev morno, mesma base develop, payloads byte-idênticos pré/pós)

| Endpoint | Antes (toda visita) | Depois: gen-frio (pós-edição) | Depois: navegação típica |
|---|---:|---:|---:|
| `/api/egp-readiness?scope=indi_deps` | 11,8s (37s frio) | **4,0s** | **~20-60ms** |
| `/api/egp` (clique no EGP) | 6,5s | **1,4s** | **~5ms** |
| `/api/gestao/rows?entity=egp` | 7,8s | **1,7s** | **~10ms** |
| `/api/gestao/rows?entity=input` | 6,0s | ~1,7s | ~80ms |
| `/api/landing` (carona) | 8,9s | ~5,0s | idem (sem payload-cache) |
| `/api/resumo` (carona) | 8,3s | ~3,4s | idem |
| `/api/funis` (carona) | 6,3s | ~2,5s | idem |

- **Equivalência verificada:** 7 payloads (readiness, gestão egp/input, egp, landing,
  resumo, funis) comparados por JSON — **idênticos** pré/pós-patch.
- **Pior caso restante:** 1ª request pós-deploy paga a tempestade de `_ensure_*`
  (7 CREATE + 6 probes de coluna, serial, 1× por processo) → ~14-16s uma única vez.
- **Meta ≤3s morno:** clique EGP e Gestão ✓; readiness gen-frio ficou em ~4s (a cadeia
  crítica é frontier→hidratação→header, com a query `cand` do `_blocking` de 2-5s).
  Opções para fechar o 1s, NÃO implementadas (decisão pendente): fusão em CTEs
  (Fase 2 original), pré-aquecimento do payload pós-mutação (recompute em background
  lendo dados PÓS-edição — não viola freshness), ou aceitar (navegação típica é ~ms).

---

## 8. Auditoria e implementação (2026-10) — piso por statement, cache compartilhado, single-flight

Branch `perf/backend-latency` (base main `4cce5480`). Diagnóstico feito com dado de PROD
(read-only), não com estimativa.

### O que a medição mostrou

- **Warehouse:** serverless PRO 2X-Small, **máx. 1 cluster**, auto-stop 10 min — compartilhado
  por app prod, app dev e sessões locais.
- **Piso de ~1 s por statement, qualquer que seja a query.** 218 statements do app prod
  casados por `stmt_id` (log `[perf]` × `system.query.history`): o app esperava p50
  **1.032 ms**; o warehouse trabalhava p50 526 ms (compile p50 293 ms mesmo com 78% em
  result cache); **~400 ms (p50) eram overhead de cliente** — `WorkspaceClient` novo + TLS
  novo a cada `run_sql`. Benchmark isolado: cliente novo 1.551 ms × reusado 641 ms.
- **Volume:** ~120 mil SELECT/7 dias (86% result cache), ~660 `CREATE TABLE` por dia como
  usuário (ensure sem `lru_cache` em GET), escrita em 5-20 minutos distintos por hora no pico.
- **O cache de agosto quase não acertava:** chave por token (N usuários = N recomputações;
  rotação de token = frio), geração global (qualquer escrita de qualquer um zera tudo), TTL
  5 min e **sem single-flight** (o prefetch dispara ~20 GETs que recalculavam o mesmo
  frontier em paralelo e enfileiravam o warehouse de 1 cluster).

### O que mudou (`backend/main.py`, `egps_atualizados.py`)

| | Mudança |
|---|---|
| Cliente OBO | `_user_client` reaproveitado **por token** (TTL 10 min, teto 64) |
| Cache | `_cache_get` único: chave **compartilhada**, single-flight por (chave, geração), entrada pré-bump nunca apaga a pós-bump, evicção sob lock que tira geração velha antes de esvaziar |
| Autorização | `_sessao()`: `current_user()` + grupos + **prova de leitura** (scalar subquery em `sas_inputs_monitor`) numa query, por token, 5 min. Substitui a identidade na chave e os 3 statements soltos de `me`/`_is_gestao`/`_is_admin` |
| Rodadas seriais | frontier (cascas/novos/vínculos na 1ª onda), `_edges_pruned` (declarados via subquery em `T_CHOICE`), `_blocking` (arestas/candidatos/famílias), `_sanitizacao_derivada` (cons/pend), Tempo por Etapa (4 leituras numa onda) |
| Statements mortos | landing com `FAMILIAS_ON`: 3 seriais só do ramo sem família; `SELECT current_date()` (warehouse é UTC) |
| Sem cache | `_egps_novos` (1 statement até com tudo quente), áreas do `/api/config` |
| Escrita/DDL em GET | `CREATE` de analistas/responsáveis BV com `lru_cache`; log diário da fragilidade 1x/dia por processo |
| Transporte | `GZipMiddleware` (nível 6); `Cache-Control: immutable` em `assets/*`, `no-cache` no `index.html` |

### Medido (app local → schema dev, token OBO no header, `FAMILIAS_SAFRA=1` como prod)

| | Antes | Depois |
|---|---:|---:|
| Rajada da página (26 GETs concorrentes) | 11,7 s | **3,3 s** |
| Soma serial, processo frio | 210 s | **68 s** |
| Soma serial, quente | 72 s | **15 s** |
| `/api/landing` quente | 8,4 s | **0,6 s** |
| `/api/tempo-etapas` | 9,2 s | **0,7 s** |

**Equivalência:** 27 endpoints comparados por hash do JSON canônico — idênticos, exceto os
dois que as correções de bug mudam de propósito (priorização 194→193 = tamanho da linha de
base; 41 antecessores com pré-working preenchido). Números absolutos locais incluem a
latência WSL→Databricks; em prod o piso por statement é menor, o ganho relativo é o que vale.

### Ainda não feito (próximos passos, por ROI)

1. Gerações por domínio (comentário na Gestão não precisa invalidar o grafo).
2. Uma leitura base cacheada de `T_EGP ⋈ T_LINK` (hoje ~8 variantes por geração) e de `T_PIPE`.
3. Mutações em lote: vínculo de família (3 statements por safra), pins (3 por pin), auditoria multi-linha, `recompute_escopo` em MERGE (e atômico — hoje abre janela de escopo vazio).
4. Payload cache de landing/resumo/funis/priorização (exige auditar que toda escrita que eles leem bumpa).
5. Modelo de leitura em memória com write-through + sonda `information_schema.tables.last_altered` (1 statement detecta qualquer escrita externa; medido que acompanha DML na hora).

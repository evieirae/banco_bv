# Onboarding — app `monitoramento-sas` (para sessões de IA: Claude Code / Cursor)

Guia rápido para uma sessão de IA trabalhar neste app **sem repetir os erros já cometidos** nesta linha de trabalho. Leia isto + [`README.md`](../README.md) (sobretudo **§Decisões de design**) antes de mexer.

## O que é

SPA **React + TypeScript (Vite)** no front + **FastAPI** no back, servido como **Databricks App** (1 processo uvicorn). Lê/escreve Delta tables em `bv_dev_db.monitoramento_sas` via **Statement Execution API** (SQL Warehouse). Painel de monitoramento da migração SAS, com **10 abas** (Guia, Resumo, Inputs, Outputs, EGPs, Escopo, Priorização, Histórico + Gestão e Ingestão, estas duas restritas ao grupo `bv_users`; a aba **Linhagem** foi desativada em 2026-07 — view/rotas dormentes, re-habilitar = reinserir o entry em `routes.ts`). A aba **Guia** (`GuiaView.tsx`, 1ª da barra; a inicial segue Resumo) é o onboarding in-app e espelha `GUIA_DO_APP.md` — mudou aba/conceito, atualize os dois. Backend: `backend/main.py`. Front: `frontend/src/`. Bundle compilado: `static/` (é o que o app serve). Guia de uso (visão do usuário): [`GUIA_DO_APP.md`](../GUIA_DO_APP.md).

## Regras duras (NÃO-NEGOCIÁVEIS)

1. **Deploy e escrita em produção exigem consentimento humano explícito.** `databricks apps deploy`, `OPTIMIZE`/`ALTER`/republish em tabelas de prod, qualquer mutação de dado de prod → **pergunte e espere o "ok"**. Aprovação numa vez **não** vale para a próxima.
2. **Nunca `git commit` / `git push` sem o usuário pedir.** Neste repo, commits **não levam** trailer `Co-Authored-By`.
3. **Tabelas de produção: `bv_dev_db.monitoramento_sas`** (catálogo `bv_dev_db`, schema `monitoramento_sas`). **NÃO é `client_journey`** — handoffs antigos erram isso e dá `INSUFFICIENT_PERMISSIONS (USE CATALOG)`.
4. **OBO (on-behalf-of-user):** dentro do app cada query roda como o **usuário logado** (header `X-Forwarded-Access-Token`). Com `REQUIRE_OBO=true` o app **recusa** request sem token (não cai no service principal). Acesso é concedido **por usuário** no Unity Catalog: `USE CATALOG`/`USE SCHEMA`, `SELECT`, `MODIFY`, e `CAN USE` no warehouse.
5. **Segredos:** nunca leia/exiba `.env`/`*.pem`/credenciais.

## Fluxo de deploy (prod = CI/CD na `main`; dev = manual — ver [`docs/DEPLOY.md`](../docs/DEPLOY.md))

**Prod deploya sozinho** no merge para `main` que toque `egps_analysis/app/**` (Bitbucket Pipelines, `bitbucket-pipelines.yml`). O gate humano passou a ser o **merge do PR** — não `databricks apps deploy` na mão. Fallback/local usa os scripts `deploy_prod.sh` (profile bv) e `deploy_dev.sh`. Os comandos crus abaixo são o que os scripts encapsulam:

```bash
# 1. build do bundle (sempre antes do deploy)
cd egps_analysis/app/frontend && npm run build      # gera ../static/

# 2. sync só de app/ + deploy   (profile bv; warehouse 5922c26f81f1bbdd)
WS=/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas
databricks sync /home/.../egps_analysis/app "$WS" --exclude 'frontend/node_modules/**' -p bv
databricks apps deploy monitoramento-sas --source-code-path "$WS" -p bv
```
Sincronizar de `egps_analysis/` (em vez de `app/`) sobe docs/CSVs e **estoura o limite de 10 MB/arquivo**. Logs: `databricks apps logs monitoramento-sas -p bv` (procure linhas `[perf]`).

## Gotchas (cada um já custou tempo)

- **`<base href="/">` em `frontend/index.html` sustenta as rotas aninhadas** (deep-link `/egps/<id>`). O Vite usa `base: "./"` (relativo); **sem** o `<base>`, um cold-load de rota aninhada faz `./assets/...` resolver contra `/egps/` → bundle 404 → página em branco, e quebra os `fetch("api/...")`. **Não remova**; qualquer rota aninhada nova depende dele.
- **`backend/main.py` é grande (~5.6k linhas)** e pode estar **bloqueado para a ferramenta Read** numa sessão (context-guard "already indexed"). Workaround: editar via **subagente** (contexto fresco) ou replace direcionado por script; revisar com `git diff`.
- **Acentos nos status são load-bearing** (`"Em ingestão"`, `"Concluído"`): editar `main.py` via script de replace ASCII que perde acento **quebra o casamento de status** com `pipeline.ts`/dados. Pós-edição, um grep pelas variantes sem acento deve dar 0.
- **Labels de aba ≠ slugs**: as abas foram renomeadas (sem "Monitoramento") mas os **slugs foram preservados** (`/monitoramento`, `/monitoramento-outputs`, `/ondas`) para links salvos — não "arrumar" slug junto com label. `/escopo-migracao` é alias da aba EGPs.
- **`recompute_escopo` existe em 2 cópias** (`main.py` e o espelho dentro de `../../publish_to_databricks.py`) que devem andar juntas: filtro `ativo IS NOT false` + self-heal `faltante`→`exato` (ver README §recompute_escopo). Era 3 até 2026-08, quando o vendor `app/pipeline/` foi removido — não reintroduza a terceira.
- **`pipeline.ts` espelha `main.py`** nas constantes de status/funil (`STATUS_PROJETO`, `PIPELINE_PROJETO`, `SEG`). Mudou num, **sincronize o outro**.
- **`recompute_escopo()`** re-deriva o escopo no app inteiro a cada edição de Escopo **e** invalida o cache de linhagem. Por isso editar o Escopo reflete em Resumo/Monitoramento/EGPs/landing na hora.
- **Toda resposta do `run_sql` vem como string** (Statement Execution API, `JSON_ARRAY`) — converta onde precisar de número/booleano.
- **O hook às vezes dispara "/data:deploying-airflow"** — é **falso positivo** (isto é Databricks App, não Airflow). Ignore.
- O app é **1 processo** (`app.yaml`): cache em memória process-local basta; não assuma múltiplas réplicas.
- **Com `FAMILIAS_SAFRA` ligada, uma linha da aba Inputs pode ser N tabelas.** Nunca derive a chave de escrita do `chave_canonica` da linha: use `chavesDoInput()` (`src/inputs.ts`), que devolve as N safras, e `confirmEscritaFamilia()` antes de gravar — a escrita é **fan-out** e sobrescreve estados divergentes por safra. A resposta de `/api/inputs` traz `grao: "safra" | "familia"`; a UI não deve inferir o grão pela presença de campos.
- **No histórico, `chave_canonica` pode ser só uma safra representante.** `/api/audit` colapsa o fan-out da família (uma edição gravou 39 linhas de auditoria; a tela mostrava 39). Quando `n_safras > 1`, o rótulo certo é `familia` — `chave_canonica` aí é `min()` do grupo, não o nome do que foi editado. `HistoryView` e o drawer mostram "· N cargas"; não some `n_safras` com nada nem use a linha para derivar chave de escrita.
- **Mudou o que uma tela conta? O agente de consulta precisa saber.** As tabelas `sas_consulta_egp`/`_input` (ADR 0004, `backend/consulta.py`) transcrevem o que as telas mostram, com uma coluna `conta_*` por tela; a rotina confere a paridade a cada gravação e **não grava se divergir** (`/api/consulta/status` mostra a divergência). Tela nova ou régua nova: acrescente a coluna e o par em `consulta.confere`, atualize `docs/divergencias-entre-telas.md` e rode `genie/avalia.py`.
- **Pílula de família usa fundo escuro** (`.pill.familia`/`.pill.misto`), como `.pill.homonimo` — pílula clara destoa do tema e some no dark. E, **dentro de `.rsm-card`, nunca use vars de tema** (dá branco-sobre-branco no dark).

## Modelo de dados (rápido)

- `sas_inputs_monitor` — atualizada por **MERGE** no publish, **preservando as colunas humanas** (`status_humano`/`responsavel`/`observacao`/`updated_by`/`updated_at`).
- `sas_egp_pipeline` · `sas_escopo` · `sas_*_audit` — `CREATE IF NOT EXISTS`, **nunca dropadas** (estado humano/auditoria).
- `sas_egp_input_periodo` (profundidade **necessária** por par EGP×família, só gestão) · `sas_familia_ingestao` (profundidade **ingerida** por família, qualquer analista) + auditoria irmã — mesmo regime: criadas pelo backend, **fora do publish**. A família **não** tem linha de estado própria: `familia::cat::NOME` é só chave de transporte na API.
- Tabelas derivadas (edges/nodes/egp_inputs/resumo/funil) — **full-replaced** no publish.
- `escopo_indi` (nos nodes) é **mutado em runtime** por `recompute_escopo()`.
- **Regra de status:** `status_humano` (editado) sempre prevalece sobre `modernizada_auto` (detecção); a divergência é sinalizada (⚠), nunca sobrescrita.

## Por quê das escolhas (o que vira dúvida)

Estão documentadas — **não reinvente, leia**:
- **[`README.md`](../README.md) → Decisões de design:** vocabulário de status (6 valores; por que `Concluído` *e* `Migrado`; `Removido` extinto em 2026-07), funil etapas×status ("banda"), `origem` (6 valores) e **"SAS/Local (externo) = dep. produtor ausente"**, filtros multi-select, deep-links + `<base href>`.
- **[`docs/CLASSIFICACAO_INPUTS_SAS.md`](../../docs/CLASSIFICACAO_INPUTS_SAS.md):** o que conta como input (`table_in`/`file_in`/`script_in`), aresta de dependência, e §8 (coluna `origem` no app + decisão "externo" + homônimos).
- **[`ANALISE_PERFORMANCE.md`](../ANALISE_PERFORMANCE.md):** diagnóstico I/O-bound, vereditos (não trocar de linguagem/framework; DuckDB recusado) e §6 (o que foi implementado).

## Mapa de docs

| Doc | Para quê |
|---|---|
| [`GUIA_DO_APP.md`](../GUIA_DO_APP.md) | **Guia de uso** (visão do usuário): abas, permissões, fluxos do dia a dia, FAQ. |
| [`README.md`](../README.md) | Arquitetura, abas, API, **Decisões de design**, dev/deploy/refresh. |
| [`ANALISE_PERFORMANCE.md`](../ANALISE_PERFORMANCE.md) | Análise de performance + o que foi implementado. |
| [`docs/CLASSIFICACAO_INPUTS_SAS.md`](../../docs/CLASSIFICACAO_INPUTS_SAS.md) | Como um input é classificado; coluna `origem`; "produtor ausente". |
| [`docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`](../../docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md) | Pipeline 01–06 que gera os dados do app. |
| `CLAUDE.md` (raiz do repo) | Guia do monorepo inteiro (sub-projetos, convenções). |

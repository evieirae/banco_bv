# ONBOARDING — sas_assessment_tool (para sessões de IA: Claude Code / Cursor)

Como uma sessão de IA deve começar a trabalhar neste repo **sem repetir erros já cometidos**. Monorepo de tooling de avaliação da migração SAS do BV — veja o [`CLAUDE.md`](CLAUDE.md) da raiz para o mapa completo dos sub-projetos.

## Regras duras (valem para todo o repo)

1. **Deploy e escrita em produção (Databricks/BigQuery) → só com consentimento humano explícito.** Aprovação numa vez **não** vale para a próxima.
2. **Nunca `git commit` / `git push` sem o usuário pedir.** Commits **sem** trailer `Co-Authored-By` — a atribuição de sessão de agentes de IA pede o trailer por padrão, então a regra só vale se você a desobedecer de propósito. Há uma rede de segurança versionada (`.githooks/commit-msg`, remove o trailer), mas `core.hooksPath` é config **local**: num clone novo, rode `git config core.hooksPath .githooks` uma vez.
3. **Nunca leia/exiba segredos** (`.env`, `*.pem`, credenciais).
4. **Não versione binários `.egp`** (já no `.gitignore`) — vêm do tar do Drive (ver `CLAUDE.md` → Setup de dados).

## Trabalho ativo: app `monitoramento-sas` (`egps_analysis/app/`)

Painel React + FastAPI servido como **Databricks App**. Se for mexer nele, leia o guia detalhado: [`egps_analysis/app/frontend/ONBOARDING.md`](egps_analysis/app/frontend/ONBOARDING.md) (regras duras + gotchas) e [`egps_analysis/app/README.md`](egps_analysis/app/README.md) → **Decisões de design** (o porquê das escolhas). Pontos que mais geram dúvida/erro:

- **Tabelas de prod: `bv_dev_db.monitoramento_sas`** (NÃO `client_journey`); profile `bv`; warehouse `5922c26f81f1bbdd`; auth **OBO** (cada query roda como o usuário logado).
- **`<base href="/">` em `frontend/index.html`** sustenta os deep-links de rota aninhada (`/egps/<id>`) — **não remova** (Vite usa `base: "./"`).
- **`frontend/src/pipeline.ts` espelha `backend/main.py`** (constantes de status/funil) — mudou num, sincronize o outro.
- **`backend/main.py` pode estar bloqueado para a ferramenta Read** (context-guard) — edite via subagente/replace direcionado e revise com `git diff`.
- **Deploy de PROD é CI/CD** (Bitbucket Pipelines): merge na `main` tocando `egps_analysis/app/**` → build+sync+deploy automáticos (o gate humano é o merge do PR). **Dev é manual** (`deploy_dev.sh`). Processo/scripts/variáveis: [`egps_analysis/app/docs/DEPLOY.md`](egps_analysis/app/docs/DEPLOY.md). Os scripts (`deploy_prod.sh`/`deploy_dev.sh`) já embutem a guarda anti-corrida do `app.yaml` e a verificação do bundle deployado (um "SUCCEEDED" pode servir código velho); `sync` roda de `app/`.

**Decisões recentes do app (2026-06/07) — não reverter sem ler o [README → Decisões de design](egps_analysis/app/README.md):**

- **`Sanitizado` = removido do escopo, no app inteiro** — fora de **toda** contagem (helper `_sanitizado()` filtra o universo de `metrics`/`landing`/`_egp_readiness_rows`/`migration_scope`/`waves`/`resumo`/funil de ingestão). `_modern`/`_aingerir` **não** mudaram. Continua **visível na lista** do Monitor.
- **Cards do Monitor são client-side** (`cardMetrics`, das linhas filtradas) — `/api/metrics` está **dormente**; não re-religue. Sanitizado entra nos cards só quando o filtro de status o inclui.
- **Escopo `indi_deps` ("Indicium + Dependências")** = base Indicium ∪ deps **transitivas** (mesmo fecho do escopo "+ dependências" da aba EGPs); a **área define a base server-side** (recarrega o dataset), client-side nos outros escopos. `_frontier_egps()` + `/api/scope-egps` (indicador de EGPs no topo).
- **Aba EGPs absorveu "Escopo de migração" (2026-07):** `/api/migration-scope` e `MigrationScopeView` **não existem mais**; tudo em `/api/egp-readiness?scope=indi|indi_deps|base`; slug `/escopo-migracao` é alias.
- **Priorização (ex-Ondas) tem recorte FIXO** (todas as áreas, indi+deps, 400/mês) + **pin de mês** (gestão, absoluto); o **Mês do plano substituiu a "Onda"** em todas as abas (`useMesPlan`, cache compartilhado).
- **Abas renomeadas sem "Monitoramento"** (Inputs/Outputs) com **slugs preservados** (`/monitoramento`, `/monitoramento-outputs`, `/ondas`) — não "arrumar" slug junto com label.
- **Gestão** é a única aba restrita (grupo `bv_users`); edições de status/etapa/responsável são abertas a qualquer usuário logado (OBO + auditoria). As abas **Ingestão** e **Macros** foram removidas em 2026-08 (não eram usadas) — junto com `backend/ingest.py`, `/api/ingest/*`, `/api/macro-files` e o vendor `app/pipeline/`.
- **Funil "migrados" conta por STATUS** (Migrado + Despriorizado e Contabilizado), não por "chegou na última etapa". O status `Removido` foi **extinto** (2026-07, fundido em Despriorizado e Contabilizado); EGP fora do backlog **não puxa dependências exclusivas** (`_egps_fora_backlog` + `no_expand` do BFS — derivado, nunca cascateado), mas segue no plano da Priorização como EGP normal; quem depende dele ganha o aviso ⏸ (`deps_despriorizadas`/`impacto_despriorizado`, propagação transitiva). **Via resolvida não gera dependência (2026-07):** tabela com status efetivo Modernizado/Sanitizado é filtrada das arestas em `_edges_pruned()` (`_vias_resolvidas`+`_filter_vias_resolvidas`) — dependência 100% satisfeita some do app inteiro (frontier, depende_de, bloqueio, priorização); derivado do status, reversível.
- **Gestão de EGPs/Inputs (topo da aba Gestão, 2026-07) é real (Delta):** endpoints `/api/gestao/*` + tabelas `sas_gestao_status`/`sas_gestao_datas` — **fora do publish, nunca dropadas**. **Sem resumo IA** (decisão do usuário: a coluna mostra o texto cru do último status). E-mail de analista é **canonizado para `@indicium.ai`** em toda escrita — nunca duplicar `nome.sobrenome` que já existe com `.tech`.
- **Aba Linhagem desativada (2026-07)** — o grafo não reflete a escolha de produtor canônico; view/rotas `/api/lineage/*` dormentes (re-habilitar = reinserir o entry em `routes.ts`).
- **Versões atualizadas de EGP (2026-09)** — versões novas de `.egp` do cliente em **tabelas próprias** (`sas_egp_atualizados*`), carga só por script local (`egps_analysis/publish_egps_atualizados.py`), backend read-only; **isolamento é de escrita, não de leitura** (prontidão via JOIN vivo com `sas_inputs_monitor` — ver `docs/adr/0001` e README → Decisões). A **aba dedicada foi aposentada** (spec §5): a comparação com o antecessor virou seção do detalhe do EGP, e o chip "📥 Aguardando corpus" (com as pendências) cobre a janela antes da entrada no corpus. Glossário do domínio em `CONTEXT.md` (raiz).
- **Família de safras é a unidade de input (flag `FAMILIAS_SAFRA`, LIGADA em prod desde 17/09/2026)** — safras datadas da mesma tabela contam **1 input** em todas as superfícies; regra única em `backend/familias.py`. O **grafo continua no grão da safra** (linhagem/produtor canônico/casamento input↔output) — **não "simetrizar"**; a guarda dos ≥2 membros é decisão de **corpus**, não do recorte em tela; escrita é **fan-out** para as N safras com auditoria por safra. Ver `docs/adr/0002` e README → Decisões de design.
- **Área "Cobrança" canonizada** (`AREA_CANON` em `publish_to_databricks.py`) — não reintroduzir `Cobranças`/`Cobrança Varejo`.
- **Armadilha light mode:** `--danger-soft` == `--danger` no tema claro; use `--tone-cyc-*` para chips/badges de aviso (nunca `--danger` texto sobre `--danger-soft` fundo).

## Armadilhas da análise (`egps_analysis/`) — decisões contra-intuitivas

Estas escolhas **parecem bug e não devem ser "consertadas"** sem ler o porquê — um "fix" quebra a corretude em silêncio. Índice completo (com links pro racional) no [`CLAUDE.md`](CLAUDE.md) → **"Decisões de design & armadilhas"**. Resumo:

- **Linhagem casa por `(path físico, membro)`, não pelo nome do libname** — o alias é mutável por EGP (mesmo diretório, nomes diferentes). Não reverta para casamento por nome.
- **A recuperação de arestas no `orchestrator_inventory.py` é 100% aditiva** (só adiciona) e **omite de propósito** o guard de membro-genérico do bloco `.sas7bdat` — a chave por path já é restritiva, então o guard só geraria falso-negativo. **Não "simetrize".**
- **Identidade por path AUMENTA a contagem de inputs** (6474→6767), não reduz: mesmo nome em paths diferentes = tabelas distintas, não cópias. Consolidação é esforço à parte e exclui `multi_produtor`.
- **O MERGE do `publish_to_databricks.py` preserva as colunas humanas** (`status_humano`/`responsavel`/`observacao` por `chave_canonica`); identidade física entra como colunas **aditivas** (`paths_fisicos`/`n_paths_fisicos`), nunca colapsando linhas.
- **O extrator exclui `*dtm.json`** (arquivo de conexão) e **colapsa variantes `[SHEET=]`** sem derrubar input legítimo; **inputs de pass-through** (`db..tabela`, tabelas cruas em `JOIN` de subquery) são capturados de propósito (viram "dep. produtor ausente").

## Onde está o quê

| Quer | Veja |
|---|---|
| Mapa do monorepo + convenções | [`CLAUDE.md`](CLAUDE.md) (raiz) |
| **Guia de uso do app** (usuário: abas, permissões, fluxos, FAQ) | [`egps_analysis/app/GUIA_DO_APP.md`](egps_analysis/app/GUIA_DO_APP.md) |
| Guia de IA do app monitoramento-sas | [`egps_analysis/app/frontend/ONBOARDING.md`](egps_analysis/app/frontend/ONBOARDING.md) |
| Decisões de design do app (por quê) | [`egps_analysis/app/README.md`](egps_analysis/app/README.md) → Decisões de design |
| Performance do app | [`egps_analysis/app/ANALISE_PERFORMANCE.md`](egps_analysis/app/ANALISE_PERFORMANCE.md) |
| Classificação de input / coluna `origem` | [`egps_analysis/docs/CLASSIFICACAO_INPUTS_SAS.md`](egps_analysis/docs/CLASSIFICACAO_INPUTS_SAS.md) |
| Pipeline 01–06 que gera os dados | [`egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`](egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md) |
| Armadilhas/decisões da análise (por quê) | [`CLAUDE.md`](CLAUDE.md) → Decisões de design & armadilhas · [`REFAZ_LINHAGEM_PATH.md`](egps_analysis/docs/analises/REFAZ_LINHAGEM_PATH.md) · [`PLANO_CONSOLIDACAO_SASLOCAL.md`](egps_analysis/docs/analises/PLANO_CONSOLIDACAO_SASLOCAL.md) |

# Fix — subcaptura de inputs em pass-through SQL (`egps_extractor.py`)

> **Status:** Fases 0–4 ✅ concluídas (2026-06-19).
> **Cobertura:** `egps_analysis/test_passthrough_inputs.py` (9 casos, todos verdes).
>
> **Resultado da Fase 4 (re-extração 1.742 + re-orquestração):**
> - **224 inputs reais recuperados** (214 qualificados `db.tabela` + 6 crus + 4 macro), **0 falso-positivos** após hardening (o stress-test pegou 2: `JOIN` em literal e FQTN BQ `bv-pdbd-prd` truncando para `BV`).
> - **Gaps do Fabricio (não modernizadas): 36/49 → efetivamente 49/49** (45 match exato + 4 capturadas em forma crua, ex. `VW_DESDOBRAMENTOS` vs `public.vw_desdobramentos`).
> - **Dependências do escopo Cobrança:** arestas 197 → 251 (+54), mas projetos "sem dependência" 81 → 81 (inalterado). **Por quê:** as leituras recuperadas são tabelas-FONTE (Sybase/SQLServer/BQ via pass-through), não datasets SAS intermediários produzidos por outro EGP → não criam aresta intra-corpus. **Confirma** que elas são "dependências de produtor ausente" → próximo passo é a visibilidade no app (categoria distinta).

## Problema

O extrator deixava de capturar como `table_in` algumas leituras dentro de pass-through SQL, escondendo dependências e inputs do plano de migração. Dois padrões confirmados em dados reais.

## Causas-raiz e correções

| # | Falha | Causa | Correção |
|---|---|---|---|
| 1 | `db..tabela` (Sybase, dono omitido) descartado — ex. `dbglobal..VwSistema` | guard `if any(not p.strip() for p in token.split('.'))` em `_register_pass_through_native_table` rejeita o segmento vazio | colapsa pontos consecutivos (`re.sub(r'\.\.+', '.', token)`) antes do guard → `DBGLOBAL.VWSISTEMA`. Malformados reais (`.tab`, `db.`) seguem rejeitados. |
| 2 | tabela em JOIN pendurado num **FROM-subquery** sumia — ex. `FROM (SELECT…) t1 LEFT JOIN VW_DESDOBRAMENTOS …` | o scan de FROM em `_native_sql_from_join_scan` pula `FROM (` (`(?!\()`), então toda a cadeia de JOINs da subquery-FROM era ignorada | scan isolado `\bJOIN\s+(?!\()(tabela)` sobre o fragmento, com literais `'...'` mascarados antes (evita `JOIN` dentro de string) |

## Fases

- **Fase 0 — Reprodução (✅):** `test_passthrough_inputs.py` com os 2 casos reais (`dbglobal..VwSistema` de `Crédito__ProcessoDiario`; `VW_DESDOBRAMENTOS` de `Riscos__1403`). Confirmado RED (falha pelo motivo certo: caso B só capturava `M_ENTIDADE`, perdendo a cadeia de JOIN da subquery).
- **Fase 1 — Fix #1 (✅):** colapso de `db..tabela`. GREEN.
- **Fase 2 — Fix #2 (✅):** scan de JOIN de FROM-subquery. GREEN.
- **Fase 3 — Guardrails anti-falso-positivo (✅):** stress-test adversarial (triple-dot, `server.db..t`, JOIN→subquery, alias pós-JOIN, `JOIN` em literal). Encontrou 1 falso-positivo (`JOIN` dentro de string) → corrigido mascarando literais. 8/8 verde.
- **Fase 4 — Validação ponta-a-ponta (PENDENTE):** re-extrair os 1.742 `.egp` → `git diff` dos `.txt` (golden-file = versão commitada `e2e9f5b`) para confirmar que só surgem inputs novos legítimos; re-rodar `orchestrator_inventory.py`; re-medir o escopo Cobrança (os **81 "sem dependência"** devem cair). Custo: ~7 min extração + ~5 min orquestrador.

## Validação de regressão

Golden-file = os `.txt` commitados em `e2e9f5b`. Após re-extração, `git diff --stat egps_analysis/text_egps` deve mostrar **apenas adições de inputs** (tabelas recuperadas), sem alterar o resto. Amostrar as novas linhas para confirmar que são tabelas reais (não aliases/colunas).

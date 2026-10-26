# Produtor canônico (revisão da ambiguidade) — Implementation Plan

> Spec: `docs/superpowers/specs/2026-07-07-produtor-canonico-design.md`. Construir e testar no **dev** (`monitoramento-sas-dev`, schema `bv_dev_db.monitoramento_sas_dev`) antes de prod. `main.py` é Read-bloqueado → editar via **patch scripts** (anchor único + `py_compile` + check de acentos). Frontend via Edit. `publish` (+ vendored `app/pipeline/`) em sincronia.

**Goal:** escolher o produtor correto de um output multi-produtor poda o grafo (frontier/bloqueio/priorização na hora; ondas no Processar), persistido.

**Architecture:** tabela `sas_output_producer_choice` (output→produtor). Backend: endpoints de save/clear + `_prune_edges(rows, choices)` aplicado em todo caminho que lê `sas_lineage_edges`; cache invalidado como `recompute_escopo`. Publish poda o report 03 antes de agregar. Frontend: aba Outputs (filtro multi + radio no drawer).

---

### Task 1 — Backend: constante + helpers de escolha/poda (main.py)

**Files:** Modify `app/backend/main.py` (perto de `T_ESC` ~66; perto de `_dep_of_map` ~1230).

- [ ] Adicionar constante `T_CHOICE = f"{FQ}.sas_output_producer_choice"` junto das outras (~66).
- [ ] Adicionar helper `_producer_choices()` — lê `SELECT chave_canonica, projeto_escolhido FROM {T_CHOICE}` (tolera tabela ausente → `{}`), cacheado por geração de linhagem (reusa `_cache_lineage` / mesma key de invalidação).
- [ ] Adicionar helper puro `_prune_edges(rows, choices)`:
```python
def _prune_edges(rows, choices):
    """rows: dicts com projeto_alvo, depende_do, via_tabelas. Remove via T de arestas
    cujo produtor != choices[T]; descarta aresta sem vias. Self-heal: só honra choices[T]
    se choices[T] for produtor atual de T nas rows."""
    if not choices:
        return rows
    prod_by_via = {}
    for e in rows:
        for t in (e.get("via_tabelas") or "").split(" | "):
            t = t.strip()
            if t: prod_by_via.setdefault(t, set()).add(e["depende_do"])
    eff = {t: p for t, p in choices.items() if p in prod_by_via.get(t, ())}
    if not eff: return rows
    out = []
    for e in rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        keep = [t for t in vias if not (t in eff and eff[t] != e["depende_do"])]
        if keep:
            out.append({**e, "via_tabelas": " | ".join(keep)})
    return out
```
- [ ] `py_compile` + check acento (`grep -Fc 'Autenticação de usuário ausente' == 1`).

### Task 2 — Backend: aplicar poda nos caminhos de grafo (main.py)

**Files:** Modify `app/backend/main.py` (`_dep_of_map` ~1230; `_blocking` ~1346; `_frontier_egps` ~1263; priorização).

- [ ] Em cada ponto que faz `run_sql("SELECT projeto_alvo, depende_do[, via_tabelas] FROM {T_ED}...")` para montar grafo, envolver com `_prune_edges(rows, _producer_choices())`. Incluir `via_tabelas` no SELECT onde hoje só pega alvo/dep (o prune precisa das vias).
  - `_dep_of_map` recebe rows já podados (ajustar chamadas em `_frontier_egps` 1278, `/api/landing` 779, `_blocking` 1352/1373).
- [ ] `_blocking._produce`: aplicar prune nas `edges` antes de derivar `produced`/`dep_of`/`cons_map`.
- [ ] `py_compile` + acento.

### Task 3 — Backend: endpoints de escolha (main.py)

**Files:** Modify `app/backend/main.py` (perto de `/api/output` ~633 e do bloco de patch/escopo).

- [ ] DDL idempotente no startup (ou lazy): `CREATE TABLE IF NOT EXISTS {T_CHOICE} (chave_canonica STRING, projeto_escolhido STRING, chosen_by STRING, chosen_at STRING) USING DELTA`.
- [ ] `POST /api/output-producer` (body `chave_canonica`, `projeto_escolhido`): valida que o projeto está em `SELECT projeto FROM {T_EGP_OUT} WHERE chave_canonica=?`; `DELETE`+`INSERT` na T_CHOICE com `current_user()`; `global _lineage_gen; _lineage_gen += 1; _lineage_cache.clear()`.
- [ ] `DELETE /api/output-producer?chave=`: apaga a linha + bump.
- [ ] `GET /api/output`: incluir `produtor_escolhido` (lookup na T_CHOICE).
- [ ] `GET /api/outputs`: por linha, `n_produtores` + `produtor_escolhido`; query param `only_multi` (default false).
- [ ] `py_compile` + acento.

### Task 4 — Publish: preservar tabela + podar report 03 (publish + vendored)

**Files:** Modify `publish_to_databricks.py` + `app/pipeline/publish_to_databricks.py` (bloco de edges ~458; DDL/apply).

- [ ] `CREATE TABLE IF NOT EXISTS {T_CHOICE}` no apply (nunca dropa).
- [ ] Carregar `choices = {chave: projeto}` da T_CHOICE; aplicar a **mesma poda** (com self-heal) nas linhas do report 03 antes de `edges[(alvo,dep)].add(t)`.
- [ ] `py_compile` + `diff -q` source vs vendored.

### Task 5 — Frontend: api + tipos

**Files:** Modify `app/frontend/src/api.ts`, `types.ts`.

- [ ] `api.setOutputProducer(chave, projeto)` (POST) + `clearOutputProducer(chave)` (DELETE).
- [ ] `outputs(scope, area, onlyMulti?)` e `output(chave)` carregam `n_produtores`/`produtor_escolhido`.
- [ ] Tipos: `OutputRow` ganha `n_produtores`, `produtor_escolhido`; `OutputDetail` ganha `produtor_escolhido`.

### Task 6 — Frontend: UI (OutputsView + OutputsDrawer)

**Files:** Modify `app/frontend/src/components/OutputsView.tsx`, `OutputsDrawer.tsx`.

- [ ] OutputsView: toggle "só multi-produtor" (usa `onlyMulti`) + badge `n_produtores`/✓ escolhido na tabela.
- [ ] OutputsDrawer: lista de produtores como radio "produtor correto"; `useMutation` setOutputProducer/clear; otimista; `onSettled` invalida `["outputs","egp-readiness","funis","priorizacao","landing"]`. Botão "limpar escolha". Marca produtores podados.
- [ ] `npm run build` (gera `static/`).

### Task 7 — Deploy dev + testes

- [ ] `! databricks auth login --profile bv` já feito. `cd app && bash deploy_dev.sh`.
- [ ] Teste manual no dev: abrir output multi-produtor → escolher produtor → conferir na hora: frontier indi_deps muda (via `/api/scope-egps` ou aba EGPs), aresta podada. Limpar → volta.
- [ ] Verificação de dados (script): antes/depois da escolha, contar arestas ambíguas e o frontier.
- [ ] (Opcional) Processar no dev → ondas consistentes; escolha preservada.

## Self-review
- Cobertura spec: §4→T1/T3/T4; §5→T1/T2; §6→T3; §7→T4; §8→T5/T6; §9 self-heal→T1. OK.
- Consistência: `_prune_edges`/`choices`/`T_CHOICE`/`produtor_escolhido` iguais em backend+publish+front.
- Read-block: main.py via patch scripts; publish via patch (source+vendored); frontend via Edit.

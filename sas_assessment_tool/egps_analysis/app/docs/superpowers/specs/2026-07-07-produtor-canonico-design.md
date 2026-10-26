# Produtor canônico — revisão humana da ambiguidade de dependência — Design Spec

- **Data:** 2026-07-07
- **Sub-projeto:** 2 de 2 (em cima do sub-projeto 1, que expôs a ambiguidade: `max_produtores` nas arestas).
- **App:** `monitoramento-sas` — construído e testado primeiro no **dev** (`monitoramento-sas-dev`).
- **Status:** design aprovado ("Marcar + podar o grafo", efeito "na hora").

## 1. Objetivo

Quando um output é produzido por vários EGPs, dar ao time uma forma de **ver os produtores candidatos e escolher o correto**, e essa escolha **poda o grafo**: o produtor escolhido vira A dependência daquele output; os demais candidatos são descartados do fecho. Efeito **imediato** em frontier/bloqueio/priorização (query-time); **ondas** só no próximo Processar.

## 2. Alinhamento de chaves (validado nos dados do dev)

- `sas_egp_outputs.chave_canonica` = nome canônico do output, ex. `INSIGHT.TBBRUTA` (lib.member upper, **sem prefixo**).
- `sas_lineage_edges.via_tabelas` = **mesmo espaço** (ex. `INSIGHT.TBBRUTA`) — join direto, **sem reconciliação**.
- `sas_egp_inputs.chave_canonica` = **prefixado** `tabela::INSIGHT.TBBRUTA` (strip do `tabela::` quando precisar cruzar; não é necessário no caminho de poda).

A escolha é keyed pelo **nome canônico do output** (= `via_tabela`). Os produtores candidatos de um output = `sas_egp_outputs.projeto` daquele `chave_canonica` (é o que o drawer `/api/output` já lista).

**Escopo da escolha: GLOBAL por output** (um produtor correto por tabela, vale pra todos os consumidores). Per-(consumidor, output) fica fora de escopo.

## 3. Dimensionamento (dev)

- Outputs multi-produtor (>1 EGP produz): **6.176**.
- Arestas ambíguas (`max_produtores>1`): **2.942**.
- Superfície de revisão que **afeta a migração** = outputs multi-produtor **consumidos** (aparecem como `via_tabela`): **~162 tabelas** (as do sub-projeto 1). Outputs multi-produtor não-consumidos podem ser listados mas não têm aresta pra podar.

## 4. Modelo de dados

Nova tabela `sas_output_producer_choice`:
```
chave_canonica STRING   -- output (espaço sas_egp_outputs / via_tabela)
projeto_escolhido STRING -- produtor correto
chosen_by STRING, chosen_at STRING
```
- Grão = 1 linha por output com escolha. Sem linha = comportamento atual (todos candidatos).
- **Preservada no Processar** (o publish nunca dropa/sobrescreve — igual `sas_escopo`/colunas humanas). Criada via DDL idempotente (`CREATE TABLE IF NOT EXISTS`) no publish e no backend.

## 5. Poda do grafo (na hora — query-time, no backend)

Helper `_producer_choices()` → `{output_key: projeto_escolhido}` (cacheado por OBO+geração, invalidado no save).

Filtro aplicado onde o grafo é lido a partir de `sas_lineage_edges` (`_dep_of_map`, `_blocking`, `_frontier_egps`, priorização). Para cada aresta `(alvo, dep, via_tabelas)`:
```
vias_restantes = [T for T in split(via_tabelas, ' | ')
                  if not (choices.get(T) and choices[T] != dep)]
# mantém (C -> P* via T) porque choices[T]==dep; remove T de (C -> P_outro)
if not vias_restantes: descarta a aresta
```
Um helper único `_prune_edges(rows, choices)` é aplicado nas funções que leem arestas, pra a poda ser consistente em todo o app. Sem escolha → nada muda.

**Self-heal (evita órfão):** `_prune_edges` primeiro deriva `produtores_por_via` das arestas e só honra `choices[T]` se `choices[T]` for de fato um produtor atual de `T` nas arestas; senão ignora a escolha (trata como sem escolha). Assim uma escolha obsoleta (produtor deixou de produzir `T` após reprocessar) não descarta todas as arestas de `T`. Mesmo guard no publish (§7).

`_producer_choices()` reusa o cache de linhagem (mesma invalidação): salvar/limpar uma escolha faz `_lineage_gen += 1` + `_lineage_cache.clear()` (idêntico a `recompute_escopo`/`patch_input`), então frontier/bloqueio/priorização refletem na hora.

## 6. Backend — endpoints (`main.py`)

- `POST /api/output-producer` `{chave_canonica, projeto_escolhido}` → valida que `projeto_escolhido` está entre os produtores do output (`sas_egp_outputs`); upsert (MERGE/DELETE+INSERT) em `sas_output_producer_choice` com `current_user()`; bump de cache. `DELETE /api/output-producer?chave=` → remove a escolha.
- `GET /api/output` (drawer): passa a devolver `produtor_escolhido` além de `produtores`/`consumidores`.
- `GET /api/outputs` (lista): cada linha ganha `n_produtores` (contagem distinta de `sas_egp_outputs.projeto`) + `produtor_escolhido`; aceita `only_multi=true` pra filtrar os ambíguos.

Reusa `sql_lit`, o padrão de cache/invalidação de `recompute_escopo`, e `_dep_of_map`/`_transitive_upstream` existentes.

## 7. Publish (ondas consistentes) — `publish_to_databricks.py` (+ vendored)

- `CREATE TABLE IF NOT EXISTS sas_output_producer_choice` (nunca dropa — preserva a escolha).
- Antes de agregar as arestas do report 03, aplica a **mesma poda** usando a tabela de escolha (remove linhas `(alvo, dep, T)` onde `choice[T]` existe e `≠ dep`). Assim `sas_lineage_edges`, `ciclo_id`, `onda` e `resumo` já nascem podados no próximo Processar.
- Mantém a coluna `max_produtores` (sub-projeto 1); uma aresta resolvida por escolha passa a ter só o produtor correto (deixa de ser ambígua no grafo publicado).

## 8. Frontend — UI (aba Outputs)

- **Lista:** toggle "só multi-produtor" + badge `n_produtores` (e marca ✓ quando já tem escolha).
- **Drawer:** a lista de `produtores` vira **selecionável** (radio "produtor correto"); salvar (`api.setOutputProducer`) marca o escolhido, mostra os demais como "podados" e um botão "limpar escolha". Otimista + `onSettled` reconcilia.
- Após salvar/limpar, invalida `["outputs"]`, `["egp-readiness"]`, `["funis"]`, `["priorizacao"]`, `["landing"]` (mesmo conjunto do fluxo de escopo em `IndiciumView`).
- `api.ts`: `setOutputProducer(chave, projeto)` / `clearOutputProducer(chave)`; `outputs`/`output` passam a carregar os campos novos.

## 9. Casos de borda

- **Sem escolha:** comportamento atual (todos os candidatos; aresta ambígua).
- **Escolha obsoleta** (produtor escolhido deixou de produzir o output após um reprocessamento): a poda simplesmente não casa nenhum `dep` → a aresta escolhida some, mas as outras também são podadas (choice[T]≠dep) → output ficaria sem produtor no grafo. Mitigação: no save, validar contra `sas_egp_outputs` atual; e o publish faz **self-heal** — se `projeto_escolhido ∉ produtores(T)`, ignora a escolha (trata como sem escolha) e opcionalmente marca pra re-revisão.
- **Output com 1 produtor:** UI não oferece escolha (nada a resolver).
- **`only_multi`** default false (não muda o comportamento atual da lista).

## 10. Fora de escopo

- Escolha per-(consumidor, output) (fica global por output).
- Poda das ondas na hora (ondas seguem publish-time; foi a decisão).
- Sugestão automática do "produtor provável" (poderia ser follow-up: default = produtor no escopo Indicium, ou o de maior fan-out).

## 11. Critérios de aceitação

- Salvar um produtor correto pra um output multi-produtor: frontier indi_deps / bloqueio / priorização refletem **na hora** (arestas dos não-escolhidos podadas).
- Drawer mostra o escolhido; lista filtra/badgeia multi-produtor; limpar escolha volta ao estado ambíguo.
- Escolha **persiste** após Processar; ondas ficam consistentes pós-Processar.
- `main.py`/frontend/publish + vendored em sincronia; testado no **dev** antes de prod.
- Sem escolha → app idêntico ao atual.

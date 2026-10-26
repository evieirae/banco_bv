# Escopo "Indicium + Dependências" nos Outputs — Design Spec

- **Data:** 2026-07-06
- **App:** `monitoramento-sas` (`egps_analysis/app/`)
- **Status:** design aprovado pelo usuário ("Sim")

## 1. Objetivo

Adicionar a opção de escopo **"Indicium + Dependências"** (`indi_deps`) na aba **Monitoramento Outputs**, espelhando o que já existe na aba de Inputs. Escopo puramente aditivo — **sem mudança de dados/publish** (nada a repopular).

## 2. Semântica (upstream, consistente com o resto do app)

`indi_deps` em todo o app = **Indicium base (da área) ∪ produtores transitivos** (fecho **upstream** via `sas_lineage_edges`), computado por `_frontier_egps("indi_deps", area)` → retorna `(frontier, base)`.

Para **outputs**: `indi_deps` = **os outputs produzidos por todos os EGPs do frontier** = os outputs do escopo Indicium **+ as tabelas intermediárias que a cadeia de dependências produz para alimentar esse escopo**. É o análogo exato da aba de Inputs (lá: inputs consumidos pelo frontier; aqui: outputs produzidos pelo frontier). A **área** selecionada define a base do fecho **server-side** (igual ao Monitor).

Decisão deliberada: usar o **mesmo frontier upstream** de Inputs/Escopo de migração/Resumo — não um fecho downstream — para manter a coerência do app. `escopo_indi` (coluna de `sas_outputs_monitor`) continua sendo só o Indicium base (para o filtro `indi`); `indi_deps` é **computado por request** (cacheado), não persistido → nenhum republish necessário.

## 3. Backend (`main.py`, espelha `/api/inputs`)

Dois endpoints ganham `scope=indi_deps` + `area: list[str] = Query(default=[])`:

- **`/api/outputs`**: se `scope=="indi_deps"`, computa `frontier, _ = _frontier_egps("indi_deps", area)` e devolve
  `SELECT <9 cols> FROM sas_outputs_monitor WHERE chave_canonica IN (SELECT DISTINCT chave_canonica FROM sas_egp_outputs WHERE projeto IN (<frontier>)) ORDER BY qtd_consumidores DESC, artifact`.
  Cacheado via `_cache_scope_dataset("outputs:indi_deps:" + "|".join(sorted(area)), …)`. Frontier vazio → `rows=[]`. Escopos `indi`/`base` inalterados (`WHERE escopo_indi = true` / sem filtro).
- **`/api/outputs-egps`**: se `scope=="indi_deps"`, `SELECT chave_canonica, projeto FROM sas_egp_outputs WHERE projeto IN (<frontier>)` (para o export explodido). Senão, comportamento atual.

Reusa helpers existentes: `_frontier_egps`, `_transitive_upstream`, `_dep_of_map`, `_cache_scope_dataset`, `sql_lit`. `T_OUT=sas_outputs_monitor`, `T_EGP_OUT=sas_egp_outputs`. Read-only (nenhuma escrita).

## 4. Frontend (`OutputsView.tsx` + `api.ts`)

- Seletor de escopo ganha a 3ª opção **"Indicium + Dependências"** (`indi_deps`), entre "Indicium" e "Base".
- Quando `scope==="indi_deps"`, as áreas selecionadas (o multi-select de área já existente) passam **para o servidor** (definem a base do fecho) e entram na **chave do React Query** — igual ao `depsArea` do `MonitorView`. Nos escopos `indi`/`base`, a área continua filtro **client-side**.
- `api.outputs(scope, area=[])` e `api.outputsEgps(scope, area=[])` passam a aceitar `area` (append de `area` na querystring), como `api.inputs`/`api.inputsEgps`.
- Drawer (`/api/output`) e export CSV (reusa `csv.ts`) funcionam sem mudança — o export continua explodindo por produtor via `api.outputsEgps(scope, area)`.

## 5. Fora de escopo

- Nenhuma mudança em `publish`/pipeline/tabelas Delta.
- Fecho downstream (não é o conceito de `indi_deps` do app).
- Indicador de "EGPs no recorte" tipo `/api/scope-egps` na aba Outputs (não pedido; pode ser follow-up).

## 6. Critérios de aceitação

- Seletor de escopo dos Outputs tem 3 opções; "Indicium + Dependências" carrega os outputs do frontier (Indicium ∪ produtores upstream), com a área definindo a base.
- Trocar de área em `indi_deps` refaz a query (área na chave de cache).
- Export CSV em `indi_deps` sai com os pares output→produtor do frontier (nome do EGP sem prefixo de área).
- `indi`/`base` inalterados; nenhum republish necessário.
- `tsc` limpo; endpoints respondem (tolerando `sas_outputs_monitor` ausente, como hoje).

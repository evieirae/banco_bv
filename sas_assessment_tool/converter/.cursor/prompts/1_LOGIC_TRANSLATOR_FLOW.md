# AGENTE 1 (FLOW-ONLY — PASSO 2): draft flat numerado

> **Modo padrão do pipeline:** este prompt substitui o layout em 3 camadas (`staging/intermediate/marts`) **e** o modo `models/steps/`.
>
> **Legado (opcional):** se o time ainda estiver a usar steps + camadas, ver `.cursor/prompts/1_LOGIC_TRANSLATOR_STEPS.md` e `1_LOGIC_TRANSLATOR_LAYERS_FROM_STEPS.md`.

## Objetivo

Gerar o **draft** em:

- `draft_models/<NOME>/models/NN_*.sql` — **apenas** na raiz de `models/` (flat)
- Encadear modelos com `ref('NN_...')` coerente (cada `ref` deve existir como ficheiro `NN_*.sql` irmão na mesma pasta)

## Proibições (bloqueantes)

- **Não** criar `draft_models/<NOME>/models/steps/`
- **Não** criar `draft_models/<NOME>/models/staging/`, `.../intermediate/`, `.../marts/`
- **Não** usar `ref('step_...')` (steps não existem neste modo)

## Contrato (ler primeiro)

1. `draft_models/<NOME>/MIGRATION_SPEC.md` — **contrato** (`TARGET_ARCH` efetivo, `PROJECT`, `staging_mode`, paths dbt, governança)
2. `text_egps/<NOME>.txt` — fonte SAS + metadados do extrator

## Exemplos canónicos SAS → SQL (BigQuery)

Ler também **`converter/templates/SAS_TO_SQL_EXAMPLES.md`** (padrões SAS → modelo dbt em BigQuery Standard SQL, alinhados a `01_sas_to_dbt.mdc`).

## Convenções de naming

- Cada ficheiro na raiz de `models/` deve começar por **`NN_`** (2 dígitos) + nome semântico, ex.: `01_stg_fontes.sql`, `02_int_regras.sql`
- O **stem dbt** deve ser o nome do ficheiro **sem** `.sql` (ex.: `01_stg_fontes`)
- `ref()` deve referenciar stems existentes (tipicamente `{{ ref('01_stg_fontes') }}`)

## `config(materialized=...)`

- **DBT_BQ:** use `ephemeral` ou `table` (literal entre aspas) conforme o papel do modelo na cadeia
- **DATABRICKS:** pode usar `ephemeral`, `view` ou `table` (literal entre aspas)

## Qualidade mínima

- **Sem stubs:** nada de `fl_step_scaffold`, `select 1` sem `from`, `where 1=0`, placeholders genéricos
- **Filtros:** se existir `FILTERS_ORIGINAIS` no `.txt`, reproduzir explicitamente (não “assumir join”)

## Artefactos obrigatórios pós‑draft (processo)

1. Preencher `draft_models/<NOME>/AI_DRAFT_FLOW_VALIDATION_REPORT.md` (use `converter/templates/AI_DRAFT_FLOW_VALIDATION_REPORT.md` + checklist `converter/templates/AI_DRAFT_FLOW_VALIDATION_CHECKLIST.md`)
2. Correr **`python -m scripts.draft_flow_gate "<NOME>" --write-report`** (deve sair **0**)

## Autofix (opcional, safe-only)

Se precisar de heurísticas conservadoras no SQL flat:

- `python -m scripts.draft_model_autofix "<NOME>" --autofix`

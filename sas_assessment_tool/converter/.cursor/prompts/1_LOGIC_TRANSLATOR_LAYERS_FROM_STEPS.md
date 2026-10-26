# AGENTE 1 (PASSO 2B): CAMADAS A PARTIR DE STEPS (DBT / BIGQUERY)

## Quando usar

Use este prompt **após** o PASSO 2A (steps-only) já ter sido executado e validado, quando o objetivo for gerar o draft canônico em camadas **derivado** dos steps.

Pré-requisitos (na pasta `converter/`):

- `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report` retornou **0**
- Existem ficheiros em `draft_models/[NOME_SEM_EXT]/models/steps/*.sql`
- Existe `draft_models/[NOME_SEM_EXT]/STEP_MANIFEST.json`

## Contexto

No PASSO 2A você garantiu **paridade mecânica**: 1 modelo por passo SAS em `models/steps/`.
Agora, no PASSO 2B, você deve gerar o draft canônico (`staging/ intermediate/ marts`) **a partir** desses steps (fonte de verdade), sem “retraduzir do zero” direto do `.txt`.

## Inputs (ler primeiro)

- `draft_models/[NOME_SEM_EXT]/MIGRATION_SPEC.md`
- `draft_models/[NOME_SEM_EXT]/STEP_MANIFEST.json`
- `draft_models/[NOME_SEM_EXT]/models/steps/*.sql`
- `text_egps/[NOME_SEM_EXT].txt` (apenas para tirar dúvidas de semântica; o grafo base é o manifest/steps)

## Objetivo

Criar (ou completar) em `draft_models/[NOME_SEM_EXT]/models/`:

- `models/staging/` (≥ 1 ficheiro)
- `models/intermediate/` (≥ 1 ficheiro)
- `models/marts/` (≥ 1 ficheiro)

Respeitando as regras do `@01_sas_to_dbt.mdc` e o contrato do `MIGRATION_SPEC.md`.

## Regra central (fonte de verdade)

- Cada modelo de camada deve ter rastreabilidade explícita para steps:
  - Preferir `{{ ref('<stem_do_step>') }}` em CTEs, quando fizer sentido.
  - Documente no topo do modelo quais steps ele cobre (lista de `ref`s).
- Se algum step ainda for “placeholder funcional”, você pode:
  - Encapsular em `intermediate` e manter um mart fino
  - Mas não apague steps nem renomeie stems.

## Estratégia prática (recomendada)

1. **Agrupar steps em blocos**:
   - `staging`: leituras de fonte (quando o step é claramente “leitura base” ou wrapper)
   - `intermediate`: joins, transformações, dedupe, cálculos
   - `marts`: saídas finais (exports / librefs permanentes / PERMANENT OUTPUTS)

2. **Montar CTEs por step**:
   - Um modelo `int_*` pode ser literalmente um “pipeline” que encadeia vários `step_*` por CTEs.
   - Evite duplicar SQL pesado: o step já tem a lógica; a camada deve orquestrar.

3. **Materialization (Draft)**
   - Em cada ficheiro de `staging/`, `intermediate/`, `marts/`, inclua `{{ config(materialized='...') }}` com literal permitido pelo `draft_gate`.
   - Para BQ: staging normalmente `ephemeral`, intermediate e marts `table` (conforme regras do repositório).

4. **YAML irmão (DBT_BQ)**
   - Para cada `.sql` em `intermediate/` e `marts/`, crie o `stem.yml` irmão mínimo (o `draft_gate` cobra paridade).

5. **Filtros**
   - Se existir `_FILTROS_APLICADOS.md` do step-level, preserve-os nas camadas correspondentes.

## Fecho (gate obrigatório)

Ao final, rode (na pasta `converter/`):

- `python -m scripts.draft_gate "[NOME_SEM_EXT]" --write-report`

Corrija até retornar exit code 0.


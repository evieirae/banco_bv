# AI_VALIDATION_CHECKLIST (obrigatório)

Este checklist é **obrigatório** mesmo quando todos os scripts/guardrails passam.  
O objetivo é capturar “anomalias plausíveis” que passam em validações mecânicas, mas quebram a intenção do pipeline.

## PASSO 2A — Steps (`draft_models/<egp>/models/steps/`)

### 2A.1 DATA step (obrigatório)
- Se o `sas_excerpt` contiver transformação (ex.: `if/then/else`, atribuições `x=...;`, `keep/drop/rename`, `format/length`), o step SQL deve conter **expressões** compatíveis:
  - `case when ... then ... else ... end as ...`
  - casts/normalizações necessárias
  - colunas novas/alteradas refletindo o SAS
- **Falha** se o step for só `select *` (ou `select * from prev`) sem nenhuma expressão nova quando o SAS tem transformação.

### 2A.2 PROC SQL / passthrough (obrigatório)
- Se o `sas_excerpt` contiver `FROM CONNECTION TO ... ( ... )`, o step deve conter o SQL **completo** (sem truncamento e sem stub).
- Se houver split (`__partNN.sql`), validar:
  - `<stem>.sql` existe e orquestra/representa o step
  - `__partNN.sql` têm cabeçalho `parent_step` e são SQL válido
- **Falha** se houver `trecho truncado` ou step “stub” (metadados apenas).

### 2A.3 Dependências (`ref('step_...')`) (obrigatório)
- `ref('step_...')` só deve existir quando há **leitura explícita** de dataset anterior no `sas_excerpt` (`set`, `data=`, `from <dataset>`, etc.).
- **Falha** se houver `ref('step_...')` “gratuito” em step sem dependência.

### 2A.4 DATA _NULL_ (exceção controlada)
- Pode ser “no-op documentado”, mas deve explicar:
  - quais macros/variáveis foram definidas
  - onde são usadas
  - como representar em BigQuery (ex.: `{% set var_* %}`, `current_date()`)

## PASSO 3A — Sandbox (`converted_egps/<DATA>_<sha>_dbt/<egp>/models/` ou legado `converted_egps/dbt/<egp>/models/`)

### 3A.1 Staging (obrigatório)
- Staging é “primeira conexão / 1 fonte”.
- **Falha** se existir `join` em qualquer `models/staging/*.sql`.
- **Falha** se `models/staging/*.sql` tiver mais de 1 upstream (`source`/`ref`).

### 3A.2 Passthrough (obrigatório, quando existir)
- `models/staging/`: conter **apenas** tabelas-base (1 `stg_*` por tabela).
- `models/intermediate/`: conter o SQL inteiro do passthrough reescrito sobre `ref('stg_*')`.

### 3A.3 Proibição de `ref('step_')` no sandbox (obrigatório)
- **Falha** se existir `ref('step_')` em qualquer arquivo do sandbox.

### 3A.4 Marts (obrigatório)
- **Outputs como fonte de verdade**: 1 mart por output real do SAS (exports / libref permanente / `PERMANENT OUTPUTS`).
- **Não-duplicação**: duas marts com a mesma query/origem (diferença só alias/CTE) é **falha**.


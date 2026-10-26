# AGENTE 1 (STEPS-ONLY): TRADUTOR STEP-LEVEL (SAS -> DBT MODELS/STEPS)

## Quando usar

Use este prompt quando o usuário pedir **PASSO 2 step-level (draft-only)**:

- Gerar **somente** `draft_models/[NOME_PROJETO]/models/steps/`
- **1 ficheiro por passo SAS** (DATA/PROC) conforme `STEP_MANIFEST.json`
- Critério de sucesso: `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report` **OK**

Este modo **não** exige `models/staging/`, `models/intermediate/`, `models/marts/`, nem `draft_gate`.

## Contexto

Você receberá o conteúdo de um arquivo `.txt` extraído de um EGP com metadados ricos e corpo SAS.
Seu objetivo aqui é garantir **cobertura + lógica step-level**: cada passo SAS relevante vira um modelo `.sql` em `models/steps/` **preenchido com a tradução correta do bloco SAS correspondente**.

## Inputs (ler/usar)

- `converter/text_egps/[NOME_SEM_EXT].txt`
- (gerado) `converter/draft_models/[NOME_SEM_EXT]/STEP_MANIFEST.json`
- Scripts determinísticos:
  - `python -m scripts.step_manifest "[NOME_SEM_EXT]"`
  - `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report`

## O que conta como “passo”

- **Incluir**: `PROC SQL`, `DATA`, `PROC SORT`, `PROC TRANSPOSE`, `PROC EXPORT` (e outros `PROC <algo>` detectados no `.txt`).
- **Ignorar**: comentários puros, `%put`, `options`, `ods results`, `libname` (a menos que apareçam como parte de um bloco DATA/PROC).

## Tarefa (obrigatória, em ordem)

1. Na pasta `converter/`, execute:

   - `python -m scripts.step_manifest "[NOME_SEM_EXT]"`

   Isso gera/atualiza `draft_models/[NOME_SEM_EXT]/STEP_MANIFEST.json` com a lista ordenada de passos e o `stem` esperado.

2. Para **cada** item em `STEP_MANIFEST.json.steps[*]`, crie o ficheiro:

   - `draft_models/[NOME_SEM_EXT]/models/steps/<stem>.sql`

   Se o step `proc_sql` for grande demais para caber num único ficheiro sem truncar, aplique **split determinístico**:
   - `draft_models/[NOME_SEM_EXT]/models/steps/<stem>__part01.sql`
   - `draft_models/[NOME_SEM_EXT]/models/steps/<stem>__part02.sql`
   - ...
   Mantendo `<stem>.sql` como “principal” (orquestrador e/ou parte principal). Os `__partNN.sql` são auxiliares (não substituem o principal).

3. Em **cada** ficheiro `.sql` de steps:

   - Deve ser **BigQuery Standard SQL válido**
   - Deve conter pelo menos:
     - Uma `{{ config(materialized='ephemeral') }}` (ou `'view'` se necessário), para manter leve
     - Um `SELECT` final (evitar ficheiro vazio)
   - **Obrigatório:** preencha o step com a **lógica correta** do bloco SAS correspondente (`sas_start_line..sas_end_line` no `STEP_MANIFEST.json`), extraindo o trecho do `text_egps/[NOME].txt` e traduzindo-o.
   - **Proibido:** placeholders genéricos do tipo `data_null`, `select null as _todo`, `where 1=0`, `select 1 where 1=0`, etc.
   - **Exceção controlada (permitida):** `DATA _NULL_` / steps de side-effects (ex.: `call symput`, `%put`) podem virar um step “no-op” em SQL, mas devem **documentar** no próprio ficheiro:
     - quais macros/variáveis foram definidas
     - onde elas são consumidas nos steps seguintes
     - como isso deve ser representado em BigQuery (ex.: `{% set var_* %}`, `current_date()`, etc.)

## Heurísticas por tipo (para preencher com lógica real)

- **`proc_sql`**: converta `CREATE TABLE <X> AS SELECT ...` para o `SELECT ...` do modelo (o nome `<X>` fica implícito no `stem`/ficheiro).
  - **Passthrough (`FROM CONNECTION TO ...`)**: o step deve conter o SQL interno **completo** (mesmo que repartido em `__partNN`). Proibido substituir por stub/metadados.
- **`data`**: converta `set/merge/if/where/keep/drop/length/format/rename` para `select` + casts + filtros.
- **`proc_sort`**: aplique ordenação e, se houver `nodupkey` + `by`, implemente dedupe (BigQuery: `qualify row_number() over(partition by ... order by ...) = 1`).
- **`proc_transpose`**: implemente pivot/agregação condicional.
- **`proc_export`**: model de saída (select do dataset exportado ou equivalente final do fluxo).

## Regras de dependência (quando usar `ref('step_...')`)

- **Só** use `{{ ref('step_...') }}` quando o `sas_excerpt` indicar leitura explícita de um dataset gerado anteriormente. Sinais comuns:
  - `set <DATASET>;`
  - `proc sort data=<DATASET> ...;`
  - `proc transpose data=<DATASET> ...;`
  - `proc sql ... from <DATASET> ...;`
- Se o step **não** tiver leitura explícita de dataset anterior (ex.: `DATA _NULL_`, blocos só de macro/side-effect, ou `PROC SQL` que só lê tabelas-base), **não** crie CTE `prev` com `ref('step_...')`.

## Regra específica (DATA step): não pode ser `select *` puro

- Se o `sas_excerpt` contiver qualquer transformação (ex.: `if/then/else`, atribuições `x = ...;`, `keep/drop/rename`, `format/length`), o SQL do step deve **expressar a transformação** (ex.: `CASE WHEN ... END AS ...`), não apenas `select * from prev`.

4. Ao terminar, rode:

   - `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report`
   - `python -m scripts.ai_step_gate "[NOME_SEM_EXT]" --write-report --autofix`

   Corrija faltas até os comandos retornarem exit code 0.

## Convenção / rastreabilidade

- Não renomeie os `stem`s: a paridade é determinística e o gate valida o nome exato.
- **Split (`__partNN`)**: cada part deve ter cabeçalho com:
  - `-- parent_step: <stem>`
  - `-- part: NN/TT`
  - (quando aplicável) `-- sas_lines: start..end`
- Se precisar de encadear steps, use `{{ ref('...') }}` quando fizer sentido (mas não é obrigatório para passar no gate; o gate só valida existência dos ficheiros).

## Critério de saída

- Somente considere o PASSO 2 (steps-only) concluído quando:
  - `python -m scripts.step_gate "[NOME_SEM_EXT]" --write-report` retornar **0**
  - E `STEP_GATE_REPORT.md` não listar faltas.

## Auto‑validação obrigatória (IA) — mesmo com scripts OK

Antes de declarar “concluído”, aplique o checklist **obrigatório**:

- `converter/templates/AI_VALIDATION_CHECKLIST.md` (seção **PASSO 2A**)

Se o checklist falhar (ex.: `DATA step` trivial, `proc_sql` stub/truncado, dependência `ref('step_')` indevida), **não avance**: corrija os steps e revalide.

Além disso, este modo exige um gate determinístico com relatório (cobertura **100%** dos steps):

- `python -m scripts.ai_step_gate "[NOME_SEM_EXT]" --write-report --autofix`
- artefato obrigatório: `draft_models/[NOME_SEM_EXT]/AI_STEP_VALIDATION_REPORT.md` (deve estar **100% PASS**)

## Próximo passo (se solicitado)

- Se o usuário quiser o pipeline canônico (camadas + governança), volte ao modo camadas (`.cursor/prompts/1_LOGIC_TRANSLATOR.md`) e siga o `draft_gate` + `checks --strict`.


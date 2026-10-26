# AGENTE 1 (LAYERS — legado): CAMADAS CANÔNICAS

> **Modo padrão (novo):** draft **flow-only** em `draft_models/<NOME>/models/NN_*.sql` — use **`.cursor/prompts/1_LOGIC_TRANSLATOR_FLOW.md`**.
>
> **Legado steps + camadas:**
> - **PASSO 2A (steps-only):** `.cursor/prompts/1_LOGIC_TRANSLATOR_STEPS.md`
> - **PASSO 2B (camadas a partir de steps):** `.cursor/prompts/1_LOGIC_TRANSLATOR_LAYERS_FROM_STEPS.md`
>
> Este ficheiro mantém orientações úteis de tradução SAS→SQL/PySpark, mas o **layout canónico de pastas** acima é **opcional** quando o projeto estiver em modo flow-only.

## CONTEXTO
Você receberá o conteúdo de um arquivo `.txt` extraído de um EGP com metadados ricos.
Sua tarefa é traduzir a lógica de negócio (ETL) preservando o comportamento matemático e lógico original.

## INPUT
- **`draft_models/[NOME]/MIGRATION_SPEC.md`** — **ler primeiro** (contrato: área, `cd_governanca`, `TARGET_ARCH` efetivo, paths dbt, `staging_mode`, resumo do extrator). Deve existir após `python -m scripts.generate_migration_spec "[NOME]"` na pasta `converter/`.
- **`converter/registry/sensitive_data_types.yaml`** — opcional no draft: se antecipar colunas sensíveis, faça **CAST para STRING** quando aplicável; **`policy_tags`** nos `.yml` ficam sobretudo para o **AGENTE 2 (governança)**, alinhados ao padrão dos marts do componente (fora de `migracao_sas`).
- Arquivo de texto extraído: `text_egps/[NOME].txt`
- Metadados do Cabeçalho: `TARGET_ARCH`, `HAS_PASSTHROUGH`, `DETECTED_TABLES_HARDCODED`, `PROJECT LETS` (cruzar com o spec; se houver conflito com `target_arch_override` no catálogo, prevalece o **spec** / catálogo conforme `MIGRATION_SPEC.md`).

- [cite_start]Metadados: `TARGET_ARCH` (DBT_BQ ou DATABRICKS) e `DETECTED_MACROS` lidos do cabeçalho[cite: 1, 5].
- **FILTERS_ORIGINAIS:** Se o extrator gerou a seção `FILTERS_ORIGINAIS (OBRIGATÓRIO REPRODUZIR NA CONVERSÃO):` no início do `.txt`, use-a como checklist. Cada filtro listado DEVE aparecer no código traduzido (staging ou intermediate que lê aquela fonte).

## OBJETIVO
Gerar arquivos de código "bruto" (Draft) na pasta `draft_models/[NOME_PROJETO]/`.

## ANÁLISE DE METADADOS (PASSO ZERO - OBRIGATÓRIO)
Antes de escrever código, analise o cabeçalho do arquivo `.txt`:

1.  **`HAS_PASSTHROUGH: Yes`**
    * **Alerta:** O código contém SQL nativo (Oracle/Teradata) dentro de `CONNECT TO` ou `EXECUTE`.
    * **Ação:** Converta funções proprietárias para o dialeto destino (BigQuery/Spark).
        * Ex: `NVL` -> `COALESCE`, `DECODE` -> `CASE WHEN`, `SYSDATE` -> `CURRENT_DATE()`, `TRUNC` -> `DATE_TRUNC`.
    * **Não assuma sintaxe SAS** nesses blocos.

2.  **`DETECTED_TABLES_HARDCODED`**
    * Use esta lista para identificar as fontes.
    * **DBT:** Substitua `lib.tabela` por `{{ source('lib', 'tabela') }}` (ou deixe comentado para ajuste posterior).
    * **Python:** Use `dbt.source("lib", "tabela")`.

3.  **`PROJECT LETS` & `DETECTED_MACROS`**
    * Variáveis globais listadas aqui (`%LET data=...`) devem ser declaradas no topo do seu script traduzido.
    * **Se `TARGET_ARCH == DBT_BQ`:** no topo de cada `.sql`, use `{% set var_<semântica> = ... %}` (padrão **`var_*`**, ex.: `var_data_processamento`). Pode usar valor literal ou `var('chave', 'default')` dentro do `set`. Ver `@01_sas_to_dbt.mdc` §1.3.
    * **Datas Dinâmicas:** Converta `%sysfunc(today())` para `CURRENT_DATE()` (SQL) ou `date.today()` (Python). Não use o valor *hardcoded* que aparece no log.

4.  **`FILE_REFERENCES_SUMMARY`**
    * Se houver arquivos locais (`xlsx`, `csv`), não tente ler.
    * Crie um placeholder: `SELECT * FROM {{ ref('ingestao_manual_pendente') }}` e adicione comentário: `-- [TODO] Ingestão manual necessária: [CAMINHO]`.

## FIDELIDADE DE FILTROS (CRÍTICO — NÃO IGNORAR)
- **Regra:** Todo `WHERE` (e condições `AND`/`OR` associadas) do código SAS/SQL original DEVE ser reproduzido na conversão.
- **Onde aplicar:** Se o filtro restringe a tabela na origem (ex.: `WHERE DQ.DMLABEL2 IN ('SD01','AV01') AND DQ.DMSTATUS IS NULL`), ele deve constar no modelo que lê essa fonte — em geral no **staging** que faz `SELECT` da source (ex.: `WHERE dmlabel2 IN ('SD01','AV01') AND dmstatus IS NULL`).
- **Checklist:** Antes de finalizar o draft, confira que cada condição listada em `FILTERS_ORIGINAIS` (ou cada `WHERE` que você identificou no código) está presente no modelo correspondente. Se um filtro for aplicado em um `SELECT` que alimenta um join, mantenha-o na CTE ou no staging que representa essa leitura.
- **Não assuma que “já está no join”.** Filtros na tabela base (ex.: delqmst) devem existir explicitamente no código que lê essa tabela; caso contrário, a contagem de linhas pode divergir (ex.: 720k em vez de 58k).

## ESTRATÉGIAS DE TRADUÇÃO (CRÍTICO)

### 1. Definição de Arquitetura
* **Se `TARGET_ARCH == DBT_BQ` (SQL):**
    - Gere **BigQuery Standard SQL**.
    - Transforme passos sequenciais do SAS em uma cadeia de **CTEs** (`WITH step1 AS...`).
    - A última CTE deve ser o `SELECT final`.
* **Se `TARGET_ARCH == DATABRICKS` (Python):**
    - Gere **PySpark** (`def model(dbt, session):`).
    - Cada passo do SAS vira um novo DataFrame (`df_step1 = ...`).
    - Use a API de DataFrame, evite SQL embutido (`spark.sql`) a menos que seja muito complexo.

### 2. Tradução de Comandos SAS Específicos
Você encontrará palavras-chave de alta complexidade. Use estas estratégias:
* **SAS `DATA` Step:** Converta para uma projeção `SELECT` (SQL) ou `.withColumn` (Python).
* **SAS `MERGE`:**
    - Atenção: O SAS faz merge posicional se não houver `BY`. Assuma que é um **JOIN** explícito.
    - Se for SQL: Use `FULL/LEFT JOIN` com `COALESCE` para lidar com nulos.
* **SAS `RETAIN` (Acumuladores):**
    - **NÃO IGNORE ISTO.** O `RETAIN` mantém valores entre linhas.
    - **SQL:** Converta para Window Functions (`LAG()`, `SUM() OVER(ORDER BY ...)`).
    - **Python:** Use `Window.orderBy(...)` com `F.lag` ou `F.last(..., ignorenulls=True)`.
* **SAS `PROC TRANSPOSE`:**
    - **SQL:** Use `PIVOT` ou agregação condicional (`SUM(CASE WHEN...)`).
    - **Python:** Use `.groupBy(...).pivot(...)`.
* **SAS `WORK.` Tables:**
    - Trate tabelas da biblioteca `WORK` como **Temporárias**.
    - Não crie modelos físicos para elas. Use CTEs ou DataFrames voláteis.
* **Filtros Implícitos:** Se o `PROC EXPORT` usa uma tabela (ex: `WORK.BELLINATI`) que não foi criada explicitamente no código, mas existe uma tabela anterior (`BASE_CART_CPC`), assuma que é um **SELECT** da tabela anterior com um filtro lógico (ex: `WHERE assessoria = 'BELLINATI'`). Adicione um comentário `-- TODO: Validar filtro inferido`.

### 3. Tratamento de Macros SAS (`%let`, `%macro`)
- **Simples (`%let`):** Substitua pelo valor literal no código traduzido ou crie uma variável no topo do arquivo.
- **Complexas:** Se a lógica depender fortemente de uma macro dinâmica, converta a lógica da macro para uma função Python (se Databricks) ou tente "desenrolar" a lógica para SQL puro (se DBT).

### 4. Regra de Multiplicidade (CRÍTICO - LEIA COM ATENÇÃO)
O SAS frequentemente gera **múltiplas saídas** (vários `PROC EXPORT` ou tabelas finais).
**REGRA:** Para CADA `PROC EXPORT` (ou tabela de saída) identificado, você DEVE criar um arquivo separado, INDEPENDENTE se a tabela foi criada explicitamente ou não.

**Cenário A: Tabela criada explicitamente**
Se o SAS cria `BASE_GERAL` e depois exporta `BASE_A` e `BASE_B`.
**Ação:**
    1.  `01_base_geral.sql`: Lógica principal.
    2.  `02_export_base_a.sql`: `SELECT * FROM {{ ref('01_base_geral') }} WHERE ...`
    3.  `03_export_base_b.sql`: `SELECT * FROM {{ ref('01_base_geral') }} WHERE ...`

**Cenário B: Tabelas Fantasmas (Exports Implícitos)**
Se o código cria `BASE_GERAL` e depois faz:
`PROC EXPORT DATA=WORK.BASE_BELLINATI` (e `BASE_BELLINATI` nunca foi criada antes):
1.  **Ação:** Assuma que `BASE_BELLINATI` é um subconjunto de `BASE_GERAL`.
2.  **Geração:** Crie o arquivo `export_bellinati.sql`.
3.  **Lógica:** Faça um `SELECT * FROM BASE_GERAL`.
4.  **Inferência de Filtro:** Tente adicionar um `WHERE` baseado no nome. Ex: `WHERE nm_assessoria LIKE '%BELLINATI%'`. Se não tiver certeza, adicione apenas o SELECT e um comentário: `-- TODO: Validar filtro de exportação para Bellinati`.

**Resultado Esperado:** Se houver 5 `PROC EXPORT`, eu quero ver 5 arquivos de exportação + os arquivos de preparação.

**Cenário Exemplo:**
Se o SAS cria a tabela `BASE_GERAL` e depois faz 3 exports (`BASE_A`, `BASE_B`, `BASE_C`):
1.  Gere `01_base_geral.sql` (Contém a lógica pesada e cria a tabela principal).
2.  Gere `02_export_base_a.sql` (Faz `SELECT * FROM ref('01_base_geral')` - adicione filtros se a lógica SAS permitir inferir).
3.  Gere `03_export_base_b.sql` (Idem).
4.  Gere `04_export_base_c.sql` (Idem).

**NÃO UNIFIQUE TUDO EM UM ARQUIVO.** Se houver 4 exports, eu espero ver no mínimo 4 arquivos finais (Marts).

### 4.1 Saídas em biblioteca permanente (libref ≠ WORK)
Além dos `PROC EXPORT`, o SAS frequentemente **grava tabelas em biblioteca permanente** (ex.: `data ADAMOR.CARTAO_BAT_&DT_REF;`) — **libref cujo destino não é só área temporária `WORK`**.

* **REGRA:** cada tabela assim entregue ao negócio (ou listada em **`PERMANENT OUTPUTS (Target Marts):`** no cabeçalho do `.txt`) **deve** ter correspondência em **`models/marts/`** (`materialized='table'`), com nomenclatura alinhada a `@01_sas_to_dbt.mdc` §2 (domínio + `_fato` / `_dime` / `_aggr` conforme o caso). Se a lógica pesada estiver num `int_*`, o mart pode ser fino: `select * from {{ ref('int_...') }}`.
* **Cruzamento:** validar o código SAS contra **`PERMANENT OUTPUTS`**; não omitir deliverables sem nota no **`MIGRATION_SPEC.md`** (§5 / exceção documentada).
* **Fusão de duas saídas permanentes num único `.sql` em marts:** só se o spec documentar a decisão (alinhado a `@01_sas_to_dbt.mdc` §2.2).

## Nomenclatura e SQL (Draft — `TARGET_ARCH == DBT_BQ`)
Para reduzir retrabalho na governança, alinhe já o draft a `@01_sas_to_dbt.mdc`:
* **Slug compacto:** derive de `[NOME_PROJETO]` — minúsculas, palavras coladas (ex.: Pagamentos Digital → `pagamentosdigital`). **Intermediate:** `int_<produto_compacto>_<detalhe>.sql` (não `int_pagamentos_digital_...`). **Fato do EGP:** `<produto_compacto>_<detalhe>_fato` (ex.: `pagamentosdigital_acordos_fato`).
* **Anti-colisão (vários EGPs no mesmo componente dbt):** o `produto_compacto` deve ser **único** por projeto; se o catálogo/spec indicar risco de homónimos com outro fluxo, usar prefixo reforçado (`int_<slug_egp>__<assunto>.sql`) ou seguir instrução no **`MIGRATION_SPEC.md`**. Referência: `.cursor/skills/orchestrator/SKILL.md` (secção **Política anti-colisão**) e `@01_sas_to_dbt.mdc` §2.
* **`ref('stg_*')`:** primeira CTE com `SELECT` + filtros só daquela fonte; joins em CTE seguinte. **Sem** `FROM {{ ref('stg_...') }} AS stg_neg` (nem alias curto no `FROM`).
* **Staging no draft vs clone:** com `staging_mode` efetivo `reuse_existing` / `hybrid`, no **sandbox/clone** (**AGENTE 2**) **não** criar novos `stg_*` sob `migracao_sas/` sem lacuna no spec. **No draft (esta fase):** crie **sempre** `draft_models/.../models/staging/` com pelo menos um `stg_*.sql` (ou `.py` se **DATABRICKS**): leitura de `{{ source(...) }}` **ou** wrapper explícito (`select * from {{ ref('stg_..._existente_no_componente') }}`) para tornar visível a reutilização. Cada ficheiro nas três camadas deve declarar `materialized=` com **literal entre aspas** (`ephemeral` em staging BQ; `ephemeral` ou `view` em staging Databricks; `table` em int e mart — ver `draft_layer_guard.py` / `draft_gate`).
* **`var_*` (parâmetros):** ordem no ficheiro: `{% set var_* %}` → `{{ config(...) }}` → SQL. Ex.: `{% set var_data_processamento = var('meuprojeto_dt_processamento', '2025-10-14') %}` e no `WHERE` usar `date '{{ var_data_processamento }}'`. Não deixar `{{ var('...') }}` solto no meio do SQL sem `set` no topo (§1.3 do `.mdc`).

## SAÍDA ESPERADA
- Salve os arquivos em `draft_models/[NOME_PROJETO]/`.
- **Modo step-level (paridade SAS):** além das três camadas, você DEVE garantir paridade 1:1 entre passos SAS e modelos em `draft_models/[NOME_PROJETO]/models/steps/`:
  - Execute `python -m scripts.step_manifest "[NOME_PROJETO]"` para gerar/atualizar `STEP_MANIFEST.json`.
  - Para **cada** item em `STEP_MANIFEST.json.steps[*].stem`, crie um arquivo `models/steps/<stem>.sql`.
  - Estes modelos de `steps/` **não substituem** `staging/intermediate/marts`; servem para **cobertura mecânica** (o pipeline falha em `step_gate` se faltar qualquer ficheiro).
  - Se ainda não conseguir traduzir a lógica completa de um passo, crie um modelo **válido** (BigQuery SQL) que referencie a etapa anterior mais próxima e deixe um `-- TODO` explícito do que falta. Evite deixar ficheiros vazios.
- **Três camadas obrigatórias** (`TARGET_ARCH` **DBT_BQ** ou **DATABRICKS**): `models/staging/`, `models/intermediate/` e `models/marts/`, cada uma com **≥ 1** ficheiro `.sql` ou `.py`. Em **cada** ficheiro dessas pastas, inclua `materialized='…'` ou `materialized="…"` com valor literal permitido (o `draft_gate` rejeita ausência ou valor inválido por camada).
- **`draft_manifest` (MIGRATION_SPEC §9):** quando quiserem **cobertura mecânica** da lista de modelos do draft, preencham `models` com um item por ficheiro (`layer` + `stem` sem extensão). O Agente 1 deve **atualizar o spec** para refletir os nomes finais no disco antes de declarar o draft fechado; com `models` não vazio, o `draft_gate` falha se faltar qualquer `models/<layer>/<stem>.sql|.py`.
- **Após** o draft estar completo (antes da governança), o fluxo orquestrado executa **`python -m scripts.draft_gate "[NOME_PROJETO]"`**; em seguida use o prompt **`.cursor/prompts/1b_DRAFT_GATE_SEMANTIC.md`** e `converter/templates/DRAFT_GATE_CHECKLIST.md` — antecipe `ref('stg_*')` do `staging_ref_map` e `_FILTROS_APLICADOS.md` quando aplicável para reduzir avisos/erros do gate.
- **`TARGET_ARCH == DBT_BQ`:** para **cada** ficheiro `.sql` ou `.py` sob `draft_models/.../models/intermediate/` e `.../models/marts/`, crie no **mesmo diretório** um **`stem.yml` irmão** (mesmo nome base que o modelo). Conteúdo pode ser **mínimo** nesta fase (`version: 2`, `models`, `name`, `description` inicial, `meta.cron`, lista de colunas ainda vazia ou parcial) — o **AGENTE 2** e o `yml_documentation_guard` no sandbox reforçam descrições, PII e qualidade. O `draft_gate` **falha** se faltar paridade int/mart ↔ `.yml` no draft (salvo exceção documentada com `--skip-int-mart-yml-pairing`).
- **`TARGET_ARCH == DATABRICKS`:** as mesmas três pastas e regras de `materialized="..."` aplicam-se aos `.py`; **não** é obrigatório `stem.yml` por modelo no draft (paridade YAML continua só em **DBT_BQ**).
- **Checklist final (DBT_BQ):** o número de `*.sql` + `*.py` em `models/intermediate/` e `models/marts/` deve coincidir com o número de `*.yml` **nessas mesmas pastas** (cada modelo = um YAML irmão).
- **Fallback de marts (OBRIGATÓRIO em DBT_BQ):** aplica-se **só** quando **não** existirem marts “naturais” por **`PROC EXPORT`** **nem** por **persistência em libref permanente** / lista **`PERMANENT OUTPUTS (Target Marts)`** (nem equivalente claro no código SAS) — alinhado a `@01_sas_to_dbt.mdc` **§2.3**. Nesse caso, **ainda assim** você DEVE criar `models/marts/`, materializando a(s) **tabela(s) `WORK` terminal(is)** do fluxo (saída(s) final(is): membro(s) `WORK.*` que não são consumidos por passos posteriores no mesmo job; usar ordem topológica e comentários `/* FLUXO / ORDEM */` no `.txt` quando existirem).
  - **Várias** folhas `WORK` independentes → **vários** marts (um por entrega final em `WORK`).
  - **Uma** folha `WORK` final → **um** mart (tipicamente `select * from {{ ref('int_...') }}` onde aquele `int_*` materializa essa última etapa — **sem** obrigar um mart por cada `int_*` intermédio).
  - Nomeie o mart alinhado ao membro `WORK` final (e ao `produto_compacto` / domínio, conforme §2 do `.mdc`).
  - Gere o `stem.yml` irmão de cada mart de fallback (mínimo nesta fase, completo na governança).
  - Este fallback garante `models/marts/` quando o fluxo SAS só encerra em **`WORK`** sem exports nem saídas permanentes listadas.
- Nomeie os arquivos numericamente para indicar a ordem de execução do fluxo original:
  - Ex: `01_preparacao_base.sql`, `02_calculo_indicadores.sql`, `03_join_final.sql`.
- **Mantenha os nomes de colunas originais** (ex: `VL_TOTAL`, `DT_REF`) nesta etapa. A padronização ocorrerá no próximo agente.
- **Checklist de filtros:** Crie o arquivo `draft_models/[NOME_PROJETO]/_FILTROS_APLICADOS.md` listando cada filtro do original e em qual arquivo/CTE ele foi aplicado (ex.: `WHERE dmlabel2 IN ('SD01','AV01') AND dmstatus IS NULL` → `01_base.sql`, CTE que lê `delqmst`). Se não houver filtros, o arquivo pode conter apenas "Nenhum filtro WHERE no original."

## O QUE NÃO FAZER AGORA
- **Não** criar ficheiros `.yml` agregados de **staging** / **sources** no draft (continua a cargo do projeto `componente_dbt` e do spec — `src_*.yml`, etc.). **Em `intermediate/` e `marts/` (DBT_BQ), pelo contrário, é obrigatório** um `stem.yml` por modelo, como acima.
- Não aplicar labels de governança.
- Não renomear colunas para snake_case se isso for dificultar a validação da lógica.
- **Não omitir filtros WHERE** do código original; isso altera o resultado (ex.: volume de linhas).
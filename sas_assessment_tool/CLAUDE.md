# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Sessões de IA: comece por [`ONBOARDING.md`](ONBOARDING.md)** — regras duras (deploy/escrita-prod só com consentimento; sem commit/push sem pedido), o trabalho ativo (app `monitoramento-sas`) e o mapa de docs. Guia detalhado do app: `egps_analysis/app/frontend/ONBOARDING.md`.

## Repository purpose

End-to-end SAS migration assessment tooling for the BV project. The repo is a **monorepo of independent sub-projects** that together cover the full migration lifecycle: log ingestion → dbt analysis → graph modelling → EGP inventory/prioritization → automated EGP-to-dbt conversion. Each sub-project has its own README, dependencies, and runtime — do not assume shared environments.

## Setup de dados (obrigatório para converter/ e egps_analysis/)

Os binários `.egp` do BV **não são versionados** (`.gitignore` bloqueia `*.egp` e `received_egps/`). Eles vivem num tar no Google Drive (`received_egps_20260612.tar`, ~846MB — link no README). Após clonar:

```bash
tar -xf received_egps_20260612.tar -C egps_analysis/   # restaura egps_analysis/received_egps/
```

O tar também contém `_arquivo_rodas_egp_binarios/`, `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO.egp` e `log_files/Exemplo 1.egp`.

## Sub-projects

| Path | Role | Stack |
|---|---|---|
| [ingestion/](ingestion/) | Ingests SAS `.log` files, user CSVs, and modernized-tables lists into Databricks. Includes [`sas_log_analyzer.py`](ingestion/sas_log_analyzer.py) (55KB regex-driven log parser) and [`regex_patterns.py`](ingestion/regex_patterns.py). | Python + `databricks-sql-connector`, OAuth U2M, Delta Lake |
| [dbt_sas_migration_assessment/](dbt_sas_migration_assessment/) | dbt project that transforms ingested logs into staging → trusted → marts → serving layers, producing dependency, lineage, and classification models. Runs on **Databricks or Snowflake** (selected via `DBT_PROFILE_TARGET`). | dbt ≥1.7, dual-target (`target-defer-databricks/`, `target-defer-snowflake/`), `bitbucket-pipelines.yml` for Slim CI, sqlfluff + yamllint + pre-commit |
| [sas_neo4j_setup/](sas_neo4j_setup/) | Converts a CSV modelling export ([exemplo_de_modelagem.csv](sas_neo4j_setup/exemplo_de_modelagem.csv)) into Cypher node/relationship scripts and loads them into Neo4j via Docker Compose. Data-driven — labels and relationship types come straight from the CSV. | Python + Neo4j 5.13 (APOC), `docker-compose.yml` |
| [converter/](converter/) | Converts `.egp` → **dbt models** (BigQuery SQL or Databricks Python) through a deterministic-script + multi-agent pipeline (6 steps, gates, batch mode). Canonical docs: [converter/README.md](converter/README.md) and [converter/.cursor/skills/orchestrator/SKILL.md](converter/.cursor/skills/orchestrator/SKILL.md). | Python (`python -m scripts.*`) + agent prompts + sqlfluff |
| [egps_analysis/](egps_analysis/) | Analyzes `.egp` projects: extracts I/O inventory and produces CSV reports (01–06) for prioritizing ingestion/migration. Canonical docs: [egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md](egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md). | Python 3.10+, pandas, openpyxl, BigQuery libs |
| [code_sas_to_py/](code_sas_to_py/) | Reference/scratch notebook ([PERF_AMIGAVEL_GCP.ipynb](code_sas_to_py/PERF_AMIGAVEL_GCP.ipynb)) and `.sqlfluff` config. |

Documentation for converter/ and egps_analysis/ is primarily in **Portuguese**.

## converter/ — EGP → dbt conversion

### Operational guardrails (NON-NEGOTIABLE)

The agent must **never** run, suggest as an automatic step, or execute in a pipeline terminal:

- **`dbt build`** — conversion produces *files for human review*; it must not materialize anything in the warehouse.
- **`git commit`** / **`git push`** — these mutate history/remote without an explicit human gate.

**Allowed git** only via `python -m scripts.bootstrap_egp_catalog ensure-repo` (clone/fetch/checkout/pull to prepare a dbt component dir — never commit/push). `dbt parse` is optionally allowed (lightweight); `sqlfluff` via `auto_fixer.py` is fine. See `.cursor/rules/04_pipeline_operational_guardrails.mdc`.

### Running scripts

All scripts run **from the `converter/` root** and are invoked as **modules**: `python -m scripts.<name>` (not `python scripts/<name>.py`). The `scripts/` package is the entrypoint surface; `batch_pipeline.py` is the orchestrator for batch/lote operations.

Per `.cursor/rules/00_shell_env.mdc`, every terminal invocation in this module should `cd` to `converter/`, source `.env`, and activate the venv in the **same** Bash call (agent terminal sessions do not persist state between calls):

```bash
cd converter && set -a && { [ ! -f .env ] || . ./.env; } && set +a && { [ ! -f venv/Scripts/activate ] || source venv/Scripts/activate; } && { [ ! -f venv/bin/activate ] || . venv/bin/activate; } && <command>
```

Install deps: `pip install -r requirements.txt`.

### Pipeline (steps 1–6, per EGP)

The full roteiro lives in `.cursor/skills/orchestrator/SKILL.md`. Each step has a deterministic script and (often) a paired AI micro-role prompt under `.cursor/prompts/`.

1. **Extract** — `python -m scripts.egps_extractor "received_egps/<AREA>/<file>.egp"` → `text_egps/<egp_key>.txt`. The header declares `TARGET_ARCH` (`DBT_BQ` or `DATABRICKS`) and `BUSINESS_AREA`. Area resolution priority: `--area` > `EGP_BUSINESS_AREA` env > path inference > TTY prompt (fails outside TTY if missing). `egps_extractor.py` is the **canonical** extractor; `egps_extractor_v10.py` is a legacy diff copy.
1b. **Catalog + clone** — look up the entry in `registry/egp_catalog.yaml`; resolve the dbt component repo root via `bootstrap_egp_catalog resolve`; ensure the clone exists via `ensure-repo`.
1c. **MIGRATION_SPEC** — `python -m scripts.generate_migration_spec "<egp_key>"` → `draft_models/<egp_key>/MIGRATION_SPEC.md` (the migration contract).
2. **Draft (logic translation)** — produces `.sql`/`.py` under `draft_models/<egp_key>/models/`.
2b. **Draft gate (mechanical)** — `python -m scripts.draft_gate "<egp_key>"` validates parity between extractor output, spec, and draft. Retry loop is capped at **5 attempts**; if still failing, stop and ask the user. Flow-only mode uses `python -m scripts.draft_flow_gate` instead.
3A. **Governance/refinement** in the sandbox under `converted_egps/`.
3B. **Publish** into the dbt component clone.
4. **Conditional validation** (optional `dbt parse`).
5. **Migration audit** → `AUDITORIA_*.md`.
6. **Expected output.**

### Two draft layouts

- **Flow-only (default):** flat numbered models `draft_models/<egp_key>/models/NN_*.sql`; gated by `draft_flow_gate.py` (requires the AI artifact `AI_DRAFT_FLOW_VALIDATION_REPORT.md` with `**Overall:** PASS`).
- **Legacy (3-layer):** `models/staging/` + `intermediate/` + `marts/`, each with a literal `materialized='…'`; gated by `draft_gate.py` + `draft_layer_guard.py`. For `DBT_BQ`, every `intermediate/` and `marts/` model needs a sibling `stem.yml`.

### Batch mode

```bash
python -m scripts.batch_pipeline extract   --batch-file registry/egp_keys_batch.txt --resume
python -m scripts.batch_pipeline checks     --batch-file registry/egp_keys_batch.txt --write-csv   # add --strict to enforce gates
python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt --write-report
python -m scripts.batch_pipeline batch-audit --batch-file registry/egp_keys_batch.txt --refresh-checks --out registry/BATCH_AUDIT.md
```

The preferred batch execution is **one Cursor-Agent session per `egp_key`** (avoids context bleed) via `scripts/run_agent_per_egp.sh` (base runner) or `scripts/run_agent_batch_isolated.sh` (wrapper that prints a summary). `scripts/run_batch_interactive.sh` adds per-step y/n prompts.

### Registry (operational source of truth)

`registry/` files are mostly git-ignored (`egp_catalog.yaml`, `egp_keys_batch.txt`, `batch_manifest.json`, `BATCH_AUDIT.md`, `user_profile.local.yaml`). `.example.*` templates are versioned — copy and fill them; **never wipe the whole catalog per batch** (it preserves `staging_ref_map` and notes). Key files: `egp_catalog.yaml` (per-EGP config), `area_componente_dbt.yaml` (area slug → dbt component + git URL), `area_cd_governanca.yaml` (governance labels), `sensitive_data_types.yaml` (PII policy tags).

### dbt code conventions (TARGET_ARCH=DBT_BQ)

From `.cursor/rules/01_sas_to_dbt.mdc`, SQL must pass SQLFluff (`.sqlfluff`, BigQuery dialect) without manual fixes: all-lowercase, **leading commas**, 4-space indent (no tabs), CTEs over subqueries (last CTE named `final`), and a **no-alias policy** for table references. `auto_fixer.py` runs sqlfluff on local files. `02_sas_to_databricks.mdc` covers the Databricks (dbt Python models) path.

### tools/

`tools/` holds standalone connectors (`bigquery_tools.py`, `databricks_tools.py`, `github_tools.py`) with companion `.md` docs and `test_databricks_connection.py`. Configured via `converter/.env` (GCP, Databricks, GitHub vars).

## egps_analysis/ — EGP inventory & migration reports

Run scripts **from the `egps_analysis/` folder** as plain files: `python <script>.py` (default paths are relative to this folder; some accept positional/CLI path args). Requires Python 3.10+ and `pip install -r requirements.txt` (includes `openpyxl`, `pandas`, BigQuery libs). GCP auth via ADC (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`; see `.env.example`.

### Ordered pipeline (respect the sequence)

`src/chameleon.csv` must reflect current BigQuery ingestions, so the GCP export (step 2) **must run before** the orchestrator (step 3).

```bash
python egps_extractor.py                         # 1. .egp/.sas → .txt metadata + I/O inventory
python gcp_bigquery_table_data_export.py \        # 2. export Chameleon catalog → src/chameleon.csv
    --project … --dataset … --table … --format csv -o ./src/chameleon.csv
python orchestrator_inventory.py                  # 3. → 01_*.csv … 06_prontidao_tabela.csv
python validate_table_in_vs_repmap.py             # 4. → 06_table_in_vs_repmap.csv (needs src/RepMap.xlsx)
python migration_hints_table_in_repmap_chameleon.py  # 5. → 06_migration_hints_table_in.csv
```

Reference inputs go in `src/`: `inventario_transacional.csv` (corporate), `RepMap.xlsx` (replication map), `chameleon.csv` (generated by step 2). `bq_connect.py` is for interactive BigQuery queries only — it does **not** replace step 2's structured export. Detailed docs are in `docs/` (start with `PIPELINE_INVENTARIO_MIGRACAO_SAS.md`).

### Decisões de design & armadilhas (não reverter sem ler o porquê)

These choices are deliberate and counter-intuitive — a future session "fixing" them will silently break correctness. Each links to its rationale doc; read it before changing the area.

- **A "família de safras" é camada de CONTAGEM; o grafo continua no grão da safra.** Com `FAMILIAS_SAFRA=1`, safras datadas da mesma tabela contam como 1 input em toda superfície do app (escopo Indicium: 2.446 linhas → 1.437 unidades), mas linhagem/produtor canônico/casamento input↔output seguem por safra de propósito — **não "simetrizar"**. Duas sutilezas que quebram em silêncio se mexidas: a guarda dos **≥2 membros** é decisão de CORPUS (resolver sobre o recorte faz a mesma tabela ser família num escopo e input solto noutro), e `n_disp` é derivado de `n_faltam` (contar "alguma safra modernizada" diria que família com 1 safra pronta e 46 pendentes está resolvida). → `docs/adr/0002-familia-de-safras-como-unidade-de-input.md`, `egps_analysis/app/backend/familias.py`.
- **Lineage/identity is keyed by `(physical path, member)`, NOT by libname name.** The libname *alias* is mutable per EGP (the same physical dir gets different aliases across projects, e.g. `INSIGHT` vs `_INSIGHT`), so name-keying causes both false-merges and false-splits. Don't revert lineage to name matching. → `docs/analises/REFAZ_LINHAGEM_PATH.md`, `docs/analises/ANALISE_LIBNAME_PATHS.md`.
- **The path-recovery pass in `orchestrator_inventory.py` is 100% additive** (only adds edges, never removes) and deliberately does **not** copy the generic-member guards (`GENERIC_MEMBER`/`len<6`/`isdigit`/fan-out cap) used in the `.sas7bdat` basename block. The `(path, member)` key is already far more restrictive than basename, so the guard would only add false-negatives (quantified: of 335 recovered edges, 0 generic, 0 numeric, 8 short-but-real). **Don't "symmetrize" it.** → `docs/analises/REFAZ_LINHAGEM_PATH.md` §Integração no orquestrador.
- **Path-aware identity INCREASES the input count (6474→6767); it does not dedupe it down.** Same name in different paths = distinct tables, not copies. Real-copy consolidation is a separate, opt-in effort that excludes `multi_produtor` (distinct tables that merely share a name). → `docs/analises/PLANO_CONSOLIDACAO_SASLOCAL.md`.
- **`publish_to_databricks.py`'s MERGE preserves human columns** (`status_humano`/`responsavel`/`observacao`, keyed by `chave_canonica`). Physical-path identity is exposed as **additive** columns (`paths_fisicos`/`n_paths_fisicos`), never by collapsing homonym rows — collapsing would destroy analyst-entered statuses. → `app/README.md` §Identidade física dos homônimos.
- **Removing a duplicate EGP or renaming one is a line in `egps_analysis/src/egps_decisoes.csv`, never a DELETE/UPDATE in the database.** The publish rewrites the corpus tables every run, so database-only fixes come back (measured 16/10/2026: all 11 hand-removed duplicates were back in prod). The orchestrator and the publish apply the file while reading the corpus and refuse orphan or conflicting decisions. → `egps_analysis/egp_decisoes.py`, `docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` §`src/egps_decisoes.csv`.
- **The extractor excludes `*dtm.json`** (connection/credential files, not data) and **collapses `[SHEET=]` xlsx variants** (same physical file), but only removes the bare reference when a sheet variant of the same file exists — so it never drops a legitimate input. → `docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` §`egps_extractor.py`.
- **Pass-through SQL inputs are captured on purpose** (`db..table` with omitted owner; bare tables in `FROM (subquery) … JOIN` chains). They're source tables (Sybase/SQL Server/BQ), so they surface as **"dep. produtor ausente"**, not as intra-corpus EGP→EGP edges. → `docs/PLANO_FIX_PASSTHROUGH_INPUTS.md`.

## .egp file format

A `.egp` is a ZIP of XML + text. Extraction priority for each `element/{UUID}/` node: `code.sas` (raw SAS) → `query.sql` (Query Builder SQL) → `log.txt`/`log.xml` (generated MPRINT code) → `element.xml` `<Path>`/`<Filename>` (external `%INCLUDE` reference). `project.xml` maps UUIDs → friendly task labels. Full anatomy in `converter/EGP_STRUCTURE.md`.

## Other sub-projects — common commands

### dbt project (`dbt_sas_migration_assessment/`)
Profile target switches the warehouse (set `DBT_PROFILE_TARGET=dev_databricks` or `dev_snowflake`). Models are organized by **numbered layer folders** (`00_staging`, `01_trusted`, `02_marts`, `03_serving`) — selectors usually take the layer name.

```bash
dbt deps
dbt build                                        # full run
dbt build -s 00_staging                          # one layer
dbt build -s dim_project_dependencie+            # one model + downstream
dbt build --select state:modified+               # Slim CI (uses target-defer-*/)
dbt test -s dim_project_dependencie
```

- `00_staging` — clean and normalize raw logs ([stg_log_process](dbt_sas_migration_assessment/models/00_staging/), `stg_table_modernized`, `stg_user`)
- `01_trusted` — aggregation and information extraction from SAS code blocks
- `02_marts` — dimensions and facts (e.g. `dim_project_dependencie`)
- `03_serving` — final BI-facing layer

Both warehouse targets must remain green; SQL is generally written portable, with sqlfluff configured in [.sqlfluff](dbt_sas_migration_assessment/.sqlfluff) and pre-commit hooks in [.pre-commit-config.yaml](dbt_sas_migration_assessment/.pre-commit-config.yaml).

### Ingestion (`ingestion/`)
```bash
python ingest_sas_logs.py --parallel --workers 6 --check_duplicates --sort_minsize
python ingest_sas_logs.py --clean                # full reload
python ingest_users.py
python ingest_modernized_tables.py
```
Requires `.env` with `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, optionally `DATABRICKS_CATALOG`/`DATABRICKS_SCHEMA`. Uses OAuth U2M (browser login).

### Neo4j setup (`sas_neo4j_setup/`)
```bash
python3 csv_to_cypher.py                         # CSV → Cypher scripts under nodes/, relationships/
docker-compose up -d                             # start Neo4j 5.13 + auto-loader
```

## Conventions from .cursorrules

The repo-root [.cursorrules](.cursorrules) targets the SAS→Databricks migration assistant role. Key guidelines: prefer idiomatic PySpark/Spark SQL over literal SAS translations, minimize Python UDFs when native Spark functions exist, default to Delta Lake, and validate row counts between SAS and Spark outputs. Map SAS PROCs to Spark equivalents (`PROC SORT`→`.orderBy()`, `PROC SQL`→Spark SQL, etc.). For SAS log analysis, use `re` + `pandas` to extract ERROR/WARNING messages, libref bindings, DATA/PROC step metrics, and macro resolutions.

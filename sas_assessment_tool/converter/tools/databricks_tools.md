# Databricks Tools — Build Record

## Original Request

```prompt
I need to create tools for this project so it can interact with Databricks. The tools should allow:

- Creating files in DBFS;
- Running notebooks and Spark SQL queries;
- Cluster management (list, start, and stop only), if possible;
- Running Databricks jobs, if possible;
- Exploring Unity Catalog and metadata;
- Accessing logs and execution results;
- Volume management;
```

## API Scope (token permissions)

- API scope(s)
- authentication
- billing
- command-execution
- clusters
- environments
- files
- global-init-scripts
- identity
- jobs
- libraries
- search
- sql
- tags
- unity-catalog
- workspace


---

Here is the implementation plan that was used:

# Plan: Databricks Interaction Tools

### Context

The project converts SAS EGP files to either dbt/BigQuery or Databricks/PySpark. The BigQuery and GitHub sides already have runtime tool modules (`tools/bigquery_tools.py`, `tools/github_tools.py`) that Claude can invoke to interact with live services. There is no equivalent for Databricks, even though the Databricks target is fully implemented in the conversion pipeline. This plan adds `tools/databricks_tools.py` and its companion skill and docs.

---

### Explicit Requirements

**Functional**

1. DBFS file management — upload a local file, download, list directory, delete.
2. Spark SQL execution — run SQL statements and return results as structured JSON.
3. Notebook execution — submit a one-time notebook run and optionally wait for its result.
4. Cluster management — list clusters (with state), start a terminated cluster, stop (terminate) a running cluster.
5. Job execution — list jobs, trigger a job run, get the status and output of any run.
6. Unity Catalog exploration — list catalogs, schemas, tables; get full metadata of a specific table.
7. Execution logs — retrieve run output and error logs for job runs and notebook runs.
8. Volume management — list volumes in a schema, get details of a specific volume.

**Non-functional**

- **Official SDK only**: use `databricks-sdk` (PyPI) — no raw REST calls.
- **Authentication via env vars**: `DATABRICKS_HOST` + `DATABRICKS_TOKEN` (the SDK reads these automatically, but `_load_config()` will still validate their presence and emit clear error messages).
- **JSON output** (`indent=2`, `ensure_ascii=False`) — machine-readable for Claude to parse, same convention as existing tools.
- **Errors to stderr + exit(1)** — consistent with existing tools.
- **Python 3.10+ type hints** — consistent with existing code style.
- **Async-aware**: operations that are inherently async (cluster start/stop, job run, notebook run) expose a `--wait` flag that blocks until completion using the SDK's built-in polling; without `--wait` they return immediately with the run/operation ID.

**Out of scope**

- Creating or deleting clusters (risk surface too high; list/start/stop only).
- Deleting jobs or catalogs.
- DBFS recursive upload/download.
- OAuth / service principal auth (PAT token is sufficient for the migration workflow).

---

### Design Decisions

| Area | Existing tools | Databricks tools | Reason |
|------|---------------|-----------------|--------|
| CLI framework | `argparse` | `argparse` | Consistent; no reason to introduce `click` |
| HTTP layer | SDK (BQ) / `requests` (GH) | `databricks-sdk` | Official SDK handles auth, retries, pagination |
| Async handling | Not needed | `--wait` flag + SDK polling | Cluster/job ops are long-running |
| SQL input | `--sql` / `--file` (BQ) | `--sql` / `--file` + `--warehouse-id` | SQL Warehouses use Statement Execution API — serverless, no cluster needed |
| Default catalog/schema | `GCP_DATASET` env var (BQ) | `DATABRICKS_DEFAULT_CATALOG` + `DATABRICKS_DEFAULT_SCHEMA` | Mirror BQ pattern for Unity Catalog defaults |
| Output metadata | Rows + schema (BQ) | State + run_id + duration + result (for async ops) | Richer context for job/notebook monitoring |

---

### Files Created / Modified

| File | Action |
|------|--------|
| `tools/databricks_tools.py` | Create — main CLI tool |
| `tools/databricks_skill_good_practices.md` | Create — safe usage rules for Claude |
| `.cursor/skills/databricks/SKILL.md` | Create — Cursor skill definition |
| `requirements.txt` | Modify — add `databricks-sdk>=0.20.0` |

---

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABRICKS_HOST` | Yes | Workspace URL (e.g. `https://adb-xxx.azuredatabricks.net`) |
| `DATABRICKS_TOKEN` | Yes | Personal Access Token |
| `DATABRICKS_DEFAULT_CATALOG` | No | Used when `--catalog` is omitted in UC/Volume commands |
| `DATABRICKS_DEFAULT_SCHEMA` | No | Used when `--schema` is omitted in UC/Volume commands |
| `DATABRICKS_DEFAULT_CLUSTER_ID` | No | Used when `--cluster-id` is omitted in cluster and notebook commands |

---

### Subcommands (19)

**DBFS (4)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `dbfs-ls` | `--path` | — | `[{path, is_dir, size_bytes, modified_ms}]` |
| `dbfs-put` | `--local`, `--remote` | `--overwrite` | `{remote_path, size_bytes}` |
| `dbfs-get` | `--remote`, `--local` | — | `{local_path, size_bytes}` |
| `dbfs-rm` | `--path` | `--recursive` | `{deleted_path}` |

**Clusters (4)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `cluster-list` | — | `--state` (filter: RUNNING/TERMINATED/…) | `[{cluster_id, name, state, runtime, driver, workers}]` |
| `cluster-get` | — | `--cluster-id`* | full cluster detail dict |
| `cluster-start` | — | `--cluster-id`*, `--wait` | `{cluster_id, state}` or blocks until RUNNING |
| `cluster-stop` | — | `--cluster-id`*, `--wait` | `{cluster_id, state}` or blocks until TERMINATED |

*Falls back to `DATABRICKS_DEFAULT_CLUSTER_ID` if omitted.

**SQL Execution (1)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `sql-run` | `--warehouse-id`, (`--sql` or `--file`) | `--max-rows` (default 100) | `{rows, row_count, total_row_count, truncated, schema}` |

Uses Statement Execution API — no running cluster required.

**Notebooks (1)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `notebook-run` | `--path` | `--cluster-id`*, `--params` (JSON), `--wait`, `--timeout` (default 600s) | `{run_id, state}` or full result with output |

*Falls back to `DATABRICKS_DEFAULT_CLUSTER_ID` if omitted.

**Jobs (3)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `job-list` | — | — | `[{job_id, name, creator, created_at_ms}]` |
| `job-run` | `--job-id` | `--params` (JSON), `--wait` | `{run_id, state}` or full result |
| `job-run-status` | `--run-id` | — | `{run_id, state, result_state, start_time, duration_ms, error, logs}` |

**Unity Catalog (4)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `uc-catalogs` | — | — | `[{name, type, owner, created_at, metastore_id}]` |
| `uc-schemas` | — | `--catalog`* | `[{name, catalog, owner, created_at}]` |
| `uc-tables` | — | `--catalog`*, `--schema`* | `[{name, full_name, catalog, schema, type, owner}]` |
| `uc-get-table` | `--table` (`catalog.schema.table`) | — | full metadata incl. columns, partitions, owner |

*Falls back to `DATABRICKS_DEFAULT_CATALOG` / `DATABRICKS_DEFAULT_SCHEMA` if omitted.

**Volumes (2)**

| Subcommand | Required args | Optional args | Returns |
|------------|--------------|---------------|---------|
| `volume-list` | — | `--catalog`*, `--schema`* | `[{name, full_name, type, storage_location, owner}]` |
| `volume-get` | `--volume` (`catalog.schema.volume`) | — | full volume detail dict |

---

### Good Practices Rules (`databricks_skill_good_practices.md`)

1. **Cost awareness before action** — warn user before starting clusters or triggering jobs.
2. **SQL always via warehouse** — use `sql-run` with `--warehouse-id`; never raw cluster command execution.
3. **Use `--wait` for synchronous results** — only when result content is needed inline.
4. **DBFS destructive ops** — confirm with user before `dbfs-rm`, especially with `--recursive`.
5. **UC exploration priority** — prefer `uc-tables` + `uc-get-table` over raw SQL against `INFORMATION_SCHEMA`.
6. **Max rows default** — `sql-run` defaults to `--max-rows 100`; ask before increasing.
7. **Check cluster state** before `cluster-start` / `cluster-stop` using `cluster-get`.
8. **Token cost awareness** — warn before printing large schemas, long logs, or many DBFS entries.

---

### Verification

```bash
# 1. Install
pip install -r requirements.txt

# 2. Source env vars
source .env

# 3. Basic connectivity
python tools/databricks_tools.py cluster-list
python tools/databricks_tools.py uc-catalogs
python tools/databricks_tools.py dbfs-ls --path /

# 4. SQL execution (requires a SQL Warehouse ID)
python tools/databricks_tools.py sql-run --warehouse-id <id> --sql "SELECT 1 AS test"

# 5. Unity Catalog drill-down
python tools/databricks_tools.py uc-schemas --catalog main
python tools/databricks_tools.py uc-tables  --catalog main --schema default
```

---


# Follow-up Adjustments

> Also, don't we need an env var for the cluster ID?

Added `DATABRICKS_DEFAULT_CLUSTER_ID` as an optional env var. When set, `--cluster-id` can be omitted from `cluster-get`, `cluster-start`, `cluster-stop`, and `notebook-run` — mirrors the pattern of `GCP_DATASET` in `bigquery_tools.py`.

---

> if the DBFS root is disabled by workspace policy, is it possible to adapt the tool to use relative paths?

Added `DATABRICKS_DBFS_BASE` env var (e.g. `/FileStore`). Paths not starting with `/` are resolved against this base. Absolute paths are passed through unchanged. DBFS operations auto-skip in the test suite if the workspace policy still denies access.

---

> why can't the all purpose cluster in DATABRICKS_DEFAULT_CLUSTER_ID run sql tests? / I want the cluster as default for sql, with warehouse as fallback

Added Command Execution API support to `sql-run`. When `DATABRICKS_DEFAULT_CLUSTER_ID` is set (or `--cluster-id` is passed), the cluster is tried first. If cluster SQL fails — Spark Connect incompatibility (DBR 13+), missing `command-execution` token scope, or other errors — the tool automatically falls back to the SQL Warehouse and prints a WARNING to stderr. `--warehouse-id` is now optional. `--cluster-id` flag added to `sql-run` for explicit override.

Internal mechanism: `_ClusterSqlError` raised by `_sql_run_cluster` on failure; caught by `sql_run` dispatcher to trigger warehouse retry.

---

> is it possible to use a serverless cluster to run a notebook if we adapt the tool?

Added serverless notebook support. `notebook-run --cluster-id` is now optional. Priority: explicit `--cluster-id` → `DATABRICKS_DEFAULT_CLUSTER_ID` → serverless (no `existing_cluster_id` sent to the API, triggering serverless compute automatically).

---

> job-run-status should consider success only if all tasks are successful / we need a separate feature to check individual tasks' status and logs

Refactored `job_run_status` to return a full `tasks` array (one entry per task) using a new `_task_summary` static method. The top-level `result_state` reflects the overall run; per-task details (`state`, `result_state`, `attempt_number`, `run_page_url`) live in `tasks`. Removed top-level `error`/`error_trace`/`logs` (these are task-level — use `job-task-output` instead).

Added `job-task-output` subcommand: accepts `--run-id` (parent run) + `--task-key` to look up a task by name, or `--run-id` alone when using a task run_id directly. Returns `error`, `error_trace`, `logs`, and `notebook_output` for that specific task.

---

> I would like it to be possible to run isolated tasks independently if it has failed before and needs repair

Added `job-repair` subcommand: re-runs specific failed/skipped tasks from an existing run using the SDK's `repair_run` API. Accepts `--run-id`, `--task-keys` (comma-separated, required), `--wait`. Respects task dependencies defined in the job — upstream failed tasks are re-run automatically even if not listed in `--task-keys`.

---

> run only test_dbt_job_triggered_externally2 (fresh isolated run, not repair)

Added `--task-keys` optional flag to `job-run`. Uses the SDK's `only` parameter in `run_now`. Tasks not listed are set to SKIPPED/DISABLED with no dependency evaluation — fully isolated. Preferred over `job-repair` when clean isolation is needed; `job-repair` preserves run history but triggers the dependency graph.

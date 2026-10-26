```
Arquivo gerado automaticamente pelo claude quando solicitado para criar a tool do databricks. Seguiu o mesmo padrão da bigquery_skill_good_practices, porém a função neste caso vai além de documentação, pois é referenciada pela skill databricks como manual das boas práticas.
```

# Databricks Tool — Good Practices

Rules that Claude must follow when using `tools/databricks_tools.py`. These exist to prevent unnecessary cluster costs, avoid irreversible file operations, and keep context usage reasonable.

---

## 1. Warn Before Any Cost-Generating Action

Starting a cluster or triggering a job incurs compute costs. Before running any of the following, warn the user and wait for confirmation:

| Action | Estimated cost |
|--------|---------------|
| `cluster-start` | Cluster DBUs start accruing immediately |
| `cluster-stop` | Terminates billing — always safe to do |
| `job-run` | Depends on job tasks and cluster size |
| `notebook-run` | Depends on cluster size and notebook duration |

> "This will start cluster `<name>` (`<id>`), which will begin billing DBUs. Proceed?"

---

## 2. SQL Execution: Cluster First, Warehouse as Fallback

`sql-run` resolves compute in this priority order:

1. **Cluster (Command Execution API)** — used when `DATABRICKS_DEFAULT_CLUSTER_ID` is set or `--cluster-id` is passed explicitly.
2. **SQL Warehouse (Statement Execution API)** — used when no cluster is configured, or when cluster SQL fails automatically (e.g., Spark Connect incompatibility on DBR 13+, or missing `command-execution` token scope). Pass `--warehouse-id` or set `DATABRICKS_DEFAULT_WAREHOUSE_ID`.
3. **Neither set** — the tool exits with an error.

```bash
# Cluster-first (implicit when DATABRICKS_DEFAULT_CLUSTER_ID is set)
python tools/databricks_tools.py sql-run --sql "SELECT 1"

# Explicit warehouse only (no cluster configured)
python tools/databricks_tools.py sql-run \
  --warehouse-id abc123 \
  --sql "SELECT * FROM my_catalog.my_schema.orders LIMIT 10"

# Both set: cluster tried first, warehouse used on failure
python tools/databricks_tools.py sql-run \
  --cluster-id 0101-xxx \
  --warehouse-id abc123 \
  --sql "SELECT * FROM my_catalog.my_schema.orders LIMIT 10"
```

When a cluster falls back to the warehouse, a WARNING is printed to stderr — no manual intervention needed.

---

## 3. Use `--wait` Only When You Need the Output

Without `--wait`, `notebook-run` and `job-run` return immediately with a `run_id` and `PENDING` state. Use `job-run-status` to poll if needed. Only pass `--wait` when:
- You need the notebook output or job result inline.
- The operation is expected to complete quickly (< 5 min).

For long-running jobs, prefer starting without `--wait` and polling:

```bash
# Start and get run_id
python tools/databricks_tools.py job-run --job-id 123

# Poll status later
python tools/databricks_tools.py job-run-status --run-id <run_id>
```

---

## 4. DBFS Destructive Operations Require Explicit Confirmation

Always confirm with the user before executing `dbfs-rm`, especially with `--recursive`. State the exact path being deleted.

> "This will permanently delete `dbfs:/mnt/data/my_folder/` and all its contents. This cannot be undone. Proceed?"

For `dbfs-put --overwrite`, confirm if overwriting existing data is intentional.

---

## 5. Prefer Unity Catalog for Metadata Exploration

When the goal is discovering tables, schemas, or column definitions:

```bash
# Fast — use these first
python tools/databricks_tools.py uc-catalogs
python tools/databricks_tools.py uc-schemas --catalog my_catalog
python tools/databricks_tools.py uc-tables --catalog my_catalog --schema my_schema
python tools/databricks_tools.py uc-get-table --table my_catalog.my_schema.my_table
```

Only run `sql-run` against `INFORMATION_SCHEMA` if `uc-*` commands don't return what you need (e.g., row counts, partition info, storage size).

---

## 6. Default Row Limit for `sql-run`

- The default `--max-rows 100` is appropriate for exploration. Do not increase it without reason.
- If you genuinely need more rows, explain why and ask the user before proceeding:
  > "This query would return N rows. I need to fetch up to X because [reason]. Can I proceed?"
- If the result set is large, prefer aggregating in SQL and returning a summary (e.g., `COUNT`, `GROUP BY`) rather than fetching raw rows.

---

## 7. Check Cluster State Before Acting

Before calling `cluster-start` or `cluster-stop`, always call `cluster-get` to confirm the current state. Starting an already-running cluster or stopping a terminated one will return an error.

```bash
python tools/databricks_tools.py cluster-get --cluster-id <id>
# Check "state" field: RUNNING, TERMINATED, PENDING, STARTING, TERMINATING, ERROR
```

---

## 8. Token / Context Cost Awareness

| Trigger | Action |
|---------|--------|
| `uc-get-table` on a table with > 100 columns | Warn before printing full schema |
| `job-run-status` with many tasks or long state messages | Summarize and offer to show more |
| `dbfs-ls` returning > 50 entries | Summarize count and show first few entries |
| Multiple large SQL results in sequence | Summarize cumulative row count before fetching |

---

## 9. Job Task Targeting: Diagnose Before Re-running

When a multi-task job fails, follow this sequence:

**Step 1 — Read per-task status**
```bash
python tools/databricks_tools.py job-run-status --run-id <run_id>
# Returns all tasks with state, result_state, attempt_number, and run_page_url
```

**Step 2 — Read the failing task's logs**
```bash
python tools/databricks_tools.py job-task-output \
  --run-id <run_id> \
  --task-key <failed_task_key>
# Returns error, error_trace, logs, and notebook_output for that specific task
```

**Step 3a — Fresh isolated run of specific tasks**
```bash
python tools/databricks_tools.py job-run \
  --job-id <job_id> \
  --task-keys <task_key> \
  --wait
# Other tasks are automatically SKIPPED/DISABLED
```

**Step 3b — Repair from an existing failed run (preserves run history)**
```bash
python tools/databricks_tools.py job-repair \
  --run-id <failed_run_id> \
  --task-keys <task_key> \
  --wait
```

> **Important:** `job-repair` respects the job's task dependency graph. If the task you're repairing has an upstream dependency that also failed, Databricks will automatically re-run that upstream task first — even if it is not listed in `--task-keys`. If this causes unwanted side effects (e.g., the upstream task has its own failures or costs), use `job-run --task-keys` for a fully isolated fresh run instead.

---
name: databricks
description: Use this skill whenever a Databricks workspace operation is needed — exploring Unity Catalog, running SQL on a warehouse or cluster, managing clusters, triggering jobs, accessing DBFS, or inspecting execution logs. Invoke it before any programmatic interaction with a Databricks workspace. SKIP when the task has no Databricks interaction.
---

# Skill: /databricks

Interact with a Databricks workspace programmatically: explore Unity Catalog, execute SQL, manage clusters, run notebooks, trigger jobs, manage DBFS and volumes, and debug task-level execution.

**Before each operation, read and apply the rules in `tools/databricks_skill_good_practices.md`.**

---

## Setup

### 1. Install dependency
```bash
pip install -r requirements.txt
# Installs databricks-sdk>=0.20.0
```

### 2. Set required env vars
```bash
export DATABRICKS_HOST=https://adb-1234567890.azuredatabricks.net
export DATABRICKS_TOKEN=dapi...   # User Settings → Developer → Access Tokens

# Optional: defaults so flags can be omitted
export DATABRICKS_DEFAULT_CATALOG=my_catalog
export DATABRICKS_DEFAULT_SCHEMA=my_schema
export DATABRICKS_DEFAULT_CLUSTER_ID=0101-123456-abcdef   # Used for sql-run, notebook-run, cluster commands
export DATABRICKS_DEFAULT_WAREHOUSE_ID=abc123              # SQL Warehouse fallback for sql-run
export DATABRICKS_SQL_WAREHOUSE_ID=abc123                  # Alias — either works
export DATABRICKS_DBFS_BASE=/FileStore                     # Base path for relative DBFS paths
```

---

## Operations

### DBFS

DBFS paths starting with `/` are used as-is. Paths without a leading `/` are resolved relative to `DATABRICKS_DBFS_BASE` (e.g., `myfile.txt` → `/FileStore/myfile.txt`).

#### `dbfs-ls` — List files in a DBFS path
```bash
python tools/databricks_tools.py dbfs-ls --path /FileStore/migrations
```
```json
[
  {"path": "/FileStore/migrations/raw/", "is_dir": true,  "size_bytes": 0,       "modified_ms": 1714000000000},
  {"path": "/FileStore/migrations/orders.parquet", "is_dir": false, "size_bytes": 524288, "modified_ms": 1714001000000}
]
```

#### `dbfs-put` — Upload a local file to DBFS
```bash
python tools/databricks_tools.py dbfs-put \
  --local ./converted_egps/databricks/my_project/models/stg_orders.py \
  --remote /FileStore/migrations/stg_orders.py \
  --overwrite
```
```json
{"remote_path": "/FileStore/migrations/stg_orders.py", "size_bytes": 4096}
```

#### `dbfs-get` — Download a DBFS file
```bash
python tools/databricks_tools.py dbfs-get \
  --remote /FileStore/data/output.csv \
  --local ./output.csv
```
```json
{"local_path": "./output.csv", "size_bytes": 102400}
```

#### `dbfs-rm` — Delete a file or directory from DBFS
```bash
python tools/databricks_tools.py dbfs-rm --path /FileStore/data/old_file.csv
python tools/databricks_tools.py dbfs-rm --path /FileStore/data/old_folder/ --recursive
```
```json
{"deleted_path": "/FileStore/data/old_file.csv"}
```

---

### Clusters

#### `cluster-list` — List clusters
```bash
python tools/databricks_tools.py cluster-list
python tools/databricks_tools.py cluster-list --state RUNNING
```
```json
[
  {
    "cluster_id": "0101-123456-abcdef",
    "name": "migration-cluster",
    "state": "RUNNING",
    "runtime": "14.3.x-scala2.12",
    "driver_type": "m5.xlarge",
    "worker_type": "m5.xlarge",
    "num_workers": 2,
    "creator": "william@company.com"
  }
]
```

#### `cluster-get` — Get full cluster details
```bash
python tools/databricks_tools.py cluster-get --cluster-id 0101-123456-abcdef
# Falls back to DATABRICKS_DEFAULT_CLUSTER_ID if --cluster-id is omitted
```

#### `cluster-start` — Start a terminated cluster
```bash
python tools/databricks_tools.py cluster-start --cluster-id 0101-123456-abcdef
python tools/databricks_tools.py cluster-start --cluster-id 0101-123456-abcdef --wait
```
```json
{"cluster_id": "0101-123456-abcdef", "state": "STARTING"}
```

#### `cluster-stop` — Terminate a running cluster (config is preserved)
```bash
python tools/databricks_tools.py cluster-stop --cluster-id 0101-123456-abcdef --wait
```
```json
{"cluster_id": "0101-123456-abcdef", "state": "TERMINATED"}
```

---

### SQL Execution

#### `sql-run` — Execute SQL (cluster-first, warehouse fallback)

Compute is resolved in this order:
1. Cluster (`--cluster-id` or `DATABRICKS_DEFAULT_CLUSTER_ID`)
2. SQL Warehouse (`--warehouse-id` or `DATABRICKS_DEFAULT_WAREHOUSE_ID`) — used when no cluster is set, or when cluster SQL fails (Spark Connect / DBR 13+, missing token scope)

```bash
# Cluster-first (implicit when DATABRICKS_DEFAULT_CLUSTER_ID is set)
python tools/databricks_tools.py sql-run \
  --sql "SELECT * FROM my_catalog.my_schema.orders LIMIT 10"

# Explicit warehouse (no cluster)
python tools/databricks_tools.py sql-run \
  --warehouse-id abc123 \
  --sql "SELECT * FROM my_catalog.my_schema.orders LIMIT 10"

# Both set — cluster tried first, auto-falls back to warehouse on failure
python tools/databricks_tools.py sql-run \
  --cluster-id 0101-xxx \
  --warehouse-id abc123 \
  --sql "SELECT * FROM my_catalog.my_schema.orders LIMIT 10"

# From a file
python tools/databricks_tools.py sql-run \
  --file converted_egps/dbt/my_project/models/stg_orders.sql \
  --max-rows 20
```
```json
{
  "rows": [{"order_id": "001", "amount": "150.00"}, "..."],
  "row_count": 10,
  "total_row_count": 42000,
  "truncated": true,
  "schema": [
    {"name": "order_id", "type": "STRING",  "nullable": true},
    {"name": "amount",   "type": "DECIMAL", "nullable": true}
  ]
}
```

---

### Notebooks

#### `notebook-run` — Submit a one-time notebook run

`--cluster-id` is optional. Priority: explicit `--cluster-id` → `DATABRICKS_DEFAULT_CLUSTER_ID` → serverless compute (no cluster).

```bash
# On a specific cluster
python tools/databricks_tools.py notebook-run \
  --path /Workspace/migrations/stg_orders \
  --cluster-id 0101-123456-abcdef \
  --params '{"env": "dev", "date": "2026-01-01"}' \
  --wait

# Serverless (no cluster ID set or passed)
python tools/databricks_tools.py notebook-run \
  --path /Workspace/migrations/stg_orders \
  --wait \
  --timeout 600
```
```json
{
  "run_id": 78901,
  "state": "TERMINATED",
  "result_state": "SUCCESS",
  "run_page_url": "https://adb-xxx.azuredatabricks.net#joblist/runs/78901",
  "notebook_output": "Processed 42000 rows",
  "error": null,
  "error_trace": null
}
```

---

### Jobs

#### `job-list` — List all jobs
```bash
python tools/databricks_tools.py job-list
```
```json
[
  {"job_id": 123, "name": "nightly_ingestion", "creator": "william@company.com", "created_at_ms": 1714000000000}
]
```

#### `job-run` — Trigger a job run
```bash
# Run all tasks
python tools/databricks_tools.py job-run --job-id 123 --wait

# Run only specific tasks (others are SKIPPED/DISABLED)
python tools/databricks_tools.py job-run \
  --job-id 123 \
  --task-keys ingest_task \
  --wait

# Multiple tasks
python tools/databricks_tools.py job-run \
  --job-id 123 \
  --task-keys ingest_task,transform_task \
  --params '{"date": "2026-01-01"}' \
  --wait
```
```json
{
  "run_id": 456,
  "state": "TERMINATED",
  "result_state": "SUCCESS",
  "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/456",
  "tasks": [
    {
      "task_key": "ingest_task",
      "run_id": 789,
      "state": "TERMINATED",
      "result_state": "SUCCESS",
      "attempt_number": 0,
      "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/789"
    }
  ]
}
```

#### `job-run-status` — Get run status and per-task breakdown
```bash
python tools/databricks_tools.py job-run-status --run-id 456
```
```json
{
  "run_id": 456,
  "state": "TERMINATED",
  "result_state": "SUCCESS",
  "state_message": "",
  "start_time_ms": 1714000000000,
  "duration_ms": 120000,
  "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/456",
  "tasks": [
    {
      "task_key": "ingest_task",
      "run_id": 789,
      "state": "TERMINATED",
      "result_state": "SUCCESS",
      "attempt_number": 0,
      "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/789"
    },
    {
      "task_key": "transform_task",
      "run_id": 790,
      "state": "TERMINATED",
      "result_state": "FAILED",
      "attempt_number": 0,
      "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/790"
    }
  ]
}
```

#### `job-task-output` — Get logs and error for a specific task
```bash
# Look up a task by key within a parent run
python tools/databricks_tools.py job-task-output \
  --run-id 456 \
  --task-key transform_task

# Use a task run_id directly (from job-run-status tasks[].run_id)
python tools/databricks_tools.py job-task-output --run-id 790
```
```json
{
  "task_run_id": 790,
  "task_key": "transform_task",
  "state": "TERMINATED",
  "result_state": "FAILED",
  "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/790",
  "notebook_output": null,
  "error": "com.example.SomeException: ...",
  "error_trace": "Traceback (most recent call last): ...",
  "logs": "..."
}
```

#### `job-repair` — Re-run specific failed or skipped tasks in an existing run
```bash
python tools/databricks_tools.py job-repair \
  --run-id 456 \
  --task-keys transform_task \
  --wait
```
```json
{
  "run_id": 456,
  "state": "TERMINATED",
  "result_state": "SUCCESS",
  "run_page_url": "https://adb-xxx.azuredatabricks.net#job/123/run/456",
  "tasks": [
    {
      "task_key": "ingest_task",
      "run_id": 789,
      "state": "TERMINATED",
      "result_state": "SUCCESS",
      "attempt_number": 0,
      "run_page_url": "..."
    },
    {
      "task_key": "transform_task",
      "run_id": 791,
      "state": "TERMINATED",
      "result_state": "SUCCESS",
      "attempt_number": 1,
      "run_page_url": "..."
    }
  ]
}
```

> **Note:** `job-repair` respects task dependencies. If the task you're repairing depends on an upstream task that also failed, Databricks will re-run that upstream task first automatically. Use `job-run --task-keys` for a fully isolated fresh run.

---

### Unity Catalog

#### `uc-catalogs` — List catalogs
```bash
python tools/databricks_tools.py uc-catalogs
```
```json
[{"name": "main", "type": "MANAGED_CATALOG", "owner": "admins", "created_at": null, "metastore_id": "xxx", "comment": null}]
```

#### `uc-schemas` — List schemas in a catalog
```bash
python tools/databricks_tools.py uc-schemas --catalog main
# Or if DATABRICKS_DEFAULT_CATALOG is set:
python tools/databricks_tools.py uc-schemas
```

#### `uc-tables` — List tables in a schema
```bash
python tools/databricks_tools.py uc-tables --catalog main --schema raw
```
```json
[
  {"name": "orders", "full_name": "main.raw.orders", "catalog": "main", "schema": "raw", "type": "MANAGED", "owner": "admins"}
]
```

#### `uc-get-table` — Get full table metadata
```bash
python tools/databricks_tools.py uc-get-table --table main.raw.orders
```
```json
{
  "full_name": "main.raw.orders",
  "catalog": "main",
  "schema": "raw",
  "name": "orders",
  "type": "MANAGED",
  "owner": "admins",
  "created_at": null,
  "updated_at": null,
  "storage_location": "abfss://...",
  "data_source_format": "DELTA",
  "comment": "Raw orders from ERP",
  "columns": [
    {"name": "order_id", "type": "STRING",  "nullable": false, "comment": "", "partition_index": null},
    {"name": "amount",   "type": "DECIMAL", "nullable": true,  "comment": "", "partition_index": null}
  ]
}
```

---

### Volumes

#### `volume-list` — List volumes in a schema
```bash
python tools/databricks_tools.py volume-list --catalog main --schema landing
```
```json
[
  {"name": "raw_files", "full_name": "main.landing.raw_files", "catalog": "main", "schema": "landing",
   "type": "EXTERNAL", "storage_location": "abfss://...", "owner": "admins"}
]
```

#### `volume-get` — Get volume details
```bash
python tools/databricks_tools.py volume-get --volume main.landing.raw_files
```

---

## Integration with the migration pipeline

After `/tradutor` generates a Databricks/PySpark model, use this skill to validate it:

```bash
# 1. Check if the target table exists in Unity Catalog
python tools/databricks_tools.py uc-get-table --table main.raw.source_table

# 2. Verify source schema matches what the model expects
python tools/databricks_tools.py sql-run \
  --sql "DESCRIBE TABLE main.raw.source_table"

# 3. Run a smoke test query
python tools/databricks_tools.py sql-run \
  --sql "SELECT COUNT(*) AS n FROM main.raw.source_table" \
  --max-rows 1
```

After `/auditor` produces a report, link the run URL from `job-run-status` to the GitHub PR comment via `/github add-comment`.

---

## Error reference

| Error message | Cause | Fix |
|--------------|-------|-----|
| `Missing required environment variable(s): DATABRICKS_HOST` | Env var not set | `export DATABRICKS_HOST=https://...` |
| `Missing required environment variable(s): DATABRICKS_TOKEN` | Token not set | Generate at workspace → User Settings → Developer |
| `databricks-sdk is not installed` | Missing dependency | `pip install -r requirements.txt` |
| `No catalog specified` | `--catalog` omitted and `DATABRICKS_DEFAULT_CATALOG` not set | Add `--catalog` or set env var |
| `No schema specified` | `--schema` omitted and `DATABRICKS_DEFAULT_SCHEMA` not set | Add `--schema` or set env var |
| `No SQL compute specified` | Neither cluster nor warehouse configured | Set `DATABRICKS_DEFAULT_CLUSTER_ID`, `DATABRICKS_DEFAULT_WAREHOUSE_ID`, or pass `--cluster-id`/`--warehouse-id` |
| `Databricks API error: PERMISSION_DENIED` | Token lacks required privileges | Contact workspace admin to grant necessary permissions |
| `Databricks API error: RESOURCE_DOES_NOT_EXIST` | Wrong path, cluster ID, or table name | Verify with `cluster-list`, `uc-catalogs`, or `dbfs-ls` |
| `SQL execution failed (FAILED)` | Invalid SQL or warehouse unreachable | Check SQL syntax; verify warehouse is running |
| `WARNING: Cluster SQL failed (...); falling back to SQL Warehouse` | Cluster uses Spark Connect (DBR 13+) or lacks `command-execution` scope | Informational only — warehouse fallback is automatic; ensure `--warehouse-id` or `DATABRICKS_DEFAULT_WAREHOUSE_ID` is set |
| `Retrieving the output of runs with multiple tasks is not supported` | Called `get_run_output` with a parent run ID | Use `job-task-output --run-id <parent_run_id> --task-key <key>` instead |

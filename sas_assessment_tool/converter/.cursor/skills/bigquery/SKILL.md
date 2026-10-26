---
name: bigquery
description: Use this skill whenever a BigQuery operation is needed — running a query, validating SQL with a dry-run, listing datasets or tables, or inspecting table schemas. Invoke it before executing any SQL against BigQuery, even for ad-hoc or inline queries. SKIP when the task has no BigQuery interaction.
---

# Skill: /bigquery

Interact with BigQuery programmatically: run queries, validate SQL, and inspect datasets and tables.

---

## Setup

### 1. Install dependency
```bash
pip install -r requirements.txt
# Installs google-cloud-bigquery>=3.13.0
```

### 2. Authenticate (pick one)

**Option A — Application Default Credentials (recommended for local dev)**
```bash
gcloud auth application-default login
# Follow browser prompt once. No env var needed afterwards.
```

**Option B — Service account key (recommended for CI / automated agents)**
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account_key.json
# Key file: GCP Console → IAM & Admin → Service Accounts → Keys → Add Key → JSON
```

### 3. Set required env var
```bash
export GCP_PROJECT_ID=my-gcp-project

# Optional: set a default dataset so --dataset can be omitted
export GCP_DATASET=my_dataset
```

---

## Operations

### `query` — Run a SQL query and return rows

```bash
# From a SQL string
python tools/bigquery_tools.py query \
  --sql "SELECT * FROM \`my-project.my_dataset.my_table\` LIMIT 10"

# From a .sql file
python tools/bigquery_tools.py query \
  --file converted_egps/dbt/my_model/models/my_model.sql \
  --max-rows 50
```

Output:
```json
{
  "rows": [{"col1": "val1", "col2": 42}, ...],
  "total_rows": 1500,
  "rows_returned": 50,
  "bytes_processed": 10485760,
  "bytes_processed_human": "10.0 MB",
  "schema": [
    {"name": "col1", "type": "STRING",  "mode": "NULLABLE"},
    {"name": "col2", "type": "INTEGER", "mode": "NULLABLE"}
  ]
}
```

`--max-rows` caps the rows returned (default: 1000). The query still scans all data — only the returned JSON is truncated. `total_rows` reflects the full result set size.

---

### `dry-run` — Validate SQL without executing

Use this **before** running an expensive query to check for syntax errors and estimate cost.

```bash
python tools/bigquery_tools.py dry-run \
  --sql "SELECT * FROM \`my-project.my_dataset.my_table\`"

python tools/bigquery_tools.py dry-run \
  --file converted_egps/dbt/my_model/models/my_model.sql
```

Output:
```json
{
  "valid": true,
  "bytes_estimated": 52428800,
  "bytes_estimated_human": "50.0 MB"
}
```

If the SQL is invalid, BigQuery returns an error and the tool exits non-zero with a diagnostic message.

---

### `list-datasets` — List all datasets in the project

```bash
python tools/bigquery_tools.py list-datasets
```

Output:
```json
[
  {"id": "raw_data",   "location": "US", "created": "2024-01-15T10:00:00+00:00", "modified": "..."},
  {"id": "dbt_models", "location": "US", "created": "2024-03-01T08:30:00+00:00", "modified": "..."}
]
```

---

### `list-tables` — List tables in a dataset

```bash
python tools/bigquery_tools.py list-tables --dataset raw_data

# If GCP_DATASET is set, --dataset can be omitted:
python tools/bigquery_tools.py list-tables
```

Output:
```json
[
  {"id": "orders",    "full_id": "my-project.raw_data.orders",    "type": "TABLE"},
  {"id": "customers", "full_id": "my-project.raw_data.customers", "type": "TABLE"},
  {"id": "v_summary", "full_id": "my-project.raw_data.v_summary", "type": "VIEW"}
]
```

`type` is `TABLE`, `VIEW`, or `EXTERNAL`.

---

### `get-table` — Get schema and metadata for a specific table

```bash
python tools/bigquery_tools.py get-table \
  --dataset raw_data \
  --table orders
```

Output:
```json
{
  "full_id": "my-project.raw_data.orders",
  "type": "TABLE",
  "rows": 4200000,
  "size_bytes": 524288000,
  "size_human": "500.0 MB",
  "created": "2024-01-15T10:00:00+00:00",
  "modified": "2024-04-10T14:22:00+00:00",
  "description": "Raw orders from ERP system",
  "schema": [
    {"name": "order_id",   "type": "STRING",    "mode": "REQUIRED", "description": ""},
    {"name": "order_date", "type": "DATE",       "mode": "NULLABLE", "description": ""},
    {"name": "amount",     "type": "NUMERIC",    "mode": "NULLABLE", "description": ""},
    {"name": "status",     "type": "STRING",     "mode": "NULLABLE", "description": ""}
  ]
}
```

---

## Integration with the migration pipeline

After `/tradutor` generates a converted dbt model, use `/bigquery` to validate it before committing:

```bash
# 1. Validate SQL syntax (free — no data scanned)
python tools/bigquery_tools.py dry-run \
  --file converted_egps/dbt/my_model/models/my_model.sql

# 2. If valid, run a small sample to verify row shape
python tools/bigquery_tools.py query \
  --file converted_egps/dbt/my_model/models/my_model.sql \
  --max-rows 5

# 3. Cross-check source table schema to catch missing columns
python tools/bigquery_tools.py get-table \
  --dataset source_dataset \
  --table source_table
```

After `/auditor` produces an audit report, use the query output to attach data-based evidence to a PR comment via `/github add-comment`.

---

## Good Practices

### 1. Mandatory Pre-Query Checklist

Every time a `query` is needed, execute these three steps in order — no exceptions:

**Step 1 — Dry run**
Always run `dry-run` first. Report `bytes_estimated_human` to the user before doing anything else.
```bash
python tools/bigquery_tools.py dry-run --sql "SELECT ..."
```

**Step 2 — Row count**
After the dry run, run an auxiliary count query to know the full result size:
```bash
python tools/bigquery_tools.py query \
  --sql "SELECT COUNT(*) AS n FROM (<original query without LIMIT>)"
```
Report the row count to the user before fetching rows.

**Step 3 — Fetch with limit**
Only then run the actual query, with `--max-rows 10` (see rule below).

---

### 2. Default Row Limit

- **Always** pass `--max-rows 10` unless one of the following is true:
  - The env var `DISABLE_BQ_QUERY_LIMIT=true` is set
  - The user has explicitly granted a one-time exception for the current query
- If more rows are genuinely needed, explain why and ask the user before proceeding:
  > "This query would return N rows. I need to fetch up to X because [reason]. Can I proceed?"

---

### 3. Comparison Queries — Let BigQuery Do the Work

Never fetch two result sets and compare them inside the response. That wastes tokens and is slower.

Instead, write a single query that performs the comparison inside BigQuery and returns only a summary:

```sql
-- Pattern: FULL JOIN two CTEs, aggregate mismatches
WITH a AS (
  -- first query
),
b AS (
  -- second query
)
SELECT
  COUNTIF(a.key IS NULL)   AS missing_in_a,
  COUNTIF(b.key IS NULL)   AS missing_in_b,
  COUNTIF(a.col != b.col)  AS value_mismatches,
  COUNT(*)                 AS total_rows
FROM a
FULL JOIN b USING (key)
```

This returns 1 row instead of N×2 rows, and BigQuery handles all the matching logic.

---

### 4. Token Cost Warnings

Before any operation that could produce a large output, warn the user and ask for permission. Mandatory triggers:

| Trigger | Action |
|---------|--------|
| Row count estimate > 10 and no limit exception granted | Ask before fetching |
| Dry-run estimate > 1 GB | Warn and ask before running |
| Schema with > 50 columns | Warn before fetching full schema |
| Multiple large queries in sequence | Summarize cumulative cost estimate first |

---

### 5. Prefer INFORMATION_SCHEMA for Metadata

When the goal is schema inspection, table sizes, or row counts, use `INFORMATION_SCHEMA` directly instead of `get-table` or `list-tables`. It is cheaper, faster, and returns exactly what is needed.

```sql
-- Column schema for a specific table
SELECT column_name, data_type, is_nullable
FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'my_table'
ORDER BY ordinal_position

-- Row counts and sizes for all tables in a dataset
SELECT table_id, row_count, size_bytes,
       ROUND(size_bytes / 1e9, 3) AS size_gb
FROM `project.dataset.__TABLES__`
ORDER BY size_bytes DESC

-- Partition info
SELECT table_name, partition_id, total_rows
FROM `project.dataset.INFORMATION_SCHEMA.PARTITIONS`
WHERE table_name = 'my_table'
```

Whenever you need to query INFORMATION_SCHEMA.TABLES (which the user might not have access to), query the INFORMATION_SCHEMA.COLUMNS instead.

---

### 6. Temporary Tables

Temporary tables are allowed in the dataset declared in `GCP_DATASET` when they help avoid repeated scans or large intermediate outputs.

**Rules:**
- **Naming format:** `temp_YYYY_MM_DD_HH_MM_SS_<short_description>`
  - Use the current UTC timestamp at creation time
  - Example: `temp_2026_04_29_14_35_22_citibike_agg`
- **Always inform the user** when a temp table is created: name, dataset, and purpose
- **Never DROP any table without explicit user permission.** When a temp table is no longer needed, inform the user and ask whether to drop it:
  > "`temp_2026_04_29_14_35_22_citibike_agg` is no longer needed. Would you like me to drop it?"

---

## Error reference

| Error message | Cause | Fix |
|--------------|-------|-----|
| `Missing required environment variable(s): GCP_PROJECT_ID` | Env var not set | `export GCP_PROJECT_ID=...` |
| `No dataset specified` | `--dataset` omitted and `GCP_DATASET` not set | Add `--dataset` or set `GCP_DATASET` |
| `google-cloud-bigquery is not installed` | Missing dependency | `pip install -r requirements.txt` |
| `BigQuery API error: 403 ...` | Missing IAM permissions | Grant `roles/bigquery.dataViewer` + `roles/bigquery.jobUser` to the service account |
| `BigQuery API error: 404 Not found` | Dataset or table doesn't exist | Check project/dataset/table names |
| `BigQuery API error: 400 Syntax error` | Invalid SQL | Run `dry-run` to see the exact error location |

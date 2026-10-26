# Databricks Connection Test — Build Record

## Original Request

```prompt
plan a set of tests to verify if all the tools are working properly. we'll run the tests a single time right after the cluster is on. it's not for production environment

save this plan in a md file in /tools

if the DBFS root is disabled by workspace policy, is it possible to adapt the tool to use relative paths?
```

---

## Follow-up Adjustments

**DBFS relative path support** — The workspace has DBFS root (`/`) disabled by security policy. Added `DATABRICKS_DBFS_BASE` env var (e.g. `/FileStore`) to `databricks_tools.py`. Relative paths passed to DBFS subcommands are resolved against this base. Absolute paths (starting with `/`) are passed through unchanged. DBFS tests auto-SKIP if the workspace policy still denies access, instead of failing the suite.

---

## Plan

### Context

`tools/databricks_tools.py` was built and spot-checked manually (individual commands run from the CLI). Before the project uses it in regular operation, we want a single diagnostic run that exercises every public method against the live workspace while the cluster is warm and reports a clear PASS / FAIL / SKIP for each one. This is not a pytest suite — no fixtures, no parametrize, no `conftest.py` — just a script that can be read at a glance.

**Known workspace state at time of writing:**
- Cluster: `ind-dbk-shared` — ID `0120-202649-002gtmoi`
- SQL Warehouse: ID stored in `DATABRICKS_DEFAULT_CLUSTER_ID` (env var dual-purpose)
- Default catalog: `client_journey` / Default schema: `default`
- Known table: `client_journey.default.lib_list`
- No jobs defined in workspace; no volumes in `client_journey.default`
- DBFS root disabled by workspace security policy; `/FileStore` is accessible

---

### Files Created / Modified

| File | Action |
|------|--------|
| `tools/test_databricks_connection.py` | Create — one-time diagnostic script |
| `tools/test_databricks_connection.md` | Create — this build record |
| `tools/databricks_tools.py` | Modify — add `DATABRICKS_DBFS_BASE` env var + relative DBFS path resolution |

---

### Prerequisites: DBFS Relative Path Support

**Problem:** Paths like `/mnt` and `/` are denied by workspace security policy.

**Solution:** `DATABRICKS_DBFS_BASE` optional env var (e.g. `/FileStore`):
- Paths starting with `/` → used as-is (absolute, unchanged)
- Paths not starting with `/` → prepended with the base (`myfile.txt` → `/FileStore/myfile.txt`)

**Changes to `tools/databricks_tools.py`:**
- `_load_config()` returns a 6-tuple (added `default_dbfs_base`)
- `DatabricksClient.__init__` accepts and stores `default_dbfs_base`
- `_resolve_dbfs_path(path)` helper applies the resolution logic
- `dbfs_ls`, `dbfs_put`, `dbfs_get`, `dbfs_rm` all call `_resolve_dbfs_path`
- `main()` unpacks the 6th value and passes it to the client

---

### Test Script Design

**Approach:** Import `DatabricksClient` and `_load_config` directly from `tools.databricks_tools` (same process, no subprocess). Instantiate the client once from env vars. Call each method, catch exceptions, collect `(status, label, detail)` tuples, print at the end.

**Constants (overridable via env vars):**

| Constant | Source |
|----------|--------|
| `WAREHOUSE_ID` | `DATABRICKS_DEFAULT_WAREHOUSE_ID` or `DATABRICKS_DEFAULT_CLUSTER_ID` |
| `CLUSTER_ID` | Hard-coded `0120-202649-002gtmoi` |
| `TEST_CATALOG` | `"client_journey"` |
| `TEST_SCHEMA` | `"default"` |
| `TEST_TABLE` | `"client_journey.default.lib_list"` |
| `TEST_NOTEBOOK` | `TEST_NOTEBOOK_PATH` env var (optional) |
| `DBFS_BASE` | `DATABRICKS_DBFS_BASE` env var (default `"/FileStore"`) |

---

### Test Cases

| # | Label | Method | Pass condition | On error |
|---|-------|--------|----------------|----------|
| 1 | `cluster-list` | `cluster_list()` | List ≥1 item; each has `cluster_id`, `name`, `state` | FAIL |
| 2 | `cluster-get` | `cluster_get("0120-202649-002gtmoi")` | Dict with `cluster_id`, `state` | FAIL |
| 3 | `sql-run: SELECT 1` | `sql_run("SELECT 1 AS n", WAREHOUSE_ID)` | `rows[0]["n"] == "1"` | SKIP if no warehouse ID |
| 4 | `sql-run: real table` | `sql_run("SELECT * FROM lib_list LIMIT 5", WAREHOUSE_ID)` | Non-empty `rows` and `schema` | SKIP if no warehouse ID |
| 5 | `uc-catalogs` | `uc_catalogs()` | List contains `client_journey` | FAIL |
| 6 | `uc-schemas` | `uc_schemas("client_journey")` | List contains `default` | FAIL |
| 7 | `uc-tables` | `uc_tables("client_journey", "default")` | List contains `lib_list` | FAIL |
| 8 | `uc-get-table` | `uc_get_table("client_journey.default.lib_list")` | Dict with `full_name`, non-empty `columns` | FAIL |
| 9 | `volume-list` | `volume_list("client_journey", "default")` | Returns a list (empty is fine) | FAIL |
| 10 | `job-list` | `job_list()` | Returns a list (empty is fine) | FAIL |
| 11 | `dbfs-ls` | `dbfs_ls("/FileStore")` | Returns a list | SKIP if policy error |
| 12 | `dbfs-put/get/rm` | Round-trip: put temp file → get → verify → rm | Content matches original bytes | SKIP if policy error |
| 13 | `notebook-run` | `notebook_run(TEST_NOTEBOOK, CLUSTER_ID, wait=True)` | Dict with `run_id`, `state` | SKIP if `TEST_NOTEBOOK_PATH` not set |
| 14 | `cluster-stop` | — | **Always SKIP** — don't terminate cluster during tests | — |
| 15 | `job-run / job-run-status` | — | **Always SKIP** — no jobs defined | — |
| 16 | `volume-get` | — | **Always SKIP** — no volumes in default schema | — |

---

### Output Format

```
Running Databricks connection tests...
────────────────────────────────────────────────────────
 PASS  cluster-list                 1 cluster(s) found
 PASS  cluster-get                  state=RUNNING
 PASS  sql-run: SELECT 1            rows=[{'n': '1'}]
 PASS  sql-run: real table          5 rows, 3 columns
 PASS  uc-catalogs                  4 catalogs found
 PASS  uc-schemas                   7 schemas in client_journey
 PASS  uc-tables                    2 tables in client_journey.default
 PASS  uc-get-table                 client_journey.default.lib_list: 12 columns
 PASS  volume-list                  0 volumes (empty is ok)
 PASS  job-list                     0 jobs (empty is ok)
 SKIP  dbfs-ls                      DBFS access denied by workspace policy (/FileStore)
 SKIP  dbfs-put/get/rm              DBFS access denied by workspace policy
 SKIP  notebook-run                 TEST_NOTEBOOK_PATH not set
 SKIP  cluster-stop                 skipped to keep cluster warm during tests
 SKIP  job-run                      no jobs defined in workspace
 SKIP  job-run-status               no jobs defined in workspace
 SKIP  volume-get                   no volumes in client_journey.default

────────────────────────────────────────────────────────
10 passed · 0 failed · 7 skipped
```

Exit code 0 if no failures, 1 if any FAIL.

---

### Verification

```bash
# Source env vars (set -a ensures they're exported to Python subprocess)
set -a && source .env && set +a

# Run tests (MSYS_NO_PATHCONV=1 prevents Git Bash path mangling)
MSYS_NO_PATHCONV=1 ../../venv/Scripts/python tools/test_databricks_connection.py

# Enable verbose tracebacks on failure
DATABRICKS_TEST_VERBOSE=1 MSYS_NO_PATHCONV=1 ../../venv/Scripts/python tools/test_databricks_connection.py

# Test notebook-run (requires a valid workspace notebook path)
TEST_NOTEBOOK_PATH=/Workspace/Users/you@company.com/test_notebook \
  MSYS_NO_PATHCONV=1 ../../venv/Scripts/python tools/test_databricks_connection.py
```

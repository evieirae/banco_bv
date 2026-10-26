
# Bigquery Tools Good Practices — Build Record

## Original Request

```prompt
add good practices to the bigquery skill in order to prevent excessive and unnecessary tolken use by claude. also, add good practices for using bigquery. here are a few suggestions: before running a query, always run a dry run to measure the total bytes that will be billed and get na idea of the potential output size in case no precautions are taken; before running a query, always run an auxiliary query to count the number of rows it will return as output (do this after the dry run); when running a query, always set a limit of 10 rows unless the environment variable DISABLE_BQ_QUERY_LIMIT is true (ask the user to allow an one-time exception and increase the limit if you judge that it will be necessary for a reason); when solving a problem that needs to compare query results, don't fetch the query results directly, make bigquery to the processing for you, returning in a few rows only the result of the comparison you need (this can be achived by full joining two tables or CTEs and agregating the results after counting them); warn the user if you judge that one particular operation might use too many tolkens and ask for permission first; use the information_schema whenever you need to save query and tolken costs; you are allowed to create temporary tables in the user's development dataset declared in GCP_DATASET if it helps you, but you shoud always start their names with the prefix "temp_AAAA_MM_DD_HH_MM_SS_", where AAAA_MM_DD_HH_MM_SS_ is the current timestamp. 

```

---

Here is the implementation plan that was used:

# Planning Document

## Good Practices — Added to SKILL.md

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
Only then run the actual query, with `--max-rows 20` (see rule below).

---

### 2. Default Row Limit

- **Always** pass `--max-rows 20` unless one of the following is true:
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


| Trigger                                                | Action                                   |
| ------------------------------------------------------ | ---------------------------------------- |
| Row count estimate > 20 and no limit exception granted | Ask before fetching                      |
| Dry-run estimate > 1 GB                                | Warn and ask before running              |
| Schema with > 50 columns                               | Warn before fetching full schema         |
| Multiple large queries in sequence                     | Summarize cumulative cost estimate first |


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
FROM `project.dataset.__TABLES_`_
ORDER BY size_bytes DESC

-- Partition info
SELECT table_name, partition_id, total_rows
FROM `project.dataset.INFORMATION_SCHEMA.PARTITIONS`
WHERE table_name = 'my_table'
```

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


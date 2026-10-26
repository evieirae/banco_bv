"""
BigQuery interaction tool for the SAS migration pipeline.

Usage:
    python tools/bigquery_tools.py <subcommand> [options]

Authentication (pick one):
    Option A — Application Default Credentials (ADC):
        Run once: gcloud auth application-default login
        No env var needed. Works automatically afterwards.

    Option B — Service account key file:
        Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account_key.json
        The key file is a JSON file downloaded from the GCP Console under
        IAM & Admin > Service Accounts > your account > Keys > Add Key.

Required env var:
    GCP_PROJECT_ID      Google Cloud project ID (e.g. my-gcp-project)

Optional env vars:
    GCP_DATASET         Default dataset; used when --dataset is omitted
    GOOGLE_APPLICATION_CREDENTIALS  Path to service account JSON key (Option B)

BigQuery concepts:
    Project   Top-level GCP billing/resource container. All query costs are billed here.
    Dataset   Namespace for tables — analogous to a schema in Postgres.
    Table     Stores the actual data. Fully-qualified name: `project.dataset.table`
    Job       Every query creates a Job. The SDK waits for it to finish via .result().
    Dry run   Validates SQL and estimates bytes billed without executing the query.
    Schema    A table's column definitions: name, data type, mode (NULLABLE/REQUIRED/REPEATED).
    Bytes billed  BigQuery bills per bytes scanned, rounded up to 10 MB per query.

Subcommands:
    query           Run a SQL query and return rows as JSON
    dry-run         Validate SQL and estimate cost — does NOT execute
    list-datasets   List all datasets in the project
    list-tables     List tables in a dataset
    get-table       Get schema and metadata for a specific table
"""

import argparse
import datetime
import decimal
import json
import os
import sys


def _load_config():
    missing = []
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        missing.append("GCP_PROJECT_ID")
    if missing:
        print(
            f"ERROR: Missing required environment variable(s): {', '.join(missing)}\n"
            "Set them before running this tool:\n"
            "  GCP_PROJECT_ID  - Google Cloud project ID (e.g. my-gcp-project)\n\n"
            "Authentication (pick one):\n"
            "  Option A (ADC): run `gcloud auth application-default login` once\n"
            "  Option B (SA key): set GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json",
            file=sys.stderr,
        )
        sys.exit(1)
    default_dataset = os.environ.get("GCP_DATASET")
    return project_id, default_dataset


def _require_bq():
    try:
        from google.cloud import bigquery
        from google.api_core.exceptions import GoogleAPIError
        return bigquery, GoogleAPIError
    except ImportError:
        print(
            "ERROR: google-cloud-bigquery is not installed.\n"
            "Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)


def _serialize_value(v):
    """Convert BigQuery-specific types to JSON-safe Python values."""
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _serialize_row(row):
    return {k: _serialize_value(v) for k, v in row.items()}


def _bytes_human(n: int) -> str:
    """Format a byte count into a human-readable string."""
    if n is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


class BigQueryClient:
    def __init__(self, project_id: str, default_dataset: str | None):
        bigquery, self._GoogleAPIError = _require_bq()
        self._project = project_id
        self._default_dataset = default_dataset
        self._client = bigquery.Client(project=project_id)
        self._bq = bigquery

    def _resolve_dataset(self, dataset_id: str | None) -> str:
        ds = dataset_id or self._default_dataset
        if not ds:
            print(
                "ERROR: No dataset specified. Pass --dataset or set GCP_DATASET.",
                file=sys.stderr,
            )
            sys.exit(1)
        return ds

    def _api_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except self._GoogleAPIError as exc:
            print(f"ERROR: BigQuery API error: {exc}", file=sys.stderr)
            sys.exit(1)

    # --- Query ---

    def query(self, sql: str, max_rows: int = 1000) -> dict:
        job_config = self._bq.QueryJobConfig()
        job = self._api_call(self._client.query, sql, job_config=job_config)
        result = self._api_call(job.result)
        rows = [_serialize_row(row) for row in list(result)[:max_rows]]
        schema = [
            {"name": f.name, "type": f.field_type, "mode": f.mode}
            for f in result.schema
        ]
        return {
            "rows": rows,
            "total_rows": result.total_rows,
            "rows_returned": len(rows),
            "bytes_processed": job.total_bytes_processed,
            "bytes_processed_human": _bytes_human(job.total_bytes_processed),
            "schema": schema,
        }

    def dry_run(self, sql: str) -> dict:
        job_config = self._bq.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = self._api_call(self._client.query, sql, job_config=job_config)
        estimated = job.total_bytes_processed
        return {
            "valid": True,
            "bytes_estimated": estimated,
            "bytes_estimated_human": _bytes_human(estimated),
        }

    # --- Inspect ---

    def list_datasets(self) -> list:
        datasets = self._api_call(list, self._client.list_datasets())
        result = []
        for ds in datasets:
            ref = self._api_call(self._client.get_dataset, ds.dataset_id)
            result.append({
                "id": ds.dataset_id,
                "location": ref.location,
                "created": ref.created.isoformat() if ref.created else None,
                "modified": ref.modified.isoformat() if ref.modified else None,
            })
        return result

    def list_tables(self, dataset_id: str | None = None) -> list:
        ds = self._resolve_dataset(dataset_id)
        tables = self._api_call(list, self._client.list_tables(ds))
        result = []
        for t in tables:
            entry = {
                "id": t.table_id,
                "full_id": f"{self._project}.{ds}.{t.table_id}",
                "type": t.table_type,
            }
            # row/size info requires a full get_table call; skip to keep it fast
            result.append(entry)
        return result

    def get_table(self, dataset_id: str | None, table_id: str) -> dict:
        ds = self._resolve_dataset(dataset_id)
        ref = f"{self._project}.{ds}.{table_id}"
        table = self._api_call(self._client.get_table, ref)
        schema = [
            {
                "name": f.name,
                "type": f.field_type,
                "mode": f.mode,
                "description": f.description or "",
            }
            for f in table.schema
        ]
        return {
            "full_id": str(table.reference),
            "type": table.table_type,
            "rows": table.num_rows,
            "size_bytes": table.num_bytes,
            "size_human": _bytes_human(table.num_bytes),
            "created": table.created.isoformat() if table.created else None,
            "modified": table.modified.isoformat() if table.modified else None,
            "description": table.description or "",
            "schema": schema,
        }


# --- CLI ---

def _read_sql(args) -> str:
    if args.sql:
        return args.sql
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        print(f"ERROR: Cannot read SQL file: {exc}", file=sys.stderr)
        sys.exit(1)


def _print(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        prog="bigquery_tools",
        description="BigQuery interaction tool for the SAS migration pipeline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # query
    p_query = sub.add_parser("query", help="Run a SQL query and return rows as JSON")
    sql_group = p_query.add_mutually_exclusive_group(required=True)
    sql_group.add_argument("--sql", help="SQL string to execute")
    sql_group.add_argument("--file", metavar="PATH", help="Path to a .sql file")
    p_query.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        metavar="N",
        help="Maximum rows to return (default: 1000)",
    )

    # dry-run
    p_dry = sub.add_parser(
        "dry-run",
        help="Validate SQL and estimate bytes billed — does NOT execute the query",
    )
    dry_group = p_dry.add_mutually_exclusive_group(required=True)
    dry_group.add_argument("--sql", help="SQL string to validate")
    dry_group.add_argument("--file", metavar="PATH", help="Path to a .sql file")

    # list-datasets
    sub.add_parser("list-datasets", help="List all datasets in the project")

    # list-tables
    p_tables = sub.add_parser("list-tables", help="List tables in a dataset")
    p_tables.add_argument(
        "--dataset",
        metavar="DATASET_ID",
        help="Dataset ID (omit to use GCP_DATASET env var)",
    )

    # get-table
    p_get = sub.add_parser("get-table", help="Get schema and metadata for a table")
    p_get.add_argument(
        "--dataset",
        metavar="DATASET_ID",
        help="Dataset ID (omit to use GCP_DATASET env var)",
    )
    p_get.add_argument("--table", required=True, metavar="TABLE_ID")

    args = parser.parse_args()
    project_id, default_dataset = _load_config()
    client = BigQueryClient(project_id, default_dataset)

    if args.cmd == "query":
        _print(client.query(_read_sql(args), args.max_rows))
    elif args.cmd == "dry-run":
        _print(client.dry_run(_read_sql(args)))
    elif args.cmd == "list-datasets":
        _print(client.list_datasets())
    elif args.cmd == "list-tables":
        _print(client.list_tables(getattr(args, "dataset", None)))
    elif args.cmd == "get-table":
        _print(client.get_table(getattr(args, "dataset", None), args.table))


if __name__ == "__main__":
    main()

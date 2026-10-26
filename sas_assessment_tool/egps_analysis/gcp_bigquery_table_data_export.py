#!/usr/bin/env python3
"""
======================================
Author: derived from gcp_bigquery_inventory.py
======================================

Export BigQuery **rows** from a full-table read (SELECT *) or from **custom SQL** (`--query` / `--query-file`).

Table reference: `--from-json` (inventory JSON: project_id, dataset_id, table_id) or `--project` / `--dataset` / `--table`.

Authentication (same as inventory script):
  - GOOGLE_APPLICATION_CREDENTIALS, or
  - gcloud auth application-default login

If you get 403 "does not have bigquery.jobs.create" on the table's project, ask an admin for
roles/bigquery.jobUser (or bigquery.user) on that project, or use --job-project to run the
query job in another GCP project where you can create jobs (you still need read access to the
dataset/table).

Usage:
  python gcp_bigquery_table_data_export.py \\
    --project bv-pdbd-prd --dataset trusted_chameleon --table tbindicadoringestao \\
    --format csv --output ./tbindicadoringestao.csv

  python gcp_bigquery_table_data_export.py --from-json table.json --format csv --output table.csv --limit 1000

  python gcp_bigquery_table_data_export.py \\
    --project bv-pdbd-prd --dataset trusted_chameleon --table tbindicadoringestao \\
    --job-project bv-geminiia-prd --format csv -o ./out.csv

  # Arbitrary SQL (--job-project = where the query job runs; omit to use ADC default project)
  python gcp_bigquery_table_data_export.py \\
    --query "SELECT id, name FROM \`bv-pdbd-prd.trusted_foo.bar\` LIMIT 10" \\
    --format ndjson -o -
  # PowerShell: use single quotes around SQL so backticks are not interpreted by the shell.

  python gcp_bigquery_table_data_export.py --query-file ./myquery.sql --job-project bv-pdbd-prd -o out.csv --format csv

Windows cmd.exe: long SQL with parentheses in -q \"...\" may be split into multiple arguments; the script
would then not receive your full SELECT list (symptom: CSV with all table columns as if SELECT *). Prefer
--query-file, pipe to --query-file -, or PowerShell with single-quoted SQL. Use --verbose to print the
exact SQL before execution, or --dry-run-sql to print without running.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional

try:
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import bigquery
    from google.cloud.exceptions import GoogleCloudError
except ImportError:
    print(
        "Missing dependency: google-cloud-bigquery. Install with: pip install google-cloud-bigquery",
        file=sys.stderr,
    )
    raise SystemExit(1)


CREDENTIALS_HINT = """\
No Google Cloud credentials found. BigQuery needs Application Default Credentials. Use one of:

  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

  gcloud auth application-default login

See: https://cloud.google.com/docs/authentication/application-default-credentials
"""


def print_credentials_hint() -> None:
    print(CREDENTIALS_HINT, file=sys.stderr, end="")


def load_table_ref_from_json(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in ("project_id", "dataset_id", "table_id"):
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            print(f"Invalid or missing '{key}' in {path}", file=sys.stderr)
            raise SystemExit(2)
    return {
        "project_id": data["project_id"].strip(),
        "dataset_id": data["dataset_id"].strip(),
        "table_id": data["table_id"].strip(),
    }


def value_to_plain(v: Any) -> Any:
    """Convert BigQuery cell values to JSON-friendly Python types (nested RECORD/REPEATED supported)."""
    if v is None:
        return None
    if isinstance(v, bigquery.table.Row):
        return {k: value_to_plain(v[k]) for k in v.keys()}
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, dict):
        return {k: value_to_plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [value_to_plain(x) for x in v]
    return v


def row_to_plain(row: bigquery.table.Row) -> Dict[str, Any]:
    """BigQuery Row -> dict with JSON-friendly scalars."""
    return {k: value_to_plain(row[k]) for k in row.keys()}


def iter_query_rows(
    client: bigquery.Client,
    sql: str,
    job_config: Optional[bigquery.QueryJobConfig] = None,
) -> Iterator[bigquery.table.Row]:
    cfg = job_config or bigquery.QueryJobConfig(use_legacy_sql=False)
    job = client.query(sql, job_config=cfg)
    yield from job.result()


def export_rows_to_output(
    rows_iter: Iterator[bigquery.table.Row],
    output_path: Optional[str],
    fmt: str,
    quiet: bool = False,
) -> int:
    """Stream BigQuery rows to file or stdout. Returns number of rows written."""
    count = 0

    if fmt == "csv":
        if not output_path or output_path == "-":
            print("--format csv requires --output FILE (not stdout)", file=sys.stderr)
            raise SystemExit(2)
        fieldnames: Optional[List[str]] = None
        csv_file = open(output_path, "w", newline="", encoding="utf-8")
        writer: Optional[csv.DictWriter] = None
        try:
            for row in rows_iter:
                plain = row_to_plain(row)
                if fieldnames is None:
                    fieldnames = list(plain.keys())
                    if not quiet:
                        print(
                            f"[gcp_bigquery_table_data_export] Result columns ({len(fieldnames)}): {', '.join(fieldnames[:40])}"
                            + (" ..." if len(fieldnames) > 40 else ""),
                            file=sys.stderr,
                            flush=True,
                        )
                    writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                assert writer is not None
                writer.writerow({k: ("" if plain[k] is None else str(plain[k])) for k in fieldnames})
                count += 1
                if not quiet and count % 5000 == 0:
                    print(f"[{count}] rows...", file=sys.stderr, flush=True)
        finally:
            csv_file.close()
        if not quiet:
            print(f"Finished: {count} row(s) -> {output_path}", file=sys.stderr, flush=True)
        return count

    out_f = sys.stdout if not output_path or output_path == "-" else open(output_path, "w", encoding="utf-8")
    try:
        if fmt == "json":
            out_f.write("[\n")
            first = True
            for row in rows_iter:
                plain = row_to_plain(row)
                line = json.dumps(plain, ensure_ascii=False)
                if not first:
                    out_f.write(",\n")
                out_f.write("  " + line)
                first = False
                count += 1
                if not quiet and count % 5000 == 0:
                    print(f"[{count}] rows...", file=sys.stderr, flush=True)
            out_f.write("\n]\n")
        else:  # ndjson
            for row in rows_iter:
                plain = row_to_plain(row)
                out_f.write(json.dumps(plain, ensure_ascii=False) + "\n")
                count += 1
                if not quiet and count % 5000 == 0:
                    print(f"[{count}] rows...", file=sys.stderr, flush=True)
    finally:
        if out_f is not sys.stdout:
            out_f.close()

    dest = output_path if output_path and output_path != "-" else "stdout"
    if not quiet:
        print(f"Finished: {count} row(s) -> {dest}", file=sys.stderr, flush=True)
    return count


def run_export(
    project_id: str,
    dataset_id: str,
    table_id: str,
    output_path: Optional[str],
    fmt: str,
    row_limit: Optional[int],
    dry_run_sql: bool,
    job_project: Optional[str] = None,
    quiet: bool = False,
) -> None:
    fq = f"`{project_id}.{dataset_id}.{table_id}`"
    if row_limit is not None and row_limit > 0:
        sql = f"SELECT * FROM {fq} LIMIT {int(row_limit)}"
    else:
        sql = f"SELECT * FROM {fq}"

    job_project_id = job_project.strip() if job_project else project_id

    if dry_run_sql:
        print(sql, file=sys.stderr)
        print(f"job project (BigQuery job runs here): {job_project_id}", file=sys.stderr)
        return

    client = bigquery.Client(project=job_project_id)
    rows_iter = iter_query_rows(client, sql)
    export_rows_to_output(rows_iter, output_path, fmt, quiet=quiet)


def _log_query_execution(sql: str, verbose: bool, quiet: bool) -> None:
    """Help debug shell truncation (e.g. Windows cmd.exe + parentheses in -q \"...\")."""
    if quiet:
        return
    n = len(sql)
    h = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]
    print(
        f"[gcp_bigquery_table_data_export] Custom SQL: {n} character(s), sha256-prefix={h}",
        file=sys.stderr,
        flush=True,
    )
    if verbose:
        print("----- BEGIN SQL (exact bytes sent to BigQuery) -----", file=sys.stderr)
        print(sql, file=sys.stderr)
        print("----- END SQL -----", file=sys.stderr, flush=True)


def run_export_from_query(
    sql: str,
    output_path: Optional[str],
    fmt: str,
    dry_run_sql: bool,
    job_project: Optional[str] = None,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    sql = sql.strip()
    if not sql:
        print("Query is empty.", file=sys.stderr)
        raise SystemExit(2)

    job_project_id = job_project.strip() if job_project else None

    if dry_run_sql:
        print(sql, file=sys.stderr)
        print(
            f"job project (BigQuery job runs here): {job_project_id or '(default from ADC / GOOGLE_CLOUD_PROJECT)'}",
            file=sys.stderr,
        )
        return

    _log_query_execution(sql, verbose=verbose, quiet=quiet)

    client = bigquery.Client(project=job_project_id)
    rows_iter = iter_query_rows(client, sql)
    export_rows_to_output(rows_iter, output_path, fmt, quiet=quiet)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export BigQuery query results: full table (SELECT *) or custom SQL (--query / --query-file).",
    )
    p.add_argument(
        "--from-json",
        dest="from_json",
        metavar="FILE",
        help="Per-table inventory JSON with project_id, dataset_id, table_id.",
    )
    p.add_argument(
        "--project",
        dest="project_id",
        metavar="PROJECT_ID",
        help="GCP project (use with --dataset and --table).",
    )
    p.add_argument("--dataset", dest="dataset_id", metavar="DATASET", help="Dataset id.")
    p.add_argument("--table", dest="table_id", metavar="TABLE", help="Table id.")
    p.add_argument(
        "--query",
        "-q",
        dest="query",
        metavar="SQL",
        default=None,
        help="Arbitrary BigQuery SQL to run. Mutually exclusive with table / --from-json.",
    )
    p.add_argument(
        "--query-file",
        dest="query_file",
        metavar="FILE",
        default=None,
        help="Read SQL from file (UTF-8). Use '-' to read SQL from stdin (avoids cmd.exe breaking -q \"...\" on parentheses).",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="With --query / --query-file: print the full SQL to stderr before running (useful to verify the shell did not truncate -q).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress lines and the default SQL length/hash log on stderr.",
    )
    p.add_argument(
        "--output",
        "-o",
        dest="output_path",
        metavar="FILE",
        help="Output file. Default or '-' = stdout (not allowed for --format csv).",
    )
    p.add_argument(
        "--format",
        choices=("json", "ndjson", "csv"),
        default="json",
        help="Output format: JSON array, newline-delimited JSON, or CSV.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Add LIMIT N to the built-in SELECT * query (table / JSON modes only; ignored with --query / --query-file).",
    )
    p.add_argument(
        "--dry-run-sql",
        action="store_true",
        help="Print the SQL and exit without running the export.",
    )
    p.add_argument(
        "--job-project",
        dest="job_project",
        metavar="PROJECT_ID",
        default=None,
        help="Project used to run the BigQuery query job (billing/job quota). "
        "Default: same as --project / table project. Use when you lack bigquery.jobs.create on the "
        "data project but can create jobs elsewhere and may read the table cross-project.",
    )
    args = p.parse_args()

    has_json = bool(args.from_json)
    has_query_text = bool(args.query and args.query.strip())
    has_query_file = bool(args.query_file)
    has_table = bool(args.project_id and args.dataset_id and args.table_id)
    partial_table = bool(args.project_id or args.dataset_id or args.table_id) and not has_table

    mode_count = sum([has_json, has_table, has_query_text or has_query_file])
    if mode_count == 0:
        print(
            "Specify one source: --from-json, or (--project, --dataset, --table), or --query / --query-file.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if mode_count > 1:
        print("Use only one of: --from-json, table (--project/--dataset/--table), --query, --query-file.", file=sys.stderr)
        raise SystemExit(2)
    if partial_table:
        print("--project, --dataset, and --table must be given together.", file=sys.stderr)
        raise SystemExit(2)
    if has_query_text and has_query_file:
        print("Use either --query or --query-file, not both.", file=sys.stderr)
        raise SystemExit(2)

    if args.limit is not None and args.limit < 1:
        print("--limit must be >= 1 when set.", file=sys.stderr)
        raise SystemExit(2)

    jp = (args.job_project or "").strip()
    job_project = jp if jp else None

    try:
        if has_query_text or has_query_file:
            if has_query_file:
                qpath = args.query_file.strip()
                if qpath == "-":
                    sql = sys.stdin.read()
                else:
                    with open(qpath, encoding="utf-8") as qf:
                        sql = qf.read()
            else:
                sql = args.query
            if args.limit is not None:
                print(
                    "Note: --limit is ignored when using --query / --query-file; add LIMIT in SQL if needed.",
                    file=sys.stderr,
                )
            run_export_from_query(
                sql,
                args.output_path,
                args.format,
                args.dry_run_sql,
                job_project,
                verbose=args.verbose,
                quiet=args.quiet,
            )
        elif has_json:
            ref = load_table_ref_from_json(args.from_json)
            run_export(
                ref["project_id"],
                ref["dataset_id"],
                ref["table_id"],
                args.output_path,
                args.format,
                args.limit,
                args.dry_run_sql,
                job_project,
                quiet=args.quiet,
            )
        else:
            run_export(
                args.project_id.strip(),
                args.dataset_id.strip(),
                args.table_id.strip(),
                args.output_path,
                args.format,
                args.limit,
                args.dry_run_sql,
                job_project,
                quiet=args.quiet,
            )
    except DefaultCredentialsError:
        print_credentials_hint()
        raise SystemExit(2)
    except GoogleCloudError as e:
        print(f"GCP error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

# Executar via CLI o comando abaixo
"""
python gcp_bigquery_table_data_export.py -q "SELECT NmTabela, NmTabelaWork, NmTabelaOrigem, DsOrigem, NmFonteDados, DtFimIngestao FROM bv-pdbd-prd.trusted_chameleon.tbindicadoringestao QUALIFY ROW_NUMBER() OVER (PARTITION BY NmTabela ORDER BY DtFimIngestao DESC) = 1" --job-project bv-sadn-dtm --format csv --output ./src/chameleon.csv
"""
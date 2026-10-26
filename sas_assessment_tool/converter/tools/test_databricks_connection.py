"""
One-time connectivity test for databricks_tools.py.

Run after sourcing env vars:
    set -a && source .env && set +a
    MSYS_NO_PATHCONV=1 python tools/test_databricks_connection.py

Unity Catalog / SQL targets (defaults: ``system.information_schema.tables``, present on UC workspaces):

    DATABRICKS_TEST_CATALOG       Catalog name (default: system)
    DATABRICKS_TEST_SCHEMA        Schema name (default: information_schema)
    DATABRICKS_TEST_TABLE         Full three-part table name (optional; default:
                                  {catalog}.{schema}.{DATABRICKS_TEST_TABLE_NAME})
    DATABRICKS_TEST_TABLE_NAME    Table name only when TEST_TABLE not set (default: tables)

Volumes (optional; both tests skipped if unset):

    DATABRICKS_TEST_VOLUME        Full name catalog.schema.volume_name
    DATABRICKS_TEST_VOLUME_NAME   Expected volume name in listings (optional;
                                  default: last segment of DATABRICKS_TEST_VOLUME)

Jobs (optional):

    DATABRICKS_TEST_JOB_ID        Numeric job id (alias: TEST_JOB_ID). Unset or 0 = skip job-run.
    DATABRICKS_TEST_JOB_WAIT      If 1/true: wait for job to finish (can take a long time).
                                  Default 0: only triggers run_now and checks status once (smoke test).

Notebook (optional):

    DATABRICKS_TEST_NOTEBOOK_PATH   Workspace path (alias: TEST_NOTEBOOK_PATH). Unset = skip.

Cluster:

    DATABRICKS_DEFAULT_CLUSTER_ID   Required for cluster-get / notebook-run on cluster.
    DATABRICKS_DEFAULT_WAREHOUSE_ID or DATABRICKS_SQL_WAREHOUSE_ID
                                    Prefer warehouse for sql-run if cluster is single-user.

Smoke-test helpers:

    DATABRICKS_TEST_SKIP_SQL      If 1/true: skip sql-run tests (e.g. warehouse unset and cluster off).

Durante a execução, cada caso imprime TRIGGERED com data/hora local; se o caso demorar mais de 1 minuto,
linhas STILL_RUNNING são emitidas a cada minuto até o término.
"""

import contextlib
import io
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime

# ── Allow importing from project root ─────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.databricks_tools import DatabricksClient, _load_config


def _env_trim(key: str, default: str | None = None) -> str | None:
    """Lê variável de ambiente com trimming, aspas externas e comentário inline estilo dotenv (` # ...`)."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    s = raw.strip()
    if not s:
        return default
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    return s if s else default


def _parse_optional_job_id() -> int | None:
    raw = _env_trim("DATABRICKS_TEST_JOB_ID") or _env_trim("TEST_JOB_ID")
    if not raw or raw == "0":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_volume_three_part(full: str) -> tuple[str, str, str] | None:
    parts = full.split(".")
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[-1]


# ── Test constants (overridable via env; see module docstring) ─────────────────
WAREHOUSE_ID = _env_trim("DATABRICKS_DEFAULT_WAREHOUSE_ID") or _env_trim("DATABRICKS_SQL_WAREHOUSE_ID")
CLUSTER_ID = _env_trim("DATABRICKS_DEFAULT_CLUSTER_ID") or ""

TEST_CATALOG = _env_trim("DATABRICKS_TEST_CATALOG", "system") or "system"
TEST_SCHEMA = _env_trim("DATABRICKS_TEST_SCHEMA", "information_schema") or "information_schema"
TEST_TABLE_FULL = _env_trim("DATABRICKS_TEST_TABLE")
_table_short = _env_trim("DATABRICKS_TEST_TABLE_NAME", "tables") or "tables"
TEST_TABLE = TEST_TABLE_FULL or f"{TEST_CATALOG}.{TEST_SCHEMA}.{_table_short}"
TEST_TABLE_SHORT = TEST_TABLE.split(".")[-1]

TEST_VOLUME = _env_trim("DATABRICKS_TEST_VOLUME") or ""
_vol_override = _env_trim("DATABRICKS_TEST_VOLUME_NAME")
_vol_parsed = _parse_volume_three_part(TEST_VOLUME) if TEST_VOLUME else None
TEST_VOLUME_FOR_LIST = _vol_override or (_vol_parsed[2] if _vol_parsed else "")
TEST_VOLUME_CATALOG = _vol_parsed[0] if _vol_parsed else ""
TEST_VOLUME_SCHEMA = _vol_parsed[1] if _vol_parsed else ""

TEST_NOTEBOOK = _env_trim("DATABRICKS_TEST_NOTEBOOK_PATH") or _env_trim("TEST_NOTEBOOK_PATH") or ""
TEST_JOB_ID: int | None = _parse_optional_job_id()
DBFS_BASE = _env_trim("DATABRICKS_DBFS_BASE") or "/FileStore"

_job_wait_raw = (_env_trim("DATABRICKS_TEST_JOB_WAIT", "0") or "0").lower()
JOB_WAIT_FOR_COMPLETION = _job_wait_raw in ("1", "true", "yes", "on")

_skip_sql_raw = (_env_trim("DATABRICKS_TEST_SKIP_SQL") or "").lower()
SKIP_SQL_TESTS = _skip_sql_raw in ("1", "true", "yes", "on")

# ── Result tracking ───────────────────────────────────────────────────────────
_results: list[tuple[str, str, str]] = []   # (status, label, detail)
_job_run_id: int | None = None              # set by test_job_run, read by test_job_run_status

DBFS_POLICY_PHRASES = ("DBFS root is disabled", "Access is denied", "Public DBFS")
CMD_EXEC_SCOPE_PHRASES = ("required scopes: command-execution", "command-execution")


def _is_dbfs_policy_error(exc: Exception) -> bool:
    return any(p in str(exc) for p in DBFS_POLICY_PHRASES)


def _is_cmd_exec_scope_error(msg: str) -> bool:
    return any(p in msg for p in CMD_EXEC_SCOPE_PHRASES)


@contextlib.contextmanager
def _trap_exit():
    """Redirect stderr; convert SystemExit into RuntimeError(captured_message)."""
    buf = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = buf
    try:
        yield
    except SystemExit:
        raise RuntimeError(buf.getvalue().strip())
    finally:
        sys.stderr = old_stderr


def passed(label: str, detail: str) -> None:
    _results.append(("PASS", label, detail))


def failed(label: str, detail: str) -> None:
    _results.append(("FAIL", label, detail))


def skipped(label: str, reason: str) -> None:
    _results.append(("SKIP", label, reason))


def assert_keys(data, keys: list[str], context: str = "") -> None:
    target = data[0] if isinstance(data, list) and data else data
    if not isinstance(target, dict):
        return
    missing = [k for k in keys if k not in target]
    if missing:
        raise AssertionError(f"Missing keys {missing}{' in ' + context if context else ''}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_cluster_list(c: DatabricksClient) -> None:
    result = c.cluster_list()
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 cluster"
    assert_keys(result, ["cluster_id", "name", "state"])
    passed("cluster-list", f"{len(result)} cluster(s) found")


def test_cluster_get(c: DatabricksClient) -> None:
    if not CLUSTER_ID:
        skipped("cluster-get", "DATABRICKS_DEFAULT_CLUSTER_ID not set")
        return
    result = c.cluster_get(CLUSTER_ID)
    assert isinstance(result, dict), "Expected dict"
    assert_keys(result, ["cluster_id", "state"])
    state = result.get("state", "?")
    passed("cluster-get", f"state={state}")


SPARK_CONNECT_PHRASES = ("SparkConnect", "SparkConnectSession")


def _run_sql(c: DatabricksClient, sql: str, label: str, **kwargs):
    """Run sql_run, auto-skipping on known workspace restriction errors."""
    try:
        with _trap_exit():
            return c.sql_run(sql, **kwargs)
    except RuntimeError as exc:
        msg = str(exc)
        if _is_cmd_exec_scope_error(msg):
            skipped(label, "command-execution scope not granted on this workspace token")
        elif any(p in msg for p in SPARK_CONNECT_PHRASES):
            skipped(label, "cluster uses Spark Connect (DBR 13+); Command Execution API not supported")
        elif "Single-user check failed" in msg:
            skipped(
                label,
                "cluster is single-user for another user; set DATABRICKS_DEFAULT_WAREHOUSE_ID or use your cluster",
            )
        elif "timed out" in msg.lower():
            skipped(
                label,
                "execution timed out (warehouse recommended or start cluster); "
                "set DATABRICKS_TEST_SKIP_SQL=1 to skip SQL tests",
            )
        else:
            failed(label, msg)
        return None


def test_sql_select_1(c: DatabricksClient) -> None:
    if SKIP_SQL_TESTS:
        skipped("sql-run: SELECT 1", "DATABRICKS_TEST_SKIP_SQL is set")
        return
    if not CLUSTER_ID and not WAREHOUSE_ID:
        skipped("sql-run: SELECT 1", "no cluster or warehouse ID available")
        return
    sql_kw: dict = {"warehouse_id": WAREHOUSE_ID, "max_rows": 1}
    if WAREHOUSE_ID:
        sql_kw["cluster_id"] = ""
    result = _run_sql(c, "SELECT 1 AS n", "sql-run: SELECT 1", **sql_kw)
    if result is None:
        return
    assert result.get("rows"), "Expected non-empty rows"
    value = result["rows"][0].get("n")
    assert value in ("1", 1), f"Expected '1', got {value!r}"
    passed("sql-run: SELECT 1", f"rows=[{result['rows'][0]}]")


def test_sql_real_table(c: DatabricksClient) -> None:
    if SKIP_SQL_TESTS:
        skipped("sql-run: real table", "DATABRICKS_TEST_SKIP_SQL is set")
        return
    if not CLUSTER_ID and not WAREHOUSE_ID:
        skipped("sql-run: real table", "no cluster or warehouse ID available")
        return
    sql_kw: dict = {"warehouse_id": WAREHOUSE_ID, "max_rows": 5}
    if WAREHOUSE_ID:
        sql_kw["cluster_id"] = ""
    result = _run_sql(
        c,
        f"SELECT * FROM {TEST_TABLE} LIMIT 5",
        "sql-run: real table",
        **sql_kw,
    )
    if result is None:
        return
    assert isinstance(result.get("rows"), list), "Expected rows list"
    assert result.get("schema"), "Expected non-empty schema"
    n_rows = result["row_count"]
    n_cols = len(result["schema"])
    passed("sql-run: real table", f"{n_rows} rows, {n_cols} columns")


def test_uc_catalogs(c: DatabricksClient) -> None:
    result = c.uc_catalogs()
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 catalog"
    names = [item["name"] for item in result]
    assert TEST_CATALOG in names, f"Expected to find catalog '{TEST_CATALOG}', got {names}"
    passed("uc-catalogs", f"{len(result)} catalogs found")


def test_uc_schemas(c: DatabricksClient) -> None:
    result = c.uc_schemas(TEST_CATALOG)
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 schema"
    names = [item["name"] for item in result]
    assert TEST_SCHEMA in names, f"Expected schema '{TEST_SCHEMA}', got {names}"
    passed("uc-schemas", f"{len(result)} schemas in {TEST_CATALOG}")


def test_uc_tables(c: DatabricksClient) -> None:
    result = c.uc_tables(TEST_CATALOG, TEST_SCHEMA)
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 table"
    names = [item["name"] for item in result]
    assert TEST_TABLE_SHORT in names, f"Expected '{TEST_TABLE_SHORT}' in tables, got {names}"
    passed("uc-tables", f"{len(result)} tables in {TEST_CATALOG}.{TEST_SCHEMA}")


def test_uc_get_table(c: DatabricksClient) -> None:
    result = c.uc_get_table(TEST_TABLE)
    assert isinstance(result, dict), "Expected dict"
    assert result.get("full_name") == TEST_TABLE, f"full_name mismatch: {result.get('full_name')}"
    n_cols = len(result.get("columns") or [])
    assert n_cols > 0, "Expected at least 1 column"
    passed("uc-get-table", f"{TEST_TABLE}: {n_cols} columns")


def test_volume_list(c: DatabricksClient) -> None:
    if not TEST_VOLUME:
        skipped("volume-list", "DATABRICKS_TEST_VOLUME not set")
        return
    if not _vol_parsed:
        skipped("volume-list", "DATABRICKS_TEST_VOLUME must be catalog.schema.volume_name")
        return
    result = c.volume_list(TEST_VOLUME_CATALOG, TEST_VOLUME_SCHEMA)
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 volume"
    names = [item["name"] for item in result]
    assert TEST_VOLUME_FOR_LIST in names, f"Expected '{TEST_VOLUME_FOR_LIST}' in {names}"
    passed(
        "volume-list",
        f"{len(result)} volume(s) in {TEST_VOLUME_CATALOG}.{TEST_VOLUME_SCHEMA}",
    )


def test_volume_get(c: DatabricksClient) -> None:
    if not TEST_VOLUME:
        skipped("volume-get", "DATABRICKS_TEST_VOLUME not set")
        return
    if not _vol_parsed:
        skipped("volume-get", "DATABRICKS_TEST_VOLUME must be catalog.schema.volume_name")
        return
    result = c.volume_get(TEST_VOLUME)
    assert isinstance(result, dict), "Expected dict"
    assert result.get("full_name") == TEST_VOLUME, f"full_name mismatch: {result.get('full_name')}"
    passed("volume-get", f"{TEST_VOLUME}: type={result.get('type')}")


def test_job_list(c: DatabricksClient) -> None:
    result = c.job_list()
    assert isinstance(result, list) and len(result) >= 1, "Expected at least 1 job"
    names = [j["name"] for j in result]
    passed("job-list", f"{len(result)} job(s): {names}")


def test_job_run(c: DatabricksClient) -> None:
    global _job_run_id
    if TEST_JOB_ID is None:
        skipped("job-run", "DATABRICKS_TEST_JOB_ID / TEST_JOB_ID not set")
        return
    try:
        with _trap_exit():
            result = c.job_run(TEST_JOB_ID, params=None, wait=JOB_WAIT_FOR_COMPLETION)
    except RuntimeError as exc:
        msg = str(exc)
        if "does not have Manage Run" in msg or "Owner or Admin permissions on job" in msg:
            skipped("job-run", "token lacks permission on this job id")
        elif "does not support jobs workload" in msg:
            skipped("job-run", "configured compute cannot run this job type")
        else:
            failed("job-run", msg)
        return
    assert isinstance(result, dict), "Expected dict"
    assert_keys(result, ["run_id", "state"])
    _job_run_id = result["run_id"]
    mode = "waited for completion" if JOB_WAIT_FOR_COMPLETION else "triggered only"
    passed(
        "job-run",
        f"run_id={_job_run_id}, state={result.get('state')}, "
        f"result={result.get('result_state')} ({mode})",
    )


def test_job_run_status(c: DatabricksClient) -> None:
    if not _job_run_id:
        skipped("job-run-status", "job-run did not produce a run_id")
        return
    result = c.job_run_status(_job_run_id)
    assert isinstance(result, dict), "Expected dict"
    assert_keys(result, ["run_id", "state", "tasks"])
    tasks = result.get("tasks", [])
    task_summary = ", ".join(f"{t['task_key']}={t.get('result_state')}" for t in tasks)
    passed("job-run-status", f"state={result.get('state')}, tasks=[{task_summary}]")


def test_dbfs_ls(c: DatabricksClient) -> None:
    try:
        with _trap_exit():
            result = c.dbfs_ls(DBFS_BASE)
        assert isinstance(result, list), "Expected list"
        passed("dbfs-ls", f"{len(result)} entries in {DBFS_BASE}")
    except RuntimeError as exc:
        if any(p in str(exc) for p in DBFS_POLICY_PHRASES):
            skipped("dbfs-ls", f"DBFS access denied by workspace policy ({DBFS_BASE})")
        else:
            failed("dbfs-ls", str(exc))
    except Exception as exc:
        if _is_dbfs_policy_error(exc):
            skipped("dbfs-ls", f"DBFS access denied by workspace policy ({DBFS_BASE})")
        else:
            raise


def test_dbfs_roundtrip(c: DatabricksClient) -> None:
    content = b"databricks_tools connection test\n"
    remote = f"{DBFS_BASE.rstrip('/')}/test_databricks_connection.txt"
    local_out = os.path.join(tempfile.gettempdir(), "test_databricks_connection_dl.txt")
    local_in = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tf:
            tf.write(content)
            local_in = tf.name

        with _trap_exit():
            c.dbfs_put(local_in, remote, overwrite=True)
            c.dbfs_get(remote, local_out)
            c.dbfs_rm(remote)

        with open(local_out, "rb") as f:
            downloaded = f.read()

        assert downloaded == content, f"Content mismatch: {downloaded!r} != {content!r}"
        passed("dbfs-put/get/rm", f"round-trip ok ({len(content)} bytes -> {remote})")

    except RuntimeError as exc:
        if any(p in str(exc) for p in DBFS_POLICY_PHRASES):
            skipped("dbfs-put/get/rm", "DBFS access denied by workspace policy")
        else:
            failed("dbfs-put/get/rm", str(exc))
    except Exception as exc:
        if _is_dbfs_policy_error(exc):
            skipped("dbfs-put/get/rm", "DBFS access denied by workspace policy")
        else:
            raise
    finally:
        for path in [local_in, local_out]:
            if path and os.path.exists(path):
                os.remove(path)


def test_notebook_run(c: DatabricksClient) -> None:
    if not TEST_NOTEBOOK:
        skipped(
            "notebook-run",
            "DATABRICKS_TEST_NOTEBOOK_PATH / TEST_NOTEBOOK_PATH not set",
        )
        return
    if not CLUSTER_ID:
        skipped("notebook-run", "DATABRICKS_DEFAULT_CLUSTER_ID not set")
        return
    try:
        with _trap_exit():
            result = c.notebook_run(TEST_NOTEBOOK, CLUSTER_ID, params=None, wait=True, timeout=180)
    except RuntimeError as exc:
        msg = str(exc)
        if "Single-user check failed" in msg:
            skipped("notebook-run", "cluster is single-user for another user")
        elif "does not support jobs workload" in msg:
            skipped("notebook-run", "compute does not support notebook jobs workload")
        else:
            failed("notebook-run", msg)
        return
    assert isinstance(result, dict), "Expected dict"
    assert_keys(result, ["run_id", "state"])
    passed("notebook-run", f"run_id={result['run_id']}, state={result.get('state')}, result={result.get('result_state')}")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    ("cluster-list",       test_cluster_list),
    ("cluster-get",        test_cluster_get),
    ("sql-run: SELECT 1",  test_sql_select_1),
    ("sql-run: real table", test_sql_real_table),
    ("uc-catalogs",        test_uc_catalogs),
    ("uc-schemas",         test_uc_schemas),
    ("uc-tables",          test_uc_tables),
    ("uc-get-table",       test_uc_get_table),
    ("volume-list",        test_volume_list),
    ("volume-get",         test_volume_get),
    ("job-list",           test_job_list),
    ("job-run",            test_job_run),
    ("job-run-status",     test_job_run_status),
    ("dbfs-ls",            test_dbfs_ls),
    ("dbfs-put/get/rm",    test_dbfs_roundtrip),
    ("notebook-run",       test_notebook_run),
]

STATIC_SKIPS = [
    ("cluster-stop", "skipped to keep cluster warm during tests"),
]


def _heartbeat_while_running(label: str, stop: threading.Event) -> None:
    """Imprime a cada 60s enquanto o teste não terminou."""
    minutes = 1
    while not stop.wait(timeout=60.0):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{ts}] STILL_RUNNING  {label!r} — teste continua em execução (~{minutes} min)",
            flush=True,
        )
        minutes += 1


def _run_single_test(label: str, fn, client: DatabricksClient) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] TRIGGERED  {label!r}", flush=True)
    stop = threading.Event()
    hb = threading.Thread(
        target=_heartbeat_while_running,
        args=(label, stop),
        daemon=True,
    )
    hb.start()
    try:
        fn(client)
    finally:
        stop.set()


def _print_last_results(since: int) -> None:
    for status, label, detail in _results[since:]:
        icon = {"PASS": " PASS", "FAIL": " FAIL", "SKIP": " SKIP"}[status]
        print(f"{icon}  {label:<26}  {detail}", flush=True)


def main() -> None:
    print("Running Databricks connection tests...")
    print("Resolved targets:")
    print(f"  catalog/schema/table  {TEST_CATALOG} / {TEST_SCHEMA} / {TEST_TABLE}")
    print(f"  cluster_id            {CLUSTER_ID or '(unset)'}")
    print(f"  warehouse_id          {WAREHOUSE_ID or '(unset)'}")
    print(f"  test_volume           {TEST_VOLUME or '(unset — volume tests skipped)'}")
    print(f"  test_job_id           {TEST_JOB_ID if TEST_JOB_ID is not None else '(unset)'}")
    print(f"  job_wait_completion   {JOB_WAIT_FOR_COMPLETION}")
    print(f"  skip_sql_tests        {SKIP_SQL_TESTS}")
    print(f"  test_notebook         {TEST_NOTEBOOK or '(unset)'}")
    print("-" * 60)

    host, token, default_catalog, default_schema, default_cluster_id, default_dbfs_base = _load_config()
    client = DatabricksClient(
        host, token, default_catalog, default_schema, default_cluster_id, default_dbfs_base
    )

    for label, fn in TESTS:
        n_before = len(_results)
        try:
            _run_single_test(label, fn, client)
        except AssertionError as exc:
            failed(label, str(exc))
        except SystemExit as exc:
            failed(label, f"tool exited with code {exc.code} (check stderr above)")
        except Exception as exc:
            failed(label, f"{type(exc).__name__}: {exc}")
            if os.environ.get("DATABRICKS_TEST_VERBOSE"):
                traceback.print_exc()
        _print_last_results(n_before)

    n_before = len(_results)
    for label, reason in STATIC_SKIPS:
        skipped(label, reason)
    _print_last_results(n_before)

    n_pass = sum(1 for s, _, _ in _results if s == "PASS")
    n_fail = sum(1 for s, _, _ in _results if s == "FAIL")
    n_skip = sum(1 for s, _, _ in _results if s == "SKIP")

    print()
    print("-" * 60)
    print(f"{n_pass} passed  {n_fail} failed  {n_skip} skipped")

    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()

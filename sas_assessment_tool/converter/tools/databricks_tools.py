"""
Databricks interaction tool for the SAS migration pipeline.

Usage:
    python tools/databricks_tools.py <subcommand> [options]

Authentication:
    Generate a Personal Access Token at:
    Databricks workspace → User Settings → Developer → Access Tokens → Generate New Token

Required env vars:
    DATABRICKS_HOST    Workspace URL (e.g. https://adb-1234567890.azuredatabricks.net)
    DATABRICKS_TOKEN   Personal Access Token

Optional env vars:
    DATABRICKS_DEFAULT_CATALOG    Default Unity Catalog catalog (used when --catalog is omitted)
    DATABRICKS_DEFAULT_SCHEMA     Default schema (used when --schema is omitted)
    DATABRICKS_DEFAULT_CLUSTER_ID Default cluster ID (used when --cluster-id is omitted)

Databricks concepts:
    Workspace      Top-level Databricks environment. All resources live here.
    Cluster        Managed Spark compute. Must be RUNNING to execute notebooks/commands.
    SQL Warehouse  Serverless SQL compute. No cluster warm-up needed. Use for sql-run.
    DBFS           Databricks File System. Shared distributed storage inside the workspace.
    Job            Orchestrated pipeline with tasks (notebooks, SQL, Python, etc.).
    Run            A single execution of a Job or one-time notebook submission.
    Unity Catalog  Centralized governance layer for tables, schemas, and volumes.
    Volume         A Unity Catalog object for non-tabular file storage.

Subcommands:
    dbfs-ls         List files/directories in a DBFS path
    dbfs-put        Upload a local file to DBFS
    dbfs-get        Download a DBFS file to a local path
    dbfs-rm         Delete a file or directory from DBFS

    cluster-list    List clusters with their states
    cluster-get     Get full details of a specific cluster
    cluster-start   Start a terminated cluster
    cluster-stop    Terminate a running cluster (config is preserved)

    sql-run         Execute Spark SQL (cluster if DATABRICKS_DEFAULT_CLUSTER_ID set, else warehouse;
                    pass empty --cluster-id to force warehouse only)

    notebook-run    Submit a one-time notebook run on a cluster

    job-list        List all jobs in the workspace
    job-run         Trigger a job run
    job-run-status  Get the status and per-task breakdown of a run
    job-repair      Re-run specific failed or skipped tasks in an existing run
    job-task-output Get logs and error output for a specific task in a run

    uc-catalogs     List Unity Catalog catalogs
    uc-schemas      List schemas in a catalog
    uc-tables       List tables in a schema
    uc-get-table    Get full metadata for a specific table

    volume-list     List volumes in a schema
    volume-get      Get details of a specific volume
"""

import argparse
import base64
import datetime
import enum
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore", category=Warning, module="requests")


# ── Config & bootstrap ────────────────────────────────────────────────────────

def _load_config() -> tuple[str, str, str | None, str | None, str | None, str | None]:
    missing = []
    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")
    if not host:
        missing.append("DATABRICKS_HOST")
    if not token:
        missing.append("DATABRICKS_TOKEN")
    if missing:
        print(
            f"ERROR: Missing required environment variable(s): {', '.join(missing)}\n"
            "Set them before running this tool:\n"
            "  DATABRICKS_HOST    Workspace URL (e.g. https://adb-xxx.azuredatabricks.net)\n"
            "  DATABRICKS_TOKEN   Personal Access Token\n\n"
            "Optional:\n"
            "  DATABRICKS_DEFAULT_CATALOG    Default Unity Catalog catalog\n"
            "  DATABRICKS_DEFAULT_SCHEMA     Default schema\n"
            "  DATABRICKS_DEFAULT_CLUSTER_ID Default cluster ID\n"
            "  DATABRICKS_DBFS_BASE          Base path for relative DBFS paths (e.g. /FileStore)",
            file=sys.stderr,
        )
        sys.exit(1)
    return (
        host,
        token,
        os.environ.get("DATABRICKS_DEFAULT_CATALOG"),
        os.environ.get("DATABRICKS_DEFAULT_SCHEMA"),
        os.environ.get("DATABRICKS_DEFAULT_CLUSTER_ID"),
        os.environ.get("DATABRICKS_DBFS_BASE"),
    )


def _require_sdk():
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.errors import DatabricksError
        return WorkspaceClient, DatabricksError
    except ImportError:
        print(
            "ERROR: databricks-sdk is not installed.\n"
            "Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Serialization helpers ─────────────────────────────────────────────────────

def _normalize(v):
    """Convert SDK enums, datetimes, and other non-JSON types to safe values."""
    if v is None:
        return None
    if isinstance(v, enum.Enum):
        return v.value if isinstance(v.value, (str, int, float)) else str(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def _print(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _read_sql(args) -> str:
    if args.sql:
        return args.sql
    try:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        print(f"ERROR: Cannot read SQL file: {exc}", file=sys.stderr)
        sys.exit(1)


# ── Client ────────────────────────────────────────────────────────────────────

class _ClusterSqlError(RuntimeError):
    """Raised when cluster-based SQL fails in a way that allows warehouse fallback."""


class DatabricksClient:
    def __init__(
        self,
        host: str,
        token: str,
        default_catalog: str | None,
        default_schema: str | None,
        default_cluster_id: str | None,
        default_dbfs_base: str | None,
    ):
        WorkspaceClient, self._DatabricksError = _require_sdk()
        self._w = WorkspaceClient(host=host, token=token)
        self._default_catalog = default_catalog
        self._default_schema = default_schema
        self._default_cluster_id = default_cluster_id
        self._default_dbfs_base = default_dbfs_base

    def _call(self, fn, *args, **kwargs):
        """Invoke an SDK method and return its result, exiting on any error."""
        try:
            return fn(*args, **kwargs)
        except self._DatabricksError as exc:
            print(f"ERROR: Databricks API error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    def _list(self, fn, *args, **kwargs) -> list:
        """Invoke a paginated SDK method and eagerly materialize the iterator."""
        try:
            return list(fn(*args, **kwargs))
        except self._DatabricksError as exc:
            print(f"ERROR: Databricks API error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    def _resolve_catalog(self, catalog: str | None) -> str:
        c = catalog or self._default_catalog
        if not c:
            print(
                "ERROR: No catalog specified. Pass --catalog or set DATABRICKS_DEFAULT_CATALOG.",
                file=sys.stderr,
            )
            sys.exit(1)
        return c

    def _resolve_schema(self, schema: str | None) -> str:
        s = schema or self._default_schema
        if not s:
            print(
                "ERROR: No schema specified. Pass --schema or set DATABRICKS_DEFAULT_SCHEMA.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Accept fully-qualified "catalog.schema" — strip the catalog prefix
        return s.split(".")[-1] if "." in s else s

    def _resolve_cluster_id(self, cluster_id: str | None) -> str:
        c = cluster_id or self._default_cluster_id
        if not c:
            print(
                "ERROR: No cluster ID specified. Pass --cluster-id or set DATABRICKS_DEFAULT_CLUSTER_ID.",
                file=sys.stderr,
            )
            sys.exit(1)
        return c

    def _wait_for_run(self, run_id: int, timeout: int = 3600) -> object:
        """Poll until the run reaches a terminal life-cycle state."""
        try:
            from databricks.sdk.service.jobs import RunLifeCycleState
            terminal = {
                RunLifeCycleState.TERMINATED,
                RunLifeCycleState.SKIPPED,
                RunLifeCycleState.INTERNAL_ERROR,
            }
        except ImportError:
            terminal = set()

        deadline = time.time() + timeout
        run = None
        while time.time() < deadline:
            run = self._call(self._w.jobs.get_run, run_id=run_id)
            lc = run.state.life_cycle_state if (run and run.state) else None
            if terminal and lc in terminal:
                return run
            if not terminal and lc is not None and str(lc) in (
                "TERMINATED", "SKIPPED", "INTERNAL_ERROR"
            ):
                return run
            time.sleep(5)
        return run

    # ── DBFS ──────────────────────────────────────────────────────────────────
    # Uses raw REST API calls (w.api_client.do) instead of w.dbfs SDK wrappers
    # to avoid Windows path mangling in SDK >= 0.40.

    def _resolve_dbfs_path(self, path: str) -> str:
        """Return an absolute DBFS path. Relative paths are joined with DATABRICKS_DBFS_BASE."""
        if path.startswith("/"):
            return path
        base = self._default_dbfs_base
        if not base:
            print(
                "ERROR: Relative DBFS path given but DATABRICKS_DBFS_BASE is not set.\n"
                "Either use an absolute path (e.g. /FileStore/myfile.txt) or set DATABRICKS_DBFS_BASE.",
                file=sys.stderr,
            )
            sys.exit(1)
        return base.rstrip("/") + "/" + path

    def _dbfs_do(self, method: str, endpoint: str, **kwargs):
        try:
            return self._w.api_client.do(method, endpoint, **kwargs)
        except self._DatabricksError as exc:
            print(f"ERROR: Databricks API error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    def dbfs_ls(self, path: str) -> list:
        resp = self._dbfs_do("GET", "/api/2.0/dbfs/list", query={"path": self._resolve_dbfs_path(path)})
        files = resp.get("files", []) if resp else []
        return [
            {
                "path": f["path"],
                "is_dir": f["is_dir"],
                "size_bytes": f.get("file_size", 0),
                "modified_ms": f.get("modification_time"),
            }
            for f in files
        ]

    def dbfs_put(self, local_path: str, remote_path: str, overwrite: bool = False) -> dict:
        try:
            with open(local_path, "rb") as f:
                data = f.read()
        except OSError as exc:
            print(f"ERROR: Cannot read local file: {exc}", file=sys.stderr)
            sys.exit(1)

        remote_path = self._resolve_dbfs_path(remote_path)
        handle_resp = self._dbfs_do(
            "POST", "/api/2.0/dbfs/create",
            body={"path": remote_path, "overwrite": overwrite},
        )
        handle = handle_resp["handle"]
        chunk_size = 1024 * 1024
        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            self._dbfs_do(
                "POST", "/api/2.0/dbfs/add-block",
                body={"handle": handle, "data": base64.b64encode(chunk).decode()},
            )
        self._dbfs_do("POST", "/api/2.0/dbfs/close", body={"handle": handle})
        return {"remote_path": remote_path, "size_bytes": len(data)}

    def dbfs_get(self, remote_path: str, local_path: str) -> dict:
        remote_path = self._resolve_dbfs_path(remote_path)
        status = self._dbfs_do("GET", "/api/2.0/dbfs/get-status", query={"path": remote_path})
        file_size = status.get("file_size", 0) if status else 0

        data = b""
        chunk_size = 1024 * 1024
        offset = 0
        while offset < file_size:
            chunk_resp = self._dbfs_do(
                "GET", "/api/2.0/dbfs/read",
                query={"path": remote_path, "offset": offset, "length": min(chunk_size, file_size - offset)},
            )
            if not chunk_resp or not chunk_resp.get("data"):
                break
            data += base64.b64decode(chunk_resp["data"])
            bytes_read = chunk_resp.get("bytes_read", 0)
            offset += bytes_read
            if not bytes_read:
                break

        try:
            with open(local_path, "wb") as f:
                f.write(data)
        except OSError as exc:
            print(f"ERROR: Cannot write local file: {exc}", file=sys.stderr)
            sys.exit(1)
        return {"local_path": local_path, "size_bytes": len(data)}

    def dbfs_rm(self, path: str, recursive: bool = False) -> dict:
        path = self._resolve_dbfs_path(path)
        self._dbfs_do("POST", "/api/2.0/dbfs/delete", body={"path": path, "recursive": recursive})
        return {"deleted_path": path}

    # ── Clusters ──────────────────────────────────────────────────────────────

    def cluster_list(self, state_filter: str | None = None) -> list:
        clusters = self._list(self._w.clusters.list)
        result = []
        for c in clusters:
            state = _normalize(c.state)
            if state_filter and str(state).upper() != state_filter.upper():
                continue
            result.append(
                {
                    "cluster_id": c.cluster_id,
                    "name": c.cluster_name,
                    "state": state,
                    "runtime": c.spark_version,
                    "driver_type": c.driver_node_type_id,
                    "worker_type": c.node_type_id,
                    "num_workers": c.num_workers,
                    "creator": c.creator_user_name,
                }
            )
        return result

    def cluster_get(self, cluster_id: str | None) -> dict:
        c = self._call(self._w.clusters.get, cluster_id=self._resolve_cluster_id(cluster_id))
        return {
            "cluster_id": c.cluster_id,
            "name": c.cluster_name,
            "state": _normalize(c.state),
            "state_message": c.state_message,
            "runtime": c.spark_version,
            "driver_type": c.driver_node_type_id,
            "worker_type": c.node_type_id,
            "num_workers": c.num_workers,
            "autoscale": (
                {"min_workers": c.autoscale.min_workers, "max_workers": c.autoscale.max_workers}
                if c.autoscale
                else None
            ),
            "creator": c.creator_user_name,
            "start_time_ms": c.start_time,
            "terminated_time_ms": c.terminated_time,
        }

    def cluster_start(self, cluster_id: str | None, wait: bool = False) -> dict:
        cid = self._resolve_cluster_id(cluster_id)
        if wait:
            result = self._call(self._w.clusters.start_and_wait, cluster_id=cid)
            state = _normalize(result.state) if result else "RUNNING"
            return {"cluster_id": cid, "state": state}
        self._call(self._w.clusters.start, cluster_id=cid)
        return {"cluster_id": cid, "state": "STARTING"}

    def cluster_stop(self, cluster_id: str | None, wait: bool = False) -> dict:
        cid = self._resolve_cluster_id(cluster_id)
        if wait:
            self._call(self._w.clusters.terminate_and_wait, cluster_id=cid)
            return {"cluster_id": cid, "state": "TERMINATED"}
        self._call(self._w.clusters.terminate, cluster_id=cid)
        return {"cluster_id": cid, "state": "TERMINATING"}

    # ── SQL Execution ─────────────────────────────────────────────────────────

    def sql_run(
        self,
        sql: str,
        warehouse_id: str | None = None,
        max_rows: int = 100,
        cluster_id: str | None = None,
    ) -> dict:
        """Dispatch to cluster or warehouse execution.

        Priority when ``cluster_id`` is omitted (``None``): use
        ``DATABRICKS_DEFAULT_CLUSTER_ID``, then fall back to ``warehouse_id`` on
        known cluster API incompatibility.

        If ``cluster_id`` is passed as empty string ``""``, no cluster is used (the
        default cluster id is ignored); execution requires ``warehouse_id`` or exits.

        Explicit non-empty ``cluster_id`` always wins over the default cluster id.
        """
        if cluster_id is None:
            effective_cluster_id = self._default_cluster_id
        else:
            effective_cluster_id = cluster_id.strip() or None
        if effective_cluster_id:
            try:
                return self._sql_run_cluster(sql, effective_cluster_id, max_rows)
            except _ClusterSqlError as exc:
                if warehouse_id:
                    print(
                        f"WARNING: Cluster SQL failed ({exc}); falling back to SQL Warehouse.",
                        file=sys.stderr,
                    )
                    return self._sql_run_warehouse(sql, warehouse_id, max_rows)
                print(f"ERROR: SQL execution on cluster failed: {exc}", file=sys.stderr)
                sys.exit(1)

        if warehouse_id:
            return self._sql_run_warehouse(sql, warehouse_id, max_rows)

        print(
            "ERROR: No SQL compute specified.\n"
            "  Set DATABRICKS_DEFAULT_CLUSTER_ID or pass --cluster-id to use an all-purpose cluster.\n"
            "  Or pass --warehouse-id to use a SQL Warehouse.",
            file=sys.stderr,
        )
        sys.exit(1)

    def _sql_run_cluster(self, sql: str, cluster_id: str, max_rows: int = 100) -> dict:
        """Execute SQL on an all-purpose cluster via the Command Execution API."""
        try:
            from databricks.sdk.service.compute import Language, CommandStatus, ResultType
        except ImportError:
            raise _ClusterSqlError("databricks-sdk version does not support Command Execution API")

        ctx = self._call(
            self._w.command_execution.create_and_wait,
            cluster_id=cluster_id,
            language=Language.SQL,
        )
        context_id = ctx.id

        try:
            result = self._call(
                self._w.command_execution.execute_and_wait,
                cluster_id=cluster_id,
                context_id=context_id,
                language=Language.SQL,
                command=sql,
            )
        finally:
            try:
                self._w.command_execution.destroy(cluster_id=cluster_id, context_id=context_id)
            except Exception:
                pass

        if result.status != CommandStatus.FINISHED:
            cause = (result.results.cause if result.results else None) or str(result.status)
            raise _ClusterSqlError(cause)

        res = result.results
        if res and res.result_type == ResultType.ERROR:
            cause = getattr(res, "cause", None) or getattr(res, "summary", None) or "unknown error"
            raise _ClusterSqlError(cause)
        if not res or res.result_type != ResultType.TABLE:
            summary = getattr(res, "summary", None) or ""
            return {"rows": [], "row_count": 0, "total_row_count": 0, "truncated": False, "schema": [], "summary": summary}

        raw_schema = res.schema or []
        schema = [
            {"name": col.get("name"), "type": col.get("type"), "nullable": True}
            for col in raw_schema
        ]
        col_names = [c["name"] for c in schema]

        raw_data = res.data or []
        rows = [
            dict(zip(col_names, row)) if col_names else list(row)
            for row in raw_data[:max_rows]
        ]
        total = len(raw_data)
        return {
            "rows": rows,
            "row_count": len(rows),
            "total_row_count": total,
            "truncated": total > max_rows,
            "schema": schema,
        }

    def _sql_run_warehouse(self, sql: str, warehouse_id: str, max_rows: int = 100) -> dict:
        """Execute SQL via the Statement Execution API (SQL Warehouse — serverless)."""
        try:
            from databricks.sdk.service.sql import StatementState, Disposition, Format
        except ImportError:
            print("ERROR: databricks-sdk version does not support Statement Execution API.", file=sys.stderr)
            sys.exit(1)

        resp = self._call(
            self._w.statement_execution.execute_statement,
            statement=sql,
            warehouse_id=warehouse_id,
            wait_timeout="50s",
            disposition=Disposition.INLINE,
            format=Format.JSON_ARRAY,
        )

        stmt_id = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = self._call(self._w.statement_execution.get_statement, statement_id=stmt_id)

        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            state = _normalize(resp.status.state) if resp.status else "UNKNOWN"
            error_msg = (
                resp.status.error.message
                if (resp.status and resp.status.error)
                else "no error detail"
            )
            print(f"ERROR: SQL execution failed ({state}): {error_msg}", file=sys.stderr)
            sys.exit(1)

        schema = []
        if resp.manifest and resp.manifest.schema and resp.manifest.schema.columns:
            schema = [
                {
                    "name": col.name,
                    "type": _normalize(col.type_name),
                    "nullable": getattr(col, "nullable", True),
                }
                for col in resp.manifest.schema.columns
            ]

        col_names = [c["name"] for c in schema]
        rows = []
        if resp.result and resp.result.data_array:
            for raw_row in resp.result.data_array[:max_rows]:
                rows.append(dict(zip(col_names, raw_row)) if col_names else list(raw_row))

        total = (resp.manifest.total_row_count if resp.manifest else None) or len(rows)
        return {
            "rows": rows,
            "row_count": len(rows),
            "total_row_count": total,
            "truncated": len(rows) < total,
            "schema": schema,
        }

    # ── Notebooks ─────────────────────────────────────────────────────────────

    def notebook_run(
        self,
        notebook_path: str,
        cluster_id: str | None,
        params: dict | None,
        wait: bool,
        timeout: int,
    ) -> dict:
        try:
            from databricks.sdk.service.jobs import SubmitTask, NotebookTask
        except ImportError:
            print("ERROR: databricks-sdk version does not support job submission.", file=sys.stderr)
            sys.exit(1)

        # Compute priority: explicit arg > DATABRICKS_DEFAULT_CLUSTER_ID > serverless
        cid = cluster_id or self._default_cluster_id

        task = SubmitTask(
            task_key="notebook_task",
            notebook_task=NotebookTask(
                notebook_path=notebook_path,
                base_parameters=params or {},
            ),
        )
        if cid:
            task.existing_cluster_id = cid
        # else: no cluster spec → Databricks uses serverless compute

        submit_resp = self._call(
            self._w.jobs.submit,
            run_name=f"notebook_run_{notebook_path.rstrip('/').split('/')[-1]}",
            tasks=[task],
        )
        run_id = getattr(submit_resp, "run_id", None) or getattr(
            getattr(submit_resp, "response", None), "run_id", None
        )

        if not wait:
            return {"run_id": run_id, "state": "PENDING"}

        run = self._wait_for_run(run_id, timeout=timeout)

        # get_run_output requires a task-level run_id for multi-task runs
        task_run_id = run_id
        if run and run.tasks:
            task_run_id = run.tasks[0].run_id or run_id
        output = self._call(self._w.jobs.get_run_output, run_id=task_run_id)

        notebook_result = None
        if output and output.notebook_output:
            notebook_result = output.notebook_output.result

        return {
            "run_id": run_id,
            "state": _normalize(run.state.life_cycle_state) if (run and run.state) else None,
            "result_state": _normalize(run.state.result_state) if (run and run.state) else None,
            "run_page_url": getattr(run, "run_page_url", None),
            "notebook_output": notebook_result,
            "error": getattr(output, "error", None) if output else None,
            "error_trace": getattr(output, "error_trace", None) if output else None,
        }

    # ── Jobs ──────────────────────────────────────────────────────────────────

    def job_list(self) -> list:
        jobs = self._list(self._w.jobs.list)
        return [
            {
                "job_id": j.job_id,
                "name": j.settings.name if j.settings else None,
                "creator": j.creator_user_name,
                "created_at_ms": j.created_time,
            }
            for j in jobs
        ]

    @staticmethod
    def _task_summary(task) -> dict:
        return {
            "task_key": task.task_key,
            "run_id": task.run_id,
            "state": _normalize(task.state.life_cycle_state) if task.state else None,
            "result_state": _normalize(task.state.result_state) if task.state else None,
            "attempt_number": getattr(task, "attempt_number", None),
            "run_page_url": getattr(task, "run_page_url", None),
        }

    def job_run(self, job_id: int, params: dict | None, wait: bool, only: list[str] | None = None) -> dict:
        try:
            waiter = self._w.jobs.run_now(job_id=job_id, notebook_params=params, only=only or None)
        except self._DatabricksError as exc:
            print(f"ERROR: Databricks API error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        run_id = getattr(waiter, "run_id", None) or getattr(
            getattr(waiter, "response", None), "run_id", None
        )

        if not wait:
            return {"run_id": run_id, "state": "PENDING"}

        run = self._wait_for_run(run_id)
        tasks = [self._task_summary(t) for t in (run.tasks or [])]
        return {
            "run_id": run_id,
            "state": _normalize(run.state.life_cycle_state) if (run and run.state) else None,
            "result_state": _normalize(run.state.result_state) if (run and run.state) else None,
            "run_page_url": getattr(run, "run_page_url", None),
            "tasks": tasks,
        }

    def job_run_status(self, run_id: int) -> dict:
        run = self._call(self._w.jobs.get_run, run_id=run_id)

        duration_ms = None
        start = getattr(run, "start_time", None)
        end = getattr(run, "end_time", None)
        if start and end:
            duration_ms = end - start

        tasks = [self._task_summary(t) for t in (run.tasks or [])]
        return {
            "run_id": run_id,
            "state": _normalize(run.state.life_cycle_state) if (run and run.state) else None,
            "result_state": _normalize(run.state.result_state) if (run and run.state) else None,
            "state_message": run.state.state_message if (run and run.state) else None,
            "start_time_ms": start,
            "duration_ms": duration_ms,
            "run_page_url": getattr(run, "run_page_url", None),
            "tasks": tasks,
        }

    def job_task_output(self, run_id: int, task_key: str | None = None) -> dict:
        """Return logs and error for a specific task.

        If task_key is given, run_id is the parent run and the task is looked up
        by key. Otherwise run_id is treated directly as a task run_id.
        """
        if task_key:
            parent = self._call(self._w.jobs.get_run, run_id=run_id)
            task_run_id = None
            for t in (parent.tasks or []):
                if t.task_key == task_key:
                    task_run_id = t.run_id
                    break
            if task_run_id is None:
                available = [t.task_key for t in (parent.tasks or [])]
                print(
                    f"ERROR: Task key '{task_key}' not found in run {run_id}.\n"
                    f"Available task keys: {available}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            task_run_id = run_id

        task_run = self._call(self._w.jobs.get_run, run_id=task_run_id)
        output = self._call(self._w.jobs.get_run_output, run_id=task_run_id)

        notebook_output = None
        if output and output.notebook_output:
            notebook_output = output.notebook_output.result

        return {
            "task_run_id": task_run_id,
            "task_key": getattr(task_run, "task_key", None),
            "state": _normalize(task_run.state.life_cycle_state) if (task_run and task_run.state) else None,
            "result_state": _normalize(task_run.state.result_state) if (task_run and task_run.state) else None,
            "run_page_url": getattr(task_run, "run_page_url", None),
            "notebook_output": notebook_output,
            "error": getattr(output, "error", None) if output else None,
            "error_trace": getattr(output, "error_trace", None) if output else None,
            "logs": getattr(output, "logs", None) if output else None,
        }

    def job_repair(self, run_id: int, task_keys: list[str], wait: bool) -> dict:
        """Re-run specific failed or skipped tasks in an existing run.

        Only tasks that previously failed or were skipped can be repaired.
        """
        if not task_keys:
            print("ERROR: At least one --task-key is required for job-repair.", file=sys.stderr)
            sys.exit(1)

        if wait:
            run = self._call(
                self._w.jobs.repair_run_and_wait,
                run_id=run_id,
                rerun_tasks=task_keys,
            )
            tasks = [self._task_summary(t) for t in (run.tasks or [])]
            return {
                "run_id": run_id,
                "state": _normalize(run.state.life_cycle_state) if (run and run.state) else None,
                "result_state": _normalize(run.state.result_state) if (run and run.state) else None,
                "run_page_url": getattr(run, "run_page_url", None),
                "tasks": tasks,
            }

        resp = self._call(
            self._w.jobs.repair_run,
            run_id=run_id,
            rerun_tasks=task_keys,
        )
        return {
            "run_id": run_id,
            "repair_id": getattr(resp, "repair_id", None),
            "rerun_tasks": task_keys,
            "state": "REPAIRING",
        }

    # ── Unity Catalog ─────────────────────────────────────────────────────────

    def uc_catalogs(self) -> list:
        cats = self._list(self._w.catalogs.list)
        return [
            {
                "name": c.name,
                "type": _normalize(c.catalog_type),
                "owner": c.owner,
                "created_at": _normalize(c.created_at),
                "metastore_id": c.metastore_id,
                "comment": c.comment,
            }
            for c in cats
        ]

    def uc_schemas(self, catalog: str | None) -> list:
        cat = self._resolve_catalog(catalog)
        schemas = self._list(self._w.schemas.list, catalog_name=cat)
        return [
            {
                "name": s.name,
                "catalog": s.catalog_name,
                "owner": s.owner,
                "created_at": _normalize(s.created_at),
                "comment": s.comment,
            }
            for s in schemas
        ]

    def uc_tables(self, catalog: str | None, schema: str | None) -> list:
        cat = self._resolve_catalog(catalog)
        sch = self._resolve_schema(schema)
        tables = self._list(self._w.tables.list, catalog_name=cat, schema_name=sch)
        return [
            {
                "name": t.name,
                "full_name": t.full_name,
                "catalog": t.catalog_name,
                "schema": t.schema_name,
                "type": _normalize(t.table_type),
                "owner": t.owner,
            }
            for t in tables
        ]

    def uc_get_table(self, full_name: str) -> dict:
        t = self._call(self._w.tables.get, full_name=full_name)
        columns = []
        if t.columns:
            columns = [
                {
                    "name": col.name,
                    "type": _normalize(col.type_name),
                    "nullable": col.nullable,
                    "comment": col.comment,
                    "partition_index": col.partition_index,
                }
                for col in t.columns
            ]
        return {
            "full_name": t.full_name,
            "catalog": t.catalog_name,
            "schema": t.schema_name,
            "name": t.name,
            "type": _normalize(t.table_type),
            "owner": t.owner,
            "created_at": _normalize(t.created_at),
            "updated_at": _normalize(t.updated_at),
            "storage_location": t.storage_location,
            "data_source_format": _normalize(t.data_source_format),
            "comment": t.comment,
            "columns": columns,
        }

    # ── Volumes ───────────────────────────────────────────────────────────────

    def volume_list(self, catalog: str | None, schema: str | None) -> list:
        cat = self._resolve_catalog(catalog)
        sch = self._resolve_schema(schema)
        vols = self._list(self._w.volumes.list, catalog_name=cat, schema_name=sch)
        return [
            {
                "name": v.name,
                "full_name": v.full_name,
                "catalog": v.catalog_name,
                "schema": v.schema_name,
                "type": _normalize(v.volume_type),
                "storage_location": v.storage_location,
                "owner": v.owner,
            }
            for v in vols
        ]

    def volume_get(self, full_name: str) -> dict:
        v = self._call(self._w.volumes.read, name=full_name)
        return {
            "full_name": v.full_name,
            "catalog": v.catalog_name,
            "schema": v.schema_name,
            "name": v.name,
            "type": _normalize(v.volume_type),
            "storage_location": v.storage_location,
            "owner": v.owner,
            "created_at": _normalize(v.created_at),
            "updated_at": _normalize(v.updated_at),
            "comment": v.comment,
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="databricks_tools",
        description="Databricks interaction tool for the SAS migration pipeline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── dbfs-ls
    p = sub.add_parser("dbfs-ls", help="List files/directories in a DBFS path")
    p.add_argument("--path", required=True, metavar="DBFS_PATH", help='DBFS path (e.g. /mnt/data)')

    # ── dbfs-put
    p = sub.add_parser("dbfs-put", help="Upload a local file to DBFS")
    p.add_argument("--local", required=True, metavar="LOCAL_PATH", help="Local file path to upload")
    p.add_argument("--remote", required=True, metavar="DBFS_PATH", help="Destination DBFS path")
    p.add_argument("--overwrite", action="store_true", help="Overwrite if the remote file already exists")

    # ── dbfs-get
    p = sub.add_parser("dbfs-get", help="Download a DBFS file to a local path")
    p.add_argument("--remote", required=True, metavar="DBFS_PATH", help="Source DBFS path")
    p.add_argument("--local", required=True, metavar="LOCAL_PATH", help="Local destination path")

    # ── dbfs-rm
    p = sub.add_parser("dbfs-rm", help="Delete a file or directory from DBFS")
    p.add_argument("--path", required=True, metavar="DBFS_PATH", help="DBFS path to delete")
    p.add_argument("--recursive", action="store_true", help="Delete directory and all its contents")

    # ── cluster-list
    p = sub.add_parser("cluster-list", help="List clusters with their states")
    p.add_argument(
        "--state",
        metavar="STATE",
        help="Filter by state: RUNNING, TERMINATED, PENDING, STARTING, TERMINATING, ERROR",
    )

    # ── cluster-get
    p = sub.add_parser("cluster-get", help="Get full details of a specific cluster")
    p.add_argument("--cluster-id", metavar="CLUSTER_ID", help="Cluster ID (or use DATABRICKS_DEFAULT_CLUSTER_ID)")

    # ── cluster-start
    p = sub.add_parser("cluster-start", help="Start a terminated cluster")
    p.add_argument("--cluster-id", metavar="CLUSTER_ID", help="Cluster ID (or use DATABRICKS_DEFAULT_CLUSTER_ID)")
    p.add_argument("--wait", action="store_true", help="Block until the cluster is RUNNING")

    # ── cluster-stop
    p = sub.add_parser("cluster-stop", help="Terminate a running cluster (config is preserved)")
    p.add_argument("--cluster-id", metavar="CLUSTER_ID", help="Cluster ID (or use DATABRICKS_DEFAULT_CLUSTER_ID)")
    p.add_argument("--wait", action="store_true", help="Block until the cluster is TERMINATED")

    # ── sql-run
    p = sub.add_parser(
        "sql-run",
        help="Execute Spark SQL (cluster by default if DATABRICKS_DEFAULT_CLUSTER_ID is set, else warehouse)",
    )
    p.add_argument(
        "--cluster-id",
        metavar="CLUSTER_ID",
        help="All-purpose cluster ID (default: DATABRICKS_DEFAULT_CLUSTER_ID; takes priority over --warehouse-id)",
    )
    p.add_argument(
        "--warehouse-id",
        metavar="WAREHOUSE_ID",
        help="SQL Warehouse ID (used only when no cluster ID is available)",
    )
    sql_group = p.add_mutually_exclusive_group(required=True)
    sql_group.add_argument("--sql", help="SQL statement to execute")
    sql_group.add_argument("--file", metavar="PATH", help="Path to a .sql file")
    p.add_argument(
        "--max-rows",
        type=int,
        default=100,
        metavar="N",
        help="Maximum rows to return (default: 100)",
    )

    # ── notebook-run
    p = sub.add_parser("notebook-run", help="Submit a one-time notebook run (cluster, or serverless if no cluster available)")
    p.add_argument("--path", required=True, metavar="NOTEBOOK_PATH", help="Workspace notebook path")
    p.add_argument("--cluster-id", metavar="CLUSTER_ID", help="Cluster ID (default: DATABRICKS_DEFAULT_CLUSTER_ID; omit for serverless)")
    p.add_argument(
        "--params",
        metavar="JSON",
        help='Notebook base parameters as a JSON object (e.g. \'{"key": "value"}\')',
    )
    p.add_argument("--wait", action="store_true", help="Block until the run completes")
    p.add_argument(
        "--timeout",
        type=int,
        default=600,
        metavar="SECONDS",
        help="Maximum wait time in seconds when --wait is set (default: 600)",
    )

    # ── job-list
    sub.add_parser("job-list", help="List all jobs in the workspace")

    # ── job-run
    p = sub.add_parser("job-run", help="Trigger a job run")
    p.add_argument("--job-id", required=True, type=int, metavar="JOB_ID")
    p.add_argument(
        "--params",
        metavar="JSON",
        help='Notebook parameters as a JSON object (e.g. \'{"key": "value"}\')',
    )
    p.add_argument("--wait", action="store_true", help="Block until the run reaches a terminal state")
    p.add_argument(
        "--task-keys",
        metavar="TASK_KEY[,TASK_KEY,...]",
        help="Comma-separated task keys to run (runs all tasks if omitted)",
    )

    # ── job-run-status
    p = sub.add_parser("job-run-status", help="Get the status and per-task breakdown of a run")
    p.add_argument("--run-id", required=True, type=int, metavar="RUN_ID")

    # ── job-repair
    p = sub.add_parser("job-repair", help="Re-run specific failed or skipped tasks in an existing run")
    p.add_argument("--run-id", required=True, type=int, metavar="RUN_ID",
                   help="Parent run ID to repair (from job-run or job-run-status)")
    p.add_argument("--task-keys", required=True, metavar="TASK_KEY[,TASK_KEY,...]",
                   help="Comma-separated task keys to re-run (must have previously failed or been skipped)")
    p.add_argument("--wait", action="store_true", help="Block until all repaired tasks reach a terminal state")

    # ── job-task-output
    p = sub.add_parser("job-task-output", help="Get logs and error output for a specific task in a run")
    p.add_argument("--run-id", required=True, type=int, metavar="RUN_ID",
                   help="Parent run ID (with --task-key) or task run ID (without --task-key)")
    p.add_argument("--task-key", metavar="TASK_KEY",
                   help="Task key to look up within the parent run (use job-run-status to list available keys)")

    # ── uc-catalogs
    sub.add_parser("uc-catalogs", help="List Unity Catalog catalogs")

    # ── uc-schemas
    p = sub.add_parser("uc-schemas", help="List schemas in a catalog")
    p.add_argument("--catalog", metavar="CATALOG", help="Catalog name (or use DATABRICKS_DEFAULT_CATALOG)")

    # ── uc-tables
    p = sub.add_parser("uc-tables", help="List tables in a schema")
    p.add_argument("--catalog", metavar="CATALOG", help="Catalog name (or use DATABRICKS_DEFAULT_CATALOG)")
    p.add_argument("--schema", metavar="SCHEMA", help="Schema name (or use DATABRICKS_DEFAULT_SCHEMA)")

    # ── uc-get-table
    p = sub.add_parser("uc-get-table", help="Get full metadata for a specific table")
    p.add_argument(
        "--table",
        required=True,
        metavar="FULL_NAME",
        help="Fully-qualified table name: catalog.schema.table",
    )

    # ── volume-list
    p = sub.add_parser("volume-list", help="List volumes in a schema")
    p.add_argument("--catalog", metavar="CATALOG", help="Catalog name (or use DATABRICKS_DEFAULT_CATALOG)")
    p.add_argument("--schema", metavar="SCHEMA", help="Schema name (or use DATABRICKS_DEFAULT_SCHEMA)")

    # ── volume-get
    p = sub.add_parser("volume-get", help="Get details of a specific volume")
    p.add_argument(
        "--volume",
        required=True,
        metavar="FULL_NAME",
        help="Fully-qualified volume name: catalog.schema.volume",
    )

    args = parser.parse_args()
    host, token, default_catalog, default_schema, default_cluster_id, default_dbfs_base = _load_config()
    client = DatabricksClient(host, token, default_catalog, default_schema, default_cluster_id, default_dbfs_base)

    if args.cmd == "dbfs-ls":
        _print(client.dbfs_ls(args.path))
    elif args.cmd == "dbfs-put":
        _print(client.dbfs_put(args.local, args.remote, args.overwrite))
    elif args.cmd == "dbfs-get":
        _print(client.dbfs_get(args.remote, args.local))
    elif args.cmd == "dbfs-rm":
        _print(client.dbfs_rm(args.path, args.recursive))
    elif args.cmd == "cluster-list":
        _print(client.cluster_list(getattr(args, "state", None)))
    elif args.cmd == "cluster-get":
        _print(client.cluster_get(args.cluster_id))
    elif args.cmd == "cluster-start":
        _print(client.cluster_start(args.cluster_id, args.wait))
    elif args.cmd == "cluster-stop":
        _print(client.cluster_stop(args.cluster_id, args.wait))
    elif args.cmd == "sql-run":
        _print(client.sql_run(
            _read_sql(args),
            warehouse_id=getattr(args, "warehouse_id", None),
            max_rows=args.max_rows,
            cluster_id=getattr(args, "cluster_id", None),
        ))
    elif args.cmd == "notebook-run":
        params = json.loads(args.params) if args.params else None
        _print(client.notebook_run(args.path, args.cluster_id, params, args.wait, args.timeout))
    elif args.cmd == "job-list":
        _print(client.job_list())
    elif args.cmd == "job-run":
        params = json.loads(args.params) if args.params else None
        only = [k.strip() for k in args.task_keys.split(",")] if args.task_keys else None
        _print(client.job_run(args.job_id, params, args.wait, only=only))
    elif args.cmd == "job-run-status":
        _print(client.job_run_status(args.run_id))
    elif args.cmd == "job-repair":
        task_keys = [k.strip() for k in args.task_keys.split(",")]
        _print(client.job_repair(args.run_id, task_keys, args.wait))
    elif args.cmd == "job-task-output":
        _print(client.job_task_output(args.run_id, getattr(args, "task_key", None)))
    elif args.cmd == "uc-catalogs":
        _print(client.uc_catalogs())
    elif args.cmd == "uc-schemas":
        _print(client.uc_schemas(getattr(args, "catalog", None)))
    elif args.cmd == "uc-tables":
        _print(client.uc_tables(getattr(args, "catalog", None), getattr(args, "schema", None)))
    elif args.cmd == "uc-get-table":
        _print(client.uc_get_table(args.table))
    elif args.cmd == "volume-list":
        _print(client.volume_list(getattr(args, "catalog", None), getattr(args, "schema", None)))
    elif args.cmd == "volume-get":
        _print(client.volume_get(args.volume))


if __name__ == "__main__":
    main()

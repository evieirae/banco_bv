
# Bigquery Tools — Build Record

## Original Request

```prompt
I need to create tools for this project so it can interact with bigquery. it should be able to send queries and fetch the results. since I always interact with bigquery via UI, I'm not familiarized with the parameters I can (or need) to provide to the bigquery API, so I would apreciate a proper documentation along with the tool.
```

---

Here is the implementation plan that was used:

# Plan: BigQuery Interaction Tools

## Context
The SAS migration tool converts `.egp` projects to dbt/BigQuery SQL. Once models are generated, there was no way to programmatically validate them against the actual data warehouse. `tools/bigquery_tools.py` fills that gap: it lets AI agents and developers run queries, validate SQL, and inspect tables/datasets — all from the command line, with JSON output suitable for downstream parsing.

Implementation mirrors `tools/github_tools.py` exactly: same argparse structure, same error-to-stderr discipline, same JSON stdout format, same `_load_config()` pattern.

---

## BigQuery Concepts (for new users)

| Concept | Description |
|---------|-------------|
| **Project** | Top-level GCP billing/resource container. Every query's cost lands here. Set via `GCP_PROJECT_ID`. |
| **Dataset** | Namespace for tables — analogous to a schema in Postgres. Set via `GCP_DATASET` or `--dataset`. |
| **Table** | Stores actual data. Fully-qualified name: `` `project.dataset.table` `` |
| **Job** | BigQuery is asynchronous: every query creates a Job. The SDK's `.result()` blocks until it finishes. |
| **Dry run** | A job with `dry_run=True` validates syntax and estimates bytes billed — it never reads or charges data. Use this before running expensive queries. |
| **Schema** | A table's column definitions: `name`, `type` (STRING/INTEGER/FLOAT/NUMERIC/DATE/TIMESTAMP/…), `mode` (NULLABLE/REQUIRED/REPEATED). |
| **Bytes billed** | BigQuery bills per bytes scanned, rounded up to 10 MB per query. Free tier: 1 TB/month. Dry run reveals the estimate before you commit. |
| **ADC** | Application Default Credentials — a GCP auth mechanism that reads credentials from the environment automatically. Preferred for local development. |

---

## Authentication

Two strategies, both handled transparently by the `google-cloud-bigquery` SDK:

### Option A — Application Default Credentials (recommended for local dev)

`gcloud` is a separate CLI tool (the **Google Cloud SDK**) — it is NOT installed via `pip`.
Install it first, then run the login command:

```bash
# Install the Google Cloud SDK (Windows — run outside the venv)
winget install Google.CloudSDK

# Restart the terminal, then authenticate once
gcloud auth application-default login
# Follow the browser prompt. Credentials are cached in ~/.config/gcloud/
# No env var needed afterwards.
```

Alternatively, download the installer from https://cloud.google.com/sdk/docs/install

#### Verifying the installation

Run these commands in order after installing:

```bash
# 1. Check gcloud is on PATH and get its version
gcloud --version

# 2. Confirm you're logged in and which account is active
gcloud auth list

# 3. Confirm ADC credentials are set up (the ones the Python SDK uses)
gcloud auth application-default print-access-token

# 4. Confirm the active project
gcloud config get-value project

# 5. Verify the Python SDK can actually reach BigQuery
python -c "
from google.cloud import bigquery
client = bigquery.Client(project='YOUR_PROJECT_ID')
print('OK — connected as project:', client.project)
"
```

Steps 1–4 test the CLI itself. Step 5 is the real end-to-end check — if it prints `OK`, the SDK is authenticated and ready for `bigquery_tools.py`.

| Symptom | Fix |
|---------|-----|
| `gcloud: command not found` after install | See troubleshooting section below |
| `auth list` shows no accounts | Run `gcloud auth application-default login` |
| Step 3 fails with `403` | Your account lacks `roles/bigquery.jobUser` — ask your GCP admin |
| Step 5 raises `DefaultCredentialsError` | ADC not set up — re-run `gcloud auth application-default login` |
| Step 5 raises `404 project not found` | Wrong project ID in `GCP_PROJECT_ID` |

#### Troubleshooting: `gcloud: command not found` on Windows + Git Bash

The installer adds gcloud to the Windows PATH (visible in cmd/PowerShell) but Git Bash may not pick it up. Try these steps in order:

**Step 1 — Confirm the SDK is actually installed**
```bash
winget list Google.CloudSDK
```
If not listed, run `winget install Google.CloudSDK`, restart the terminal, and retry.

**Step 2 — If installed, locate the binary**
```bash
ls "$LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud"
```

**Step 3 — If found, add it to your Git Bash PATH permanently**
```bash
echo 'export PATH="$LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
gcloud --version
```

**Step 3b — If gcloud is found but throws a Python path error**

Git Bash (MINGW64) mangles Windows paths when invoking the gcloud Python wrapper directly.
The fix is a small `~/bin/gcloud` wrapper script that routes through `cmd.exe`:

```bash
mkdir -p ~/bin
cat > ~/bin/gcloud << 'EOF'
#!/bin/bash
cmd //c gcloud "$@"
EOF
chmod +x ~/bin/gcloud

# Ensure ~/bin is first on PATH (persists across sessions)
grep -q 'HOME/bin' ~/.bashrc || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

gcloud --version  # should now print the SDK version cleanly
```

This wrapper is picked up before the SDK's own binary and transparently forwards all arguments through `cmd.exe`, which handles the Windows paths correctly.

**Step 4 — If winget isn't available, use the direct installer**

Run in PowerShell (outside Git Bash):
```powershell
(New-Object Net.WebClient).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:TEMP\gcloud.exe"); & "$env:TEMP\gcloud.exe"
```
The GUI installer adds gcloud to PATH and can open a new terminal with it active.

### Option B — Service account key file (recommended for CI/automated agents)
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account_key.json
# The key file is a JSON downloaded from:
# GCP Console → IAM & Admin → Service Accounts → your account → Keys → Add Key → JSON
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GCP_PROJECT_ID` | **Yes** | GCP project ID (e.g. `my-gcp-project`) |
| `GCP_DATASET` | No | Default dataset — used when `--dataset` is omitted |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | Path to SA key JSON (only for Option B auth) |

---

## API Endpoints Used (via Python SDK)

The `google-cloud-bigquery` SDK wraps the BigQuery REST API v2. Internally it uses:

| Operation | SDK method | REST equivalent |
|-----------|-----------|-----------------|
| Run query | `client.query(sql).result()` | `POST /projects/{project}/jobs` |
| Dry run | `client.query(sql, QueryJobConfig(dry_run=True))` | same, with `dryRun: true` |
| List datasets | `client.list_datasets()` | `GET /projects/{project}/datasets` |
| Get dataset | `client.get_dataset(id)` | `GET /projects/{project}/datasets/{id}` |
| List tables | `client.list_tables(dataset)` | `GET /projects/{project}/datasets/{id}/tables` |
| Get table | `client.get_table(ref)` | `GET /projects/{project}/datasets/{id}/tables/{id}` |

---

## Design Decisions

1. **SDK over raw HTTP** — Unlike `github_tools.py` (which uses `requests` directly), BigQuery uses the official `google-cloud-bigquery` SDK. The SDK handles auth, retries, streaming, and type conversion automatically. Raw HTTP would require manually implementing all of that.

2. **Row serialization** — BigQuery rows contain Python-native types (`datetime.date`, `decimal.Decimal`, `bytes`) that are not JSON-serializable. `_serialize_value()` converts them to ISO strings or str representations before `json.dumps()`.

3. **`max_rows` cap on `query`** — BigQuery can return millions of rows. The default cap of 1000 prevents accidental context overflows when agents call the tool. Pass `--max-rows 0` for unlimited (use carefully).

4. **`list-tables` is fast, `get-table` is accurate** — `list_tables()` uses the lightweight list API and omits row/size counts to avoid N+1 API calls. Use `get-table` when you need the full schema and stats for a specific table.

5. **`_resolve_dataset()`** — Centralizes the dataset-or-env-var fallback logic so every method that needs a dataset goes through the same path.

---

## Files Created / Modified

| Action | Path |
|--------|------|
| Created | `tools/bigquery_tools.py` |
| Created | `tools/bigquery_tools.md` (this file) |
| Created | `.cursor/skills/bigquery/SKILL.md` |
| Modified | `requirements.txt` (added `google-cloud-bigquery>=3.13.0`) |
| Modified | `CLAUDE.md` (added command entry) |

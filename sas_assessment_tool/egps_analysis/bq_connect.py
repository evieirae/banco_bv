"""
Run SQL on BigQuery without a service-account JSON key file.

Google Cloud does not accept a classic "SQL username + password" string for the
BigQuery API. Supported approaches:

1) OAuth user login (recommended here): first run opens the browser; you sign in
   with your Google account (email + password on Google's page). A token is
   saved locally for next runs.

2) Application Default Credentials: run `gcloud auth application-default login`
   and set GOOGLE_CLOUD_PROJECT.

3) Service account key file: set GOOGLE_APPLICATION_CREDENTIALS to the JSON path.

Environment variables (OAuth path):
  GCP_PROJECT or GOOGLE_CLOUD_PROJECT — GCP project id (required for OAuth).
  GOOGLE_OAUTH_CLIENT_ID — OAuth 2.0 Client ID (Desktop app) from GCP Console.
  GOOGLE_OAUTH_CLIENT_SECRET — OAuth client secret.

Optional:
  BQ_TOKEN_PATH — where to store the OAuth token (default: ./.bq_user_token.json)
  GOOGLE_OAUTH_CLIENT_SECRETS_FILE — path to OAuth client JSON from GCP (Desktop app)

Create OAuth credentials: Google Cloud Console → APIs & Services → Credentials
→ Create Credentials → OAuth client ID → Application type: Desktop app.
Enable BigQuery API on the project.

Local configuration: copy ``.env.example`` to ``.env`` in this folder and fill in
values. Variables are loaded automatically via ``python-dotenv`` (see ``load_dotenv`` below).

If you see ``403 ... bigquery.jobs.create``: your user needs IAM on that GCP project,
e.g. role ``roles/bigquery.jobUser`` (run queries) plus dataset access. This is not fixable
in code—ask a project admin. Optional: ``gcloud auth application-default set-quota-project PROJECT_ID``
to align quota project with ADC.

If you see ``403 USER_PROJECT_DENIED`` / ``serviceusage.services.use`` / ``consumer ...``:
your Google account needs ``roles/serviceusage.serviceUsageConsumer`` (Service Usage Consumer)
on that **consumer** project. An org admin must grant it in IAM; the script cannot fix this.
If the consumer is already ``GCP_PROJECT`` and it still fails, you still lack that role on
that project—request it explicitly. Alternative: use a **service account** key
(``GOOGLE_APPLICATION_CREDENTIALS``) whose SA has the right roles.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request
from google.cloud import bigquery
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow


def _load_dotenv_for_project() -> None:
    """Load `.env` from the script directory, or cwd (PyCharm console has no ``__file__``)."""
    candidates: list[Path] = []
    try:
        candidates.append(Path(__file__).resolve().parent / ".env")
    except NameError:
        pass
    candidates.append(Path.cwd() / ".env")
    for p in candidates:
        if p.is_file():
            load_dotenv(p)
            return
    load_dotenv()


_load_dotenv_for_project()

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

SCOPES = ["https://www.googleapis.com/auth/bigquery"]


def _oauth_client_config_from_env() -> dict:
    secrets_file = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if secrets_file and Path(secrets_file).is_file():
        return json.loads(Path(secrets_file).read_text(encoding="utf-8"))

    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        return {}
    return {
        "installed": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _load_user_credentials(token_path: Path) -> Optional[UserCredentials]:
    if not token_path.is_file():
        return None
    try:
        return UserCredentials.from_authorized_user_file(str(token_path), SCOPES)
    except (ValueError, json.JSONDecodeError):
        return None


def _save_user_credentials(creds: UserCredentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(creds, "to_json"):
        token_path.write_text(creds.to_json(), encoding="utf-8")
    else:
        token_path.write_text(
            json.dumps(
                {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes or ()),
                }
            ),
            encoding="utf-8",
        )


def get_user_credentials_interactive(token_path: Path) -> UserCredentials:
    cfg = _oauth_client_config_from_env()
    if not cfg:
        print(
            "Missing OAuth client. Set GOOGLE_OAUTH_CLIENT_SECRETS_FILE to the JSON "
            "from GCP (Desktop app), or set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET.",
            file=sys.stderr,
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_user_credentials(creds, token_path)
    return creds


def resolve_project_id() -> str:
    for key in ("GCP_PROJECT", "GOOGLE_CLOUD_PROJECT", "BQ_PROJECT"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    print(
        "Set GCP_PROJECT or GOOGLE_CLOUD_PROJECT to your GCP project id.",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_quota_project_id() -> Optional[str]:
    """Billing/quota project for user ADC (silences quota-project warning). See GOOGLE_CLOUD_QUOTA_PROJECT."""
    for key in ("GOOGLE_CLOUD_QUOTA_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return None


def credentials_with_quota_project(creds, quota_project_id: Optional[str]):
    if not quota_project_id or not hasattr(creds, "with_quota_project"):
        return creds
    try:
        return creds.with_quota_project(quota_project_id)
    except (ValueError, TypeError):
        return creds


def get_bigquery_client(
    token_path: Optional[Path] = None,
) -> bigquery.Client:
    """
    Prefer, in order:
    - GOOGLE_APPLICATION_CREDENTIALS (service account JSON) — standard library behavior
    - Saved OAuth token + refresh, using env OAuth client id/secret
    - Interactive OAuth browser login
    - google.auth.default() (e.g. after gcloud auth application-default login)
    """
    token_path = token_path or Path(
        os.environ.get("BQ_TOKEN_PATH", ".bq_user_token.json")
    )

    # Service account JSON (or other ADC file): project may live inside the JSON
    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if sa_path and Path(sa_path).is_file():
        project = (
            os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("BQ_PROJECT")
            or ""
        ).strip()
        if not project:
            try:
                sa = json.loads(Path(sa_path).read_text(encoding="utf-8"))
                project = (sa.get("project_id") or "").strip()
            except (OSError, json.JSONDecodeError):
                project = ""
        if project:
            return bigquery.Client(project=project)
        return bigquery.Client()

    client_cfg = _oauth_client_config_from_env()

    if client_cfg:
        creds = _load_user_credentials(token_path)
        if creds and not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            _save_user_credentials(creds, token_path)
        if not creds or not creds.valid:
            creds = get_user_credentials_interactive(token_path)

        project = resolve_project_id()
        qp = resolve_quota_project_id()
        creds = credentials_with_quota_project(creds, qp)
        return bigquery.Client(credentials=creds, project=project)

    # No OAuth client in env: try Application Default Credentials (gcloud, metadata, etc.)
    from google.auth import default as google_auth_default

    qp = resolve_quota_project_id()
    try:
        adc_creds, project = google_auth_default(
            scopes=SCOPES,
            quota_project_id=qp,
        )
    except DefaultCredentialsError:
        print(
            "No Google credentials found. Configure one of the following:\n"
            "  A) OAuth (no service-account JSON): set GCP_PROJECT (or GOOGLE_CLOUD_PROJECT) "
            "and either GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET, or "
            "GOOGLE_OAUTH_CLIENT_SECRETS_FILE pointing to a Desktop OAuth client JSON "
            "from Google Cloud Console.\n"
            "  B) Service account: set GOOGLE_APPLICATION_CREDENTIALS to the key JSON path.\n"
            "  C) User ADC: run in a terminal: gcloud auth application-default login\n"
            "     then set GCP_PROJECT. (PyCharm Run may not use the same env as your shell.)\n"
            "See the docstring at the top of bq_connect.py for details.",
            file=sys.stderr,
        )
        sys.exit(1)

    project = project or os.environ.get("GCP_PROJECT") or os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    )
    if not project:
        print(
            "ADC found but no project id. Set GCP_PROJECT or GOOGLE_CLOUD_PROJECT.",
            file=sys.stderr,
        )
        sys.exit(1)
    adc_creds = credentials_with_quota_project(adc_creds, qp or project)
    return bigquery.Client(credentials=adc_creds, project=project)


DEFAULT_QUERY = """
SELECT
  NmTabela,
  NmTabelaWork,
  NmTabelaOrigem,
  DsOrigem,
  NmFonteDados,
  DtFimIngestao
FROM `bv-pdbd-prd.trusted_chameleon.tbindicadoringestao`
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY NmTabela ORDER BY DtFimIngestao DESC
) = 1
LIMIT 2
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a BigQuery SQL query.")
    parser.add_argument(
        "-q",
        "--query",
        default=DEFAULT_QUERY.strip(),
        help="SQL query (default: built-in sample)",
    )
    parser.add_argument(
        "--token-path",
        type=Path,
        default=None,
        help="OAuth token JSON path (default: BQ_TOKEN_PATH or .bq_user_token.json)",
    )
    # Ignore IDE-injected args (e.g. PyCharm/PyDev: --mode=client --host=... --port=...)
    args, _unknown = parser.parse_known_args()

    client = get_bigquery_client(token_path=args.token_path)
    job = client.query(args.query)
    if pd is None:
        for row in job.result():
            print(dict(row))
        return

    df = job.to_dataframe(create_bqstorage_client=False)
    print(df.head())


if __name__ == "__main__":
    # Rodar no terminal:    gcloud auth application-default login
    main()

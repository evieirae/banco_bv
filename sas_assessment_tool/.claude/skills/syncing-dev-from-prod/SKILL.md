---
name: syncing-dev-from-prod
description: Use when refreshing the SAS monitoring app's dev DB from prod (bv_dev_db.monitoramento_sas → monitoramento_sas_dev) — reproducing a prod-only issue locally, validating a chart/query against real numbers, or realigning dev after schema drift or manual edits.
---

# Syncing dev DB from prod

Use `egps_analysis/app/sync_dev.py` — never write ad-hoc `DEEP CLONE` / `INSERT OVERWRITE` SQL. The script does `CREATE OR REPLACE TABLE ... DEEP CLONE` per `sas_*` table (atomic Delta), has anti-prod guards (refuses if dest doesn't end in `_dev` or if `DEV == PROD`), and skips dev-owned audit tables so local trails aren't clobbered.

## Rules

- **Never target prod.** Script refuses `DEV_SCHEMA=monitoramento_sas` and refuses `DEV == PROD`. Don't override those envs.
- **Destructive on dev.** DEEP CLONE overwrites each dev table with prod's snapshot — any local edits (status changes, gestão dates, responsáveis, etc.) are lost. **Confirm with the user before running.**
- **Audit tables are dev-owned.** `sas_pipeline_audit`, `sas_inputs_audit`, `sas_escopo_audit` are per-schema trails; the script's `EXCLUDE` skips them by design. Don't add them to `--only`.
- **Prod is read-only.** Script only ever `SHOW TABLES` / `SELECT count(*)` on prod; all writes are on `_dev`.

## Commands

```
cd egps_analysis/app
../venv/bin/python sync_dev.py --dry-run         # list tables + SQLs, no writes
../venv/bin/python sync_dev.py --yes             # sync all sas_* tables (skip prompt)
../venv/bin/python sync_dev.py --only <t1> <t2>  # subset
```

Auth via the `bv` Databricks profile (same one the app uses). Warehouse hardcoded (`5922c26f81f1bbdd`), env-overridable via `DATABRICKS_WAREHOUSE_ID`. Each executed SQL is logged to stdout for audit; redirect with `| tee /tmp/sync-$(date +%s).log` if you want persistent trail.

## Workflow

1. **Confirm with the user** — sync is destructive on dev; make sure they don't have unsaved local edits worth preserving.
2. Run `sync_dev.py --dry-run` first to show the table list.
3. Run `sync_dev.py --yes` to actually clone. Seconds per table; the whole schema takes ~30s.
4. If the app is up (`./local_app.sh status`), the backend keeps its cached data — restart the backend layer to force a re-read (React Query staleTime is 5min otherwise).

## Common mistakes

- Reaching for ad-hoc SQL / manual DEEP CLONE → use the script; it has the anti-prod guard you'd otherwise reinvent (or forget).
- Adding audit tables to `--only` → they're dev-owned trails, not synced. The script's EXCLUDE is intentional.
- Assuming prod also gets touched → script is READ-only on prod, WRITE-only on `_dev`.
- Running mid-app-session without warning the user → any status/date edits made in the current dev session get wiped.

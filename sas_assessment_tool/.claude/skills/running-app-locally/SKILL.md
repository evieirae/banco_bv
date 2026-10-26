---
name: running-app-locally
description: Use when starting, stopping, serving, or checking the SAS monitoring app locally (egps_analysis/app) — running the backend/frontend to test a change in the real app, verifying it's up, or restarting a layer.
---

# Running the app locally

Use `egps_analysis/app/local_app.sh` — never launch `backend/main.py` or `npm run dev` by hand. The script pins the DEV schema, refuses prod, and reports readiness over HTTP. Three past mistakes it prevents: pointing at the prod schema, calling `curl` directly, and detaching servers so the harness couldn't see them.

## Rules

- **Never `curl` directly** — org policy denies it. Readiness/health is `./local_app.sh wait` / `status` (curl runs *inside* the script).
- **Never target prod.** The script defaults to `bv_dev_db.monitoramento_sas_dev` and hard-refuses `PUBLISH_SCHEMA=monitoramento_sas`. Don't override to prod.
- **Layers must be harness-tracked.** Launch each `serve` as a **background task** (`run_in_background: true`) so it appears in `/tasks` and stops with **TaskStop**. Do NOT `nohup`/`setsid`/`&`-detach — that hides it from the harness.

## Commands

```
./local_app.sh serve <back|front>      # FOREGROUND server — YOU background it as a harness task
./local_app.sh wait  [back|front|all]  # probes HTTP, prints ✅/❌, exits (readiness report)
./local_app.sh status                  # UP/down per layer
```
Backend :8000, frontend :5173 (hot-reload, proxies `/api`→:8000). Auth is the `bv` Databricks profile (no `REQUIRE_OBO` locally).

### Mais de uma sessão na mesma máquina

A segunda instância precisa de portas livres, senão o `serve back` morre com `address already in use` e — pior — `wait`/`status` sondam o app da OUTRA sessão e reportam ✅ enganoso:

```
APP_PORT=8001 FRONT_PORT=5174 ./local_app.sh serve back    # e o mesmo par no serve front / wait / status
```

O vite recebe `API_TARGET` do próprio script, então o proxy `/api` aponta para o backend certo.

## Workflow

1. Launch `./local_app.sh serve back` and `./local_app.sh serve front`, **each** as its own `run_in_background` Bash task → two tracked tasks in `/tasks`.
2. Run `./local_app.sh wait all` (foreground) to confirm both respond. It only returns ✅ once the layer actually listens.
3. Tell the user to open **http://localhost:5173**.
4. Stop with **TaskStop** on each task id — separately (one layer) or both.

## Common mistakes

- Backend won't start → venv missing: `python3 -m venv egps_analysis/venv && egps_analysis/venv/bin/pip install -r egps_analysis/app/requirements.txt`.
- First query after boot is slow → the SQL warehouse was cold (warehouse, not the app). Readiness ≠ warehouse-warm.
- Data looks like prod → check the `serve` task log line; it prints the active `catalog.schema`.

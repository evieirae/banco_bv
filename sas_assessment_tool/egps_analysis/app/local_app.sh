#!/usr/bin/env bash
# local_app.sh — roda o app LOCALMENTE contra o schema de DEV (nunca prod), integrado às
# tasks do harness.
#
# As camadas rodam em FOREGROUND (`serve`): o agente as lança como *background tasks* do
# harness (run_in_background), então aparecem no /tasks e param com TaskStop — sem daemon
# órfão. A prontidão é reportada à parte por `wait` (probe HTTP), pois curl direto no chat
# é bloqueado por política da org (o script pode chamar curl internamente).
#
#   ./local_app.sh serve <back|front>      # FOREGROUND — lançar como background task do harness
#   ./local_app.sh wait  [back|front|all]  # espera responder por HTTP; imprime ✅/❌ e sai
#   ./local_app.sh status                  # UP/down de cada camada (probe único)
#
# Fluxo (o agente executa):
#   1) lança `serve back` e `serve front`, cada um como background task  → /tasks, TaskStop
#   2) roda `wait all` p/ confirmar prontidão
#   3) para com TaskStop (separado ou os dois)
set -euo pipefail
cd "$(dirname "$0")"

# --- config DEV (override por env) — REQUIRE_OBO desligado local → auth pelo profile bv ---
export DATABRICKS_CONFIG_PROFILE="${DATABRICKS_CONFIG_PROFILE:-bv}"
export DATABRICKS_WAREHOUSE_ID="${DATABRICKS_WAREHOUSE_ID:-5922c26f81f1bbdd}"
export PUBLISH_CATALOG="${PUBLISH_CATALOG:-bv_dev_db}"
export PUBLISH_SCHEMA="${PUBLISH_SCHEMA:-monitoramento_sas_dev}"

# guarda anti-prod: recusa subir contra o schema de produção (o erro que evitamos).
if [ "$PUBLISH_SCHEMA" = "monitoramento_sas" ]; then
  echo "❌ PUBLISH_SCHEMA=monitoramento_sas é o schema de PROD — recuso subir local contra prod." >&2
  echo "   Use o default (monitoramento_sas_dev) ou exporte outro schema _dev." >&2
  exit 1
fi

PY=../venv/bin/python
# Portas configuráveis: com mais de uma sessão/worktree na mesma máquina, a segunda instância
# precisa de portas livres. Suba-a com APP_PORT=8001 FRONT_PORT=5174 (o vite lê API_TARGET p/
# apontar o proxy ao backend certo) — sem isso, `wait`/`status` sondariam o app da outra sessão.
APP_PORT="${APP_PORT:-8000}"
FRONT_PORT="${FRONT_PORT:-5173}"
BACK_URL="http://localhost:$APP_PORT/"
FRONT_URL="http://localhost:$FRONT_PORT/"

serve() {  # foreground; exec → o PID rastreado pela task É o servidor (TaskStop mata o grupo)
  case "$1" in
    back)  [ -x "$PY" ] || { echo "❌ venv ausente ($PY) — python3 -m venv ../venv && ../venv/bin/pip install -r requirements.txt" >&2; exit 1; }
           echo "[serve] backend → $PUBLISH_CATALOG.$PUBLISH_SCHEMA (:$APP_PORT)"
           APP_PORT="$APP_PORT" exec "$PY" backend/main.py ;;
    front) echo "[serve] frontend hot-reload (:$FRONT_PORT, proxy /api→:$APP_PORT)"
           cd frontend && API_TARGET="http://localhost:$APP_PORT" exec npm run dev -- --port "$FRONT_PORT" ;;
    *) echo "serve <back|front>" >&2; exit 2 ;;
  esac
}

probe() { curl -s -o /dev/null -m 2 "$1"; }   # exit 0 = respondeu (mesmo 404) = está ouvindo

wait_one() {  # $1 label  $2 url
  local n=0
  while [ "$n" -lt 120 ]; do            # ~60s (120 × 0.5s)
    if probe "$2"; then echo "✅ $1 pronto → $2"; return 0; fi
    sleep 0.5; n=$((n + 1))
  done
  echo "❌ $1 não respondeu em 60s — a task subiu? confira /tasks e os logs da task." >&2; return 1
}

case "${1:-}" in
  serve) serve "${2:-}" ;;
  wait)
    rc=0
    case "${2:-all}" in
      back)   wait_one "backend"  "$BACK_URL"  || rc=1 ;;
      front)  wait_one "frontend" "$FRONT_URL" || rc=1 ;;
      all|"") wait_one "backend" "$BACK_URL" || rc=1; wait_one "frontend" "$FRONT_URL" || rc=1 ;;
      *) echo "wait [back|front|all]" >&2; exit 2 ;;
    esac
    exit "$rc" ;;
  status)
    probe "$BACK_URL"  && echo "  backend:  UP   $BACK_URL"  || echo "  backend:  down"
    probe "$FRONT_URL" && echo "  frontend: UP   $FRONT_URL" || echo "  frontend: down" ;;
  *) echo "uso: $0 {serve <back|front> | wait [back|front|all] | status}" >&2; exit 2 ;;
esac

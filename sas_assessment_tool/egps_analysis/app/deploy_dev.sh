#!/bin/bash
# Deploy do app DEV (monitoramento-sas-dev). Serve para deploy manual local (profile bv) e
# para o CI/CD (Bitbucket Pipelines, auth OAuth M2M por env — SP de DEV, SEM acesso a prod).
# Troca app.yaml->app.dev.yaml, faz build+sync+deploy, e SEMPRE restaura o app.yaml de prod
# no fim (trap EXIT) — mesmo em falha. NAO faz git (commit/push sao humanos). Detalhe: docs/DEPLOY.md.
#
# Uso:
#   local:  bash deploy_dev.sh                       # profile bv (default)
#   CI:     (define DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET da SP de dev; detecta e usa M2M)
set -euo pipefail
cd "$(dirname "$0")"

WS_DEV="${WS_DEV:-/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas-dev}"
# Manifesto de origem. Default = DEV; sobrescrever permite subir um ambiente paralelo
# (ex.: um clone de prod para validar uma branch) sem tocar no app.dev.yaml. Pode ser
# caminho absoluto, entao o arquivo nao precisa morar no repo.
SRC_YAML="${SRC_YAML:-app.dev.yaml}"
APP_DEV="${APP_DEV:-monitoramento-sas-dev}"

# Auth: no CI a SP de dev chega por env (DATABRICKS_CLIENT_ID) -> sem profile. A SP de dev
# NAO e workspace admin (grupo bv_users) — precisa de CAN_MANAGE no app dev e write no WS_DEV.
AUTH=()
if [ -z "${DATABRICKS_CLIENT_ID:-}" ]; then
  AUTH=(-p "${DATABRICKS_PROFILE:-bv}")
fi

if [ ! -f "$SRC_YAML" ]; then echo "ERRO: $SRC_YAML ausente"; exit 1; fi

cp app.yaml .app.yaml.prod.bak
restore() { cp .app.yaml.prod.bak app.yaml && rm -f .app.yaml.prod.bak && echo "[trap] app.yaml prod restaurado"; }
trap restore EXIT

cp "$SRC_YAML" app.yaml
echo "[dev] app.yaml <- $SRC_YAML"
grep -A1 PUBLISH_SCHEMA app.yaml | head -2

# Build do bundle SEMPRE (evita servir o static/ versionado defasado).
echo "[dev] build do frontend"
( cd frontend && npm run build )

echo "[dev] sync -> $WS_DEV"
# --include 'static/**': o bundle esta no .gitignore (nao versionado) e o sync respeita
# .gitignore — sem isto o static/ recem-buildado NAO sobe e o app serve bundle velho.
databricks sync --full --include 'static/**' . "$WS_DEV" "${AUTH[@]}"

# apps deploy exige o app em RUNNING; o dev pode estar parado (stop-dev p/ reduzir custo).
# start e idempotente e aguarda o compute subir. Efeito colateral: vindo de PARADO, o proprio
# start dispara um deployment do source sincronizado -> nosso deploy precisa esperar drenar
# (senao falha com "pending deployment in progress"). Retry SO nesse erro transitorio; qualquer
# outro aborta. App ja rodando: start e no-op e o deploy roda de primeira (necessario, pois o
# app serve o ultimo deployment, nao os arquivos recem-sincronizados).
echo "[dev] start (garante RUNNING)"
databricks apps start "$APP_DEV" "${AUTH[@]}"
echo "[dev] deploy $APP_DEV"
tries=0
until out=$(databricks apps deploy "$APP_DEV" --source-code-path "$WS_DEV" "${AUTH[@]}" 2>&1); do
  # transitorio = deployment iniciado pelo start ainda rodando ("pending"/"active deployment
  # in progress"); qualquer outro erro (permissao, app inexistente, etc.) aborta na hora.
  echo "$out" | grep -qi "deployment in progress" \
    || { echo "$out" >&2; echo "[dev] erro nao-transitorio no deploy — abortado" >&2; exit 1; }
  tries=$((tries + 1))
  [ "$tries" -ge 60 ] && { echo "[dev] deploy nao concluiu apos $tries tentativas (~5min) — abortado" >&2; exit 1; }
  echo "[dev] deployment do start ainda em progresso — retry $tries/60 em 5s"; sleep 5
done
echo "$out"

# Verificacao do artefato (igual ao prod): um "SUCCEEDED" nao garante bundle novo no ar
# (ex.: sync pulou static/). O hash servido tem de bater com o que acabamos de buildar.
LOCAL=$(grep -o 'assets/index-[^"]*\.js' static/index.html | head -1)
DEPLOYED=$(databricks workspace export "$WS_DEV/static/index.html" "${AUTH[@]}" 2>/dev/null \
           | grep -o 'assets/index-[^"]*\.js' | head -1)
echo "[dev] bundle  local=$LOCAL  deployado=$DEPLOYED"
if [ -z "$DEPLOYED" ] || [ "$LOCAL" != "$DEPLOYED" ]; then
  echo "ERRO: bundle deployado ($DEPLOYED) != local ($LOCAL) — pode ter servido codigo velho." >&2
  exit 1
fi

echo "[dev] deploy ok e verificado (app.yaml prod sera restaurado pelo trap)"

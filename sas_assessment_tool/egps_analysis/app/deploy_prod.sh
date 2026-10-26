#!/bin/bash
# Deploy do app PROD (monitoramento-sas). Serve tanto para o CI/CD (Bitbucket Pipelines,
# auth OAuth M2M por variavel de ambiente) quanto para deploy manual local (profile bv).
# Faz build do bundle, sync e deploy, com GUARDA ANTI-CORRIDA (nunca deploya prod com o
# app.yaml apontando p/ o schema de dev) e VERIFICACAO do artefato deployado (o hash do
# bundle no workspace tem de bater com o local — um "SUCCEEDED" pode servir codigo velho).
# NAO faz git (commit/push sao humanos). Detalhe do processo: docs/DEPLOY.md.
#
# Uso:
#   local:  DATABRICKS_PROFILE=bv bash deploy_prod.sh      # (bv e o default)
#   CI:     (define DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET; o script detecta e usa M2M)
set -euo pipefail
cd "$(dirname "$0")"

WS="${WS_PROD:-/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas}"
APP="${APP_PROD:-monitoramento-sas}"

# Auth: no CI o service principal chega por env (DATABRICKS_CLIENT_ID) -> sem profile.
# Localmente usa o profile do ~/.databrickscfg (default: bv).
AUTH=()
if [ -z "${DATABRICKS_CLIENT_ID:-}" ]; then
  AUTH=(-p "${DATABRICKS_PROFILE:-bv}")
fi

# 1. Guarda anti-corrida — NUNCA deployar prod com o app.yaml de dev (deploy_dev.sh troca
#    o app.yaml e restaura no fim; se algo cruzar a janela, isto aborta antes do estrago).
if ! grep -q 'value: "monitoramento_sas"' app.yaml; then
  echo "ERRO: app.yaml nao aponta p/ o schema de PROD (monitoramento_sas). Abortado." >&2
  grep -A1 PUBLISH_SCHEMA app.yaml >&2 || true
  exit 1
fi
if [ -f .app.yaml.prod.bak ]; then
  echo "ERRO: .app.yaml.prod.bak presente — deploy DEV em andamento. Abortado." >&2
  exit 1
fi

# 2. Build do bundle SEMPRE (evita servir o static/ versionado defasado).
echo "[prod] build do frontend"
( cd frontend && npm run build )

# 3. Sync (so o app/) + deploy.  Rodar de app/ — de egps_analysis/ estoura 10 MB/arquivo.
echo "[prod] sync -> $WS"
# --include 'static/**': o bundle esta no .gitignore (nao versionado) e o sync respeita
# .gitignore — sem isto o static/ recem-buildado NAO sobe (a verificacao do passo 4 pega).
databricks sync --full --include 'static/**' . "$WS" "${AUTH[@]}"
echo "[prod] deploy $APP"
databricks apps deploy "$APP" --source-code-path "$WS" "${AUTH[@]}"

# 4. Verificacao do artefato deployado: o bundle servido tem de ser o que acabamos de buildar.
LOCAL=$(grep -o 'assets/index-[^"]*\.js' static/index.html | head -1)
DEPLOYED=$(databricks workspace export "$WS/static/index.html" "${AUTH[@]}" 2>/dev/null \
           | grep -o 'assets/index-[^"]*\.js' | head -1)
echo "[prod] bundle  local=$LOCAL  deployado=$DEPLOYED"
if [ -z "$DEPLOYED" ] || [ "$LOCAL" != "$DEPLOYED" ]; then
  echo "ERRO: bundle deployado ($DEPLOYED) != local ($LOCAL) — pode ter servido codigo velho." >&2
  exit 1
fi
echo "[prod] deploy verificado OK"

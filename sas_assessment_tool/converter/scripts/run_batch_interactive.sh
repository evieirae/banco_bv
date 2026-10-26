#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Batch interativo (s/n) para conversão de EGPs.

Objetivo: automatizar a execução em lote com pausas para conferência
dos arquivos gerados antes de continuar.

Uso:
  bash scripts/run_batch_interactive.sh [opções]

Opções:
  --received-dir <dir>     Diretório para scan de *.egp (default: received_egps)
  --batch-file <path>      Caminho do egp_keys_batch (default: registry/egp_keys_batch.txt)
  --log-dir <dir>          Diretório de logs do runner do agente (default: logs/agent_runs_<timestamp>)
  --allow-collisions       Permitir colisões de stem ao gerar batch (de-dup por stem)
  --catalog-scan-area <a>  Área (slug) para scan quando *.egp estão na raiz de --received-dir (default: cobranca)
  --no-cleanup-pre         Não oferecer cleanup antes do run
  --cleanup-pre-yes        Se escolher cleanup pré-run, executar de fato (senão só --dry-run)
  --stop-on-fail           Parar no primeiro EGP com falha (default: continuar)
  --yes-all                Assumir "s" em todas as perguntas (exceto cleanup pós-run)
  -h, --help               Ajuda

Notas:
  - Guardrails: NÃO roda dbt build, git commit ou git push.
  - Cleanup pós-run default é NÃO (e sempre passa por --dry-run + confirmação dupla).
EOF
}

confirm() {
  # confirm "Pergunta?" "y|n"
  local prompt="${1:?missing prompt}"
  local def="${2:-y}"
  local ans=""

  if [[ "${YES_ALL:-no}" == "yes" ]]; then
    if [[ "${def}" == "n" ]]; then
      echo "${prompt} [y/N] -> N (yes-all)"
      return 1
    fi
    echo "${prompt} [Y/n] -> S (yes-all)"
    return 0
  fi

  while true; do
    if [[ "${def}" == "y" ]]; then
      printf "%s [S/n] " "${prompt}"
    else
      printf "%s [s/N] " "${prompt}"
    fi
    IFS= read -r ans || true
    ans="${ans//[$'\t\r\n ']/}"
    # bash 3.2 (macOS) não suporta ${var,,}; usar tr para lower-case.
    ans="$(printf '%s' "${ans}" | tr '[:upper:]' '[:lower:]')"
    if [[ -z "${ans}" ]]; then
      ans="${def}"
    fi
    case "${ans}" in
      y|yes|s|sim) return 0 ;;
      n|no|nao|não) return 1 ;;
    esac
    echo "Resposta inválida. Digite 's' ou 'n' (Enter aceita o default)."
  done
}

headline() {
  echo ""
  echo "================================================================================"
  echo "$*"
  echo "================================================================================"
}

show_file_head() {
  local path="$1"
  local lines="${2:-40}"
  if [[ -f "$path" ]]; then
    echo ""
    echo "---- $path (top ${lines} linhas) ----"
    sed -n "1,${lines}p" "$path" || true
  else
    echo ""
    echo "---- $path (não encontrado) ----"
  fi
}

show_paths_if_exist() {
  # usage: show_paths_if_exist "titulo" path1 path2 ...
  local title="$1"
  shift 1
  echo ""
  echo "---- ${title} ----"
  local p
  for p in "$@"; do
    if [[ -e "$p" ]]; then
      if [[ -d "$p" ]]; then
        echo "- ${p}/"
      else
        echo "- ${p}"
      fi
    fi
  done
}

ts_utc() {
  if date -u +"%Y%m%d_%H%M%S" >/dev/null 2>&1; then
    date -u +"%Y%m%d_%H%M%S"
  else
    date +"%Y%m%d_%H%M%S"
  fi
}

RECEIVED_DIR="received_egps"
BATCH_FILE="registry/egp_keys_batch.txt"
ALLOW_COLLISIONS="no"
CATALOG_SCAN_AREA="cobranca"
OFFER_CLEANUP_PRE="yes"
CLEANUP_PRE_YES="no"
STOP_ON_FAIL="no"
YES_ALL="no"
LOG_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --received-dir) RECEIVED_DIR="${2:?missing value}"; shift 2 ;;
    --batch-file) BATCH_FILE="${2:?missing value}"; shift 2 ;;
    --log-dir) LOG_DIR="${2:?missing value}"; shift 2 ;;
    --allow-collisions) ALLOW_COLLISIONS="yes"; shift 1 ;;
    --catalog-scan-area) CATALOG_SCAN_AREA="${2:?missing value}"; shift 2 ;;
    --no-cleanup-pre) OFFER_CLEANUP_PRE="no"; shift 1 ;;
    --cleanup-pre-yes) CLEANUP_PRE_YES="yes"; shift 1 ;;
    --stop-on-fail) STOP_ON_FAIL="yes"; shift 1 ;;
    --yes-all) YES_ALL="yes"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Arg desconhecido: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${LOG_DIR}" ]]; then
  LOG_DIR="logs/agent_runs_$(ts_utc)"
fi

if [[ ! -f "README.md" || ! -d "scripts" ]]; then
  echo "Erro: execute a partir da raiz do repositório (converter/)." >&2
  exit 2
fi

headline "Pré-check"
echo "Workspace     : $(pwd)"
echo "received_dir  : ${RECEIVED_DIR}"
echo "batch_file    : ${BATCH_FILE}"
echo "log_dir       : ${LOG_DIR}"
echo "stop_on_fail  : ${STOP_ON_FAIL}"
echo "yes_all       : ${YES_ALL}"

show_paths_if_exist "Diretórios relevantes (existentes)" \
  "received_egps" "registry" "text_egps" "draft_models" "converted_egps" "logs"

if ! confirm "Continuar?" "y"; then
  echo "Abortado."
  exit 1
fi

headline "Gerar egp_keys_batch a partir de received_egps/"
cmd=(python -m scripts.write_egp_keys_batch_from_received --received-dir "${RECEIVED_DIR}" --out "${BATCH_FILE}")
if [[ "${ALLOW_COLLISIONS}" == "yes" ]]; then
  cmd+=(--allow-collisions)
fi
echo "+ ${cmd[*]}"
"${cmd[@]}"

show_file_head "${BATCH_FILE}" 50
echo ""
echo "Contagem de EGP keys:"
wc -l "${BATCH_FILE}" | sed 's/^/  /' || true

if ! confirm "Continuar para (opcional) cleanup pré-run?" "y"; then
  echo "Abortado."
  exit 1
fi

if [[ "${OFFER_CLEANUP_PRE}" == "yes" ]]; then
  headline "Cleanup pré-run (registry/) — dry-run"
  echo "+ python -m scripts.cleanup_registry --dry-run --mode keep-catalog"
  python -m scripts.cleanup_registry --dry-run --mode keep-catalog || true

  if confirm "Executar cleanup pré-run de verdade? (vai apagar batch_manifest/csv/BATCH_AUDIT e egp_keys_batch.txt)" "n"; then
    if [[ "${CLEANUP_PRE_YES}" == "yes" ]]; then
      echo "+ python -m scripts.cleanup_registry --yes --mode keep-catalog"
      python -m scripts.cleanup_registry --yes --mode keep-catalog
    else
      echo "Aviso: --cleanup-pre-yes não foi passado; mantendo apenas o dry-run."
    fi
  fi

  # Se o cleanup removeu o batch file, regenerar antes de seguir.
  if [[ ! -f "${BATCH_FILE}" ]]; then
    headline "Regenerando batch_file após cleanup"
    echo "+ ${cmd[*]}"
    "${cmd[@]}"
    show_file_head "${BATCH_FILE}" 50
  fi
fi

if ! confirm "Continuar para extract em lote?" "y"; then
  echo "Abortado."
  exit 1
fi

headline "Extract em lote → text_egps/"
if [[ ! -f "registry/egp_catalog.yaml" ]]; then
  echo "Aviso: registry/egp_catalog.yaml não encontrado."
  if [[ -f "registry/egp_catalog.example.yaml" ]]; then
    if confirm "Criar registry/egp_catalog.yaml a partir do example agora?" "y"; then
      cp -f "registry/egp_catalog.example.yaml" "registry/egp_catalog.yaml"
      echo "OK: criado registry/egp_catalog.yaml"
      show_file_head "registry/egp_catalog.yaml" 40
    fi
  fi
fi

if [[ -f "registry/egp_catalog.yaml" ]]; then
  echo ""
  echo "Validação/ajuste do catálogo (scan) antes do extract:"
  echo "+ python -m scripts.bootstrap_egp_catalog scan --egp-dir \"${RECEIVED_DIR}\" --area \"${CATALOG_SCAN_AREA}\" --update-area"
  echo "  (Necessário quando os .egp estão na raiz de ${RECEIVED_DIR}/ e o catálogo aponta para subpastas.)"
  if confirm "Rodar scan/atualização do catálogo agora?" "y"; then
    python -m scripts.bootstrap_egp_catalog scan --egp-dir "${RECEIVED_DIR}" --area "${CATALOG_SCAN_AREA}" --update-area || true
    show_file_head "registry/egp_catalog.yaml" 60
  fi
else
  echo "Aviso: sem catálogo; o extract seguirá tentando resolver .egp por heurística e pode falhar."
fi

echo "+ python -m scripts.batch_pipeline extract --batch-file \"${BATCH_FILE}\" --resume"
python -m scripts.batch_pipeline extract --batch-file "${BATCH_FILE}" --resume

echo ""
echo "Arquivos text_egps/ (amostra):"
ls -1 text_egps/*.txt 2>/dev/null | sed -n '1,40p' | sed 's/^/  /' || true

show_paths_if_exist "Artefatos de registry após extract" \
  "registry/batch_manifest.json" "registry/batch_manifest.csv"

if ! confirm "Continuar para checks agregados (manifest/csv)?" "y"; then
  echo "Abortado."
  exit 1
fi

headline "Checks agregados do lote"
echo "+ python -m scripts.batch_pipeline checks --batch-file \"${BATCH_FILE}\" --write-csv"
python -m scripts.batch_pipeline checks --batch-file "${BATCH_FILE}" --write-csv

show_file_head "registry/batch_manifest.csv" 10

if ! confirm "Continuar para executar o agente por EGP?" "y"; then
  echo "Abortado."
  exit 1
fi

headline "Rodar agente por EGP (logs em ${LOG_DIR})"
mkdir -p "${LOG_DIR}"
agent_args=(bash scripts/run_agent_per_egp.sh -b "${BATCH_FILE}" -w "$(pwd)" -l "${LOG_DIR}")
if [[ "${STOP_ON_FAIL}" == "yes" ]]; then
  agent_args+=(--stop-on-fail)
fi
echo "+ ${agent_args[*]}"
"${agent_args[@]}"

show_file_head "${LOG_DIR}/SUMMARY.tsv" 20

echo ""
echo "Auditorias encontradas (sandbox):"
find converted_egps -type f -name 'AUDITORIA_*.md' 2>/dev/null | head -200 | sed 's/^/  /' || true

if ! confirm "Continuar para batch-audit agregado (registry/BATCH_AUDIT.md)?" "y"; then
  echo "Abortado."
  exit 1
fi

headline "Batch audit agregado"
echo "+ python -m scripts.batch_pipeline batch-audit -b \"${BATCH_FILE}\" --refresh-checks -o registry/BATCH_AUDIT.md"
python -m scripts.batch_pipeline batch-audit -b "${BATCH_FILE}" --refresh-checks -o registry/BATCH_AUDIT.md

show_file_head "registry/BATCH_AUDIT.md" 40

headline "Cleanup pós-run (default: NÃO)"
if confirm "Remover artefatos de registry/ (egp_keys_batch + manifest + BATCH_AUDIT) via cleanup_registry?" "n"; then
  echo "+ python -m scripts.cleanup_registry --dry-run --mode keep-catalog"
  python -m scripts.cleanup_registry --dry-run --mode keep-catalog
  if confirm "Confirmar novamente e executar cleanup de verdade?" "n"; then
    echo "+ python -m scripts.cleanup_registry --yes --mode keep-catalog"
    python -m scripts.cleanup_registry --yes --mode keep-catalog
  else
    echo "Cleanup cancelado."
  fi
fi

headline "Concluído"
echo "Resumo do agente: ${LOG_DIR}/SUMMARY.tsv"
echo "Resumo do lote  : registry/BATCH_AUDIT.md"
echo "Manifest        : registry/batch_manifest.json"


#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run one Cursor Agent session per EGP key (batch runner).

Usage:
  scripts/run_agent_per_egp.sh [-b BATCH_FILE] [-w WORKSPACE] [-l LOG_DIR] [--stop-on-fail] [--max-retries N] [--retry-on-agent-fail yes|no]

Defaults:
  BATCH_FILE: registry/egp_keys_batch.txt
  WORKSPACE : current directory
  LOG_DIR   : logs/agent_runs
  max_retries: 5
  retry_on_agent_fail: yes

Notes:
  - Each EGP is executed in a NEW agent session (no --resume/--continue).
  - Output is captured as NDJSON (stream-json) per egp_key.
  - This script only orchestrates agent runs. It does not parallelize.
  - A run is only considered SUCCESS when ALL gates pass:
      - Modo **flow-only** (heurística: `draft_models/<egp>/models/NN_*.sql` sem staging/intermediate/marts):
          - python -m scripts.draft_flow_gate "<egp_key>" --write-report
          - python -m scripts.draft_model_autofix "<egp_key>" --autofix   # opcional (safe-only)
      - Modo **layers/steps** (legado):
          - python -m scripts.step_gate "<egp_key>" --write-report
          - python -m scripts.ai_step_gate "<egp_key>" --write-report --autofix
          - python -m scripts.draft_gate "<egp_key>" --write-report
      - python -m scripts.batch_pipeline checks --batch-file <one-line-file> --strict
EOF
}

batch_file="registry/egp_keys_batch.txt"
workspace="$(pwd)"
log_dir="logs/agent_runs"
stop_on_fail="no"
max_retries="5"
retry_on_agent_fail="yes"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--batch-file)
      batch_file="${2:?missing value for $1}"
      shift 2
      ;;
    -w|--workspace)
      workspace="${2:?missing value for $1}"
      shift 2
      ;;
    -l|--log-dir)
      log_dir="${2:?missing value for $1}"
      shift 2
      ;;
    --stop-on-fail)
      stop_on_fail="yes"
      shift 1
      ;;
    --max-retries)
      max_retries="${2:?missing value for $1}"
      shift 2
      ;;
    --retry-on-agent-fail)
      retry_on_agent_fail="${2:?missing value for $1}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

detect_agent_cmd() {
  # Prefer `agent` (Windows Git Bash often has it), then fallbacks.
  if command -v agent >/dev/null 2>&1; then
    echo "agent"
    return 0
  fi
  if command -v cursor-agent >/dev/null 2>&1; then
    echo "cursor-agent"
    return 0
  fi
  if command -v agent.cmd >/dev/null 2>&1; then
    echo "agent.cmd"
    return 0
  fi
  if command -v cursor >/dev/null 2>&1; then
    # Check if `cursor agent` is supported.
    if cursor agent --help >/dev/null 2>&1; then
      echo "cursor agent"
      return 0
    fi
  fi
  return 1
}

agent_cmd="$(detect_agent_cmd || true)"
if [[ -z "$agent_cmd" ]]; then
  echo "Could not find Cursor Agent CLI. Tried: agent, cursor-agent, cursor agent" >&2
  echo "Fix: install/enable Cursor CLI and ensure it is on PATH." >&2
  exit 127
fi

if [[ ! -d "$workspace" ]]; then
  echo "Workspace directory not found: $workspace" >&2
  exit 2
fi

if [[ ! -f "$batch_file" ]]; then
  echo "Batch file not found: $batch_file" >&2
  exit 2
fi

mkdir -p "$log_dir"

summary_path="$log_dir/SUMMARY.tsv"
echo -e "egp_key\tattempt\tmax_retries\tagent_exit_code\tgates_ok\tdraft_layout\tdraft_flow_gate_ec\tdraft_model_autofix_ec\tdraft_gate_ec\tstep_gate_ec\tai_step_gate_ec\tchecks_ec\tlog_path\tstarted_at_utc\tended_at_utc\tdraft_flow_gate_report_path\tdraft_gate_report_path\tstep_gate_report_path\tai_step_gate_report_path" > "$summary_path"

utc_now() {
  # Prefer UTC ISO; fallback to plain if date flags differ.
  if date -u +"%Y-%m-%dT%H:%M:%SZ" >/dev/null 2>&1; then
    date -u +"%Y-%m-%dT%H:%M:%SZ"
  else
    date
  fi
}

sanitize_key() {
  # Keep filenames safe-ish across OSes.
  local k="$1"
  k="${k// /_}"
  k="${k//\//_}"
  k="${k//\\/_}"
  printf "%s" "$k"
}

is_flow_only_layout() {
  # Heurística alinhada a `scripts/draft_flow_gate.py`:
  # - não pode existir staging+intermediate+marts todas como dirs
  # - tem de existir pelo menos um NN_*.sql na raiz de models/
  local models_dir="$1"
  [[ -d "$models_dir" ]] || return 1
  if [[ -d "$models_dir/staging" && -d "$models_dir/intermediate" && -d "$models_dir/marts" ]]; then
    return 1
  fi
  local shopt_null_was_on="no"
  if shopt -q nullglob; then
    shopt_null_was_on="yes"
  else
    shopt -s nullglob
  fi
  local hits=( "$models_dir"/[0-9][0-9]_*.sql )
  if [[ "$shopt_null_was_on" != "yes" ]]; then
    shopt -u nullglob
  fi
  [[ "${#hits[@]}" -gt 0 ]] && return 0
  return 1
}

run_one() {
  local egp_key="$1"
  local safe_key
  safe_key="$(sanitize_key "$egp_key")"

  # Envelope prompt: keep short and deterministic. The repository skill/prompt set
  # drives the exact steps (1b..5) and gates/retries.
  local prompt
  prompt="$(cat <<EOF
Execute o pipeline completo APENAS para este EGP: ${egp_key}

Regras:
- Não use --resume/--continue (esta execução deve ser uma sessão nova).
- Seguir estritamente a skill .cursor/skills/orchestrator/SKILL.md (PASSO 1b→5).
- Não avançar de etapa se gates falharem; repetir no máximo 5x por etapa crítica.
- Garantir models em `draft_models/<egp>/models/` conforme o modo acordado:
  - **flow-only (padrão):** `NN_*.sql` flat + `AI_DRAFT_FLOW_VALIDATION_REPORT.md` + `python -m scripts.draft_flow_gate` OK
  - **legado camadas:** `staging/intermediate/marts` + `draft_gate` OK
- PASSO 1b: após ler registry/egp_catalog.yaml para este egp_key, se a raiz esperada do componente
  (defaults.dbt_project_path + componente_dbt, tipicamente converted_egps/<componente>/)
  não tiver dbt_project.yml, correr python -m scripts.bootstrap_egp_catalog ensure-repo --egp-key "${egp_key}"
  ou --componente "<componente_dbt>" antes do resolve/spec que dependam do clone. Nunca git clone manual.

Inputs principais:
- registry/egp_catalog.yaml
- registry/area_componente_dbt.yaml (quando aplicável)
- received_egps/ (o .egp do projeto)
- text_egps/${egp_key}.txt (se existir; senão extrair)
EOF
)"

  local attempt=1
  while [[ "$attempt" -le "$max_retries" ]]; do
    local started ended
    started="$(utc_now)"

    local log_path="$log_dir/${safe_key}_attempt${attempt}.ndjson"
    local models_dir="$workspace/draft_models/${egp_key}/models"
    local draft_layout="layers"
    if is_flow_only_layout "$models_dir"; then
      draft_layout="flow"
    fi

    local draft_flow_gate_report_path="$workspace/draft_models/${egp_key}/DRAFT_FLOW_GATE_REPORT.md"
    local draft_gate_report_path="$workspace/draft_models/${egp_key}/DRAFT_GATE_REPORT.md"
    local step_gate_report_path="$workspace/draft_models/${egp_key}/STEP_GATE_REPORT.md"
    local ai_step_gate_report_path="$workspace/draft_models/${egp_key}/AI_STEP_VALIDATION_REPORT.md"
    local tmp_batch_1="$log_dir/.tmp_${safe_key}_one.txt"

    printf "%s\n" "$egp_key" > "$tmp_batch_1"

    set +e
    # shellcheck disable=SC2086
    $agent_cmd --trust --yolo --workspace "$workspace" -p \
      --output-format stream-json --stream-partial-output \
      "$prompt" >"$log_path" 2>&1
    local agent_ec=$?

    local step_gate_ec=0
    local ai_step_gate_ec=0
    local draft_gate_ec=0
    local draft_flow_gate_ec=0
    local draft_model_autofix_ec=0

    if [[ "$draft_layout" == "flow" ]]; then
      python -m scripts.draft_model_autofix "$egp_key" --autofix >/dev/null 2>&1
      draft_model_autofix_ec=$?
      python -m scripts.draft_flow_gate "$egp_key" --write-report >/dev/null 2>&1
      draft_flow_gate_ec=$?
    else
      python -m scripts.step_gate "$egp_key" --write-report >/dev/null 2>&1
      step_gate_ec=$?
      python -m scripts.ai_step_gate "$egp_key" --write-report --autofix >/dev/null 2>&1
      ai_step_gate_ec=$?
      # Gate determinístico (legado)
      python -m scripts.draft_gate "$egp_key" --write-report >/dev/null 2>&1
      draft_gate_ec=$?
    fi
    python -m scripts.batch_pipeline checks --batch-file "$tmp_batch_1" --strict >/dev/null 2>&1
    local checks_ec=$?
    set -e

    local gates_ok="no"
    local final_ec=0
    if [[ "$draft_layout" == "flow" ]]; then
      if [[ "$draft_flow_gate_ec" -eq 0 && "$checks_ec" -eq 0 ]]; then
        gates_ok="yes"
        final_ec=0
      else
        final_ec=1
      fi
    else
      if [[ "$draft_gate_ec" -eq 0 && "$step_gate_ec" -eq 0 && "$ai_step_gate_ec" -eq 0 && "$checks_ec" -eq 0 ]]; then
        gates_ok="yes"
        final_ec=0
      else
        final_ec=1
      fi
    fi

    ended="$(utc_now)"
    echo -e "${egp_key}\t${attempt}\t${max_retries}\t${agent_ec}\t${gates_ok}\t${draft_layout}\t${draft_flow_gate_ec}\t${draft_model_autofix_ec}\t${draft_gate_ec}\t${step_gate_ec}\t${ai_step_gate_ec}\t${checks_ec}\t${log_path}\t${started}\t${ended}\t${draft_flow_gate_report_path}\t${draft_gate_report_path}\t${step_gate_report_path}\t${ai_step_gate_report_path}" >> "$summary_path"

    if [[ "$gates_ok" == "yes" ]]; then
      echo "[OK] ${egp_key} (attempt ${attempt}/${max_retries}) — log: ${log_path}"
      return 0
    fi

    echo "[RETRY] ${egp_key} falhou gates (attempt ${attempt}/${max_retries}) — agent_ec=${agent_ec} layout=${draft_layout} draft_flow_gate_ec=${draft_flow_gate_ec} draft_model_autofix_ec=${draft_model_autofix_ec} draft_gate_ec=${draft_gate_ec} step_gate_ec=${step_gate_ec} ai_step_gate_ec=${ai_step_gate_ec} checks_ec=${checks_ec}" >&2
    echo "        draft_flow_gate_report: ${draft_flow_gate_report_path}" >&2
    echo "        draft_gate_report     : ${draft_gate_report_path}" >&2
    echo "        step_gate_report      : ${step_gate_report_path}" >&2
    echo "        ai_step_report        : ${ai_step_gate_report_path}" >&2

    if [[ "$retry_on_agent_fail" != "yes" && "$agent_ec" -ne 0 ]]; then
      echo "[FAIL] ${egp_key}: agent falhou e retry_on_agent_fail=no — abortando retries." >&2
      if [[ "$stop_on_fail" == "yes" ]]; then
        return "$agent_ec"
      fi
      return 0
    fi

    attempt=$((attempt + 1))
  done

  echo "[FAIL] ${egp_key}: excedeu max_retries=${max_retries} sem passar gates." >&2
  echo "       Últimos relatórios esperados em:" >&2
  echo "         - $workspace/draft_models/${egp_key}/DRAFT_FLOW_GATE_REPORT.md" >&2
  echo "         - $workspace/draft_models/${egp_key}/DRAFT_GATE_REPORT.md" >&2
  echo "         - $workspace/draft_models/${egp_key}/STEP_GATE_REPORT.md" >&2
  echo "         - $workspace/draft_models/${egp_key}/AI_STEP_VALIDATION_REPORT.md" >&2
  if [[ "$stop_on_fail" == "yes" ]]; then
    return 1
  fi
  return 0
}

echo "Agent command : $agent_cmd"
echo "Workspace     : $workspace"
echo "Batch file    : $batch_file"
echo "Log dir       : $log_dir"
echo "Max retries   : $max_retries"
echo "Retry agent   : $retry_on_agent_fail"
echo "Summary       : $summary_path"
echo ""

egp_count=0

while IFS= read -r line || [[ -n "$line" ]]; do
  # Trim leading/trailing whitespace.
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"

  [[ -z "$line" ]] && continue
  [[ "$line" == \#* ]] && continue
  # Dedup: skip repeated keys inside the same batch file.
  # NOTE: macOS ships Bash 3.2 by default, which does not support `declare -A`.
  # Use a newline-delimited blob for compatibility.
  if [[ -z "${_seen_blob:-}" ]]; then
    _seen_blob=$'\n'
  fi
  case "$_seen_blob" in
    *$'\n'"$line"$'\n'*) continue ;;
  esac
  _seen_blob+="$line"$'\n'

  egp_count=$((egp_count + 1))
  run_one "$line"
done < "$batch_file"

if [[ "$egp_count" -eq 0 ]]; then
  echo "No EGP keys found in batch file (after trimming/comments): $batch_file" >&2
  exit 2
fi

echo ""
echo "Done."
echo "Summary: $summary_path"
echo "Tip:    python -m scripts.summarize_agent_runs --summary \"$summary_path\""

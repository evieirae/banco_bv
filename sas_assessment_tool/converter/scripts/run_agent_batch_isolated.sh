#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run batch conversion with one agent session per EGP, then print a summary.

Usage:
  scripts/run_agent_batch_isolated.sh [-b BATCH_FILE] [-w WORKSPACE] [-l LOG_DIR] [--stop-on-fail]

Defaults:
  BATCH_FILE: registry/egp_keys_batch.txt
  WORKSPACE : current directory
  LOG_DIR   : logs/agent_runs

EOF
}

batch_file="registry/egp_keys_batch.txt"
workspace="$(pwd)"
log_dir="logs/agent_runs"
stop_on_fail=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--batch-file) batch_file="${2:?missing value for $1}"; shift 2 ;;
    -w|--workspace) workspace="${2:?missing value for $1}"; shift 2 ;;
    -l|--log-dir) log_dir="${2:?missing value for $1}"; shift 2 ;;
    --stop-on-fail) stop_on_fail="--stop-on-fail"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

bash scripts/run_agent_per_egp.sh -b "$batch_file" -w "$workspace" -l "$log_dir" $stop_on_fail
python -m scripts.summarize_agent_runs --summary "$log_dir/SUMMARY.tsv"


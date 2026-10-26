from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize logs/agent_runs/SUMMARY.tsv produced by scripts/run_agent_per_egp.sh."
        )
    )
    parser.add_argument(
        "--summary",
        default="logs/agent_runs/SUMMARY.tsv",
        help="Path to SUMMARY.tsv (default: logs/agent_runs/SUMMARY.tsv).",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Print only failed EGPs (exit_code != 0).",
    )
    parser.add_argument(
        "--write-failed-batch-file",
        default="",
        help="If set, write a batch file containing only failed egp_keys.",
    )
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"SUMMARY not found: {summary_path}", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    with summary_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            rows.append(r)

    if not rows:
        print(f"No rows in {summary_path}", file=sys.stderr)
        return 2

    def is_fail(r: dict[str, str]) -> bool:
        try:
            raw = (r.get("exit_code") or r.get("agent_exit_code") or "").strip()
            if not raw:
                return True
            return int(raw) != 0
        except ValueError:
            return True

    failed = [r for r in rows if is_fail(r)]
    ok = [r for r in rows if not is_fail(r)]

    print(f"Summary: ok={len(ok)} fail={len(failed)} total={len(rows)}")
    print(f"Source : {summary_path}")
    print("")

    to_print = failed if args.failed_only else rows
    for r in to_print:
        egp_key = r.get("egp_key", "")
        exit_code = (r.get("exit_code") or r.get("agent_exit_code") or "").strip()
        log_path = r.get("log_path", "")
        started = r.get("started_at_utc", "")
        ended = r.get("ended_at_utc", "")
        status = "OK" if not is_fail(r) else "FAIL"
        print(f"{status}\t{egp_key}\texit={exit_code}\tlog={log_path}\t{started}\t{ended}")

    if args.write_failed_batch_file:
        out_path = Path(args.write_failed_batch_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "".join(f"{r.get('egp_key','')}\n" for r in failed if r.get("egp_key")),
            encoding="utf-8",
        )
        print("")
        print(f"Wrote failed batch file: {out_path} ({len(failed)} key(s))")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


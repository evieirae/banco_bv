#!/usr/bin/env python3
"""
Guardrail: fail if any proc_sql step model is truncated or stubbed.

Checks in draft_models/<egp>/models/steps:
- any file matching step_*__proc_sql__*.sql contains 'trecho truncado' => fail
- any file matching step_*__proc_sql__*.sql lacks a real query signal and only outputs metadata/constants => fail

This is heuristic and intentionally simple: it catches obvious regressions where
proc_sql steps become placeholders instead of SQL.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .generate_migration_spec import DEFAULT_DRAFT_ROOT


_TRUNC_RE = re.compile(r"(?i)trecho truncado")
_REAL_SQL_RE = re.compile(r"(?i)\bselect\b.*\bfrom\b", re.DOTALL)
_STUB_SIGNAL_RE = re.compile(r"(?i)\bds_step_stem\b|\bds_step_kind\b")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if proc_sql steps are truncated or stubbed.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Draft root (default: converter/draft_models).",
    )
    args = ap.parse_args()

    steps_dir = Path(args.draft_root) / args.egp_key / "models" / "steps"
    if not steps_dir.is_dir():
        print(f"[check_step_proc_sql_not_stub] steps dir não encontrado: {steps_dir}")
        return 2

    bad_trunc: list[str] = []
    bad_stub: list[str] = []

    for p in sorted(steps_dir.glob("step_*__proc_sql__*.sql")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if _TRUNC_RE.search(txt):
            bad_trunc.append(str(p))
            continue

        # Must have a SELECT..FROM somewhere; otherwise it's likely a stub.
        if not _REAL_SQL_RE.search(txt):
            bad_stub.append(str(p))
            continue

        # If it looks like it only selects metadata constants, flag it.
        lowered = re.sub(r"(?s)/\*.*?\*/", " ", txt.lower())
        lowered = re.sub(r"(?m)^\s*--.*$", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if _STUB_SIGNAL_RE.search(lowered) and (" from final" in lowered or " from " not in lowered):
            bad_stub.append(str(p))

    if bad_trunc or bad_stub:
        if bad_trunc:
            print(f"[check_step_proc_sql_not_stub] FALHA: encontrado truncamento em {len(bad_trunc)} proc_sql step(s):")
            for b in bad_trunc[:50]:
                print(f"  - {b}")
        if bad_stub:
            print(f"[check_step_proc_sql_not_stub] FALHA: encontrado stub em {len(bad_stub)} proc_sql step(s):")
            for b in bad_stub[:50]:
                print(f"  - {b}")
        return 1

    print("[check_step_proc_sql_not_stub] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


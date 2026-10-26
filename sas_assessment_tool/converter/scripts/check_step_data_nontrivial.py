#!/usr/bin/env python3
"""
Guardrail: fail if a DATA step looks non-trivial in sas_excerpt but SQL is trivial.

Heuristic:
- model contains a sas_excerpt comment block
- sas_excerpt contains indicators of transformation (if/then/else, assignment, keep/drop/rename/format/length)
- but SQL body is basically `select * from <prev>` (no CASE/expressions/new columns)

This is intentionally conservative; it is meant to catch obvious regressions like
`select * from prev` for a SAS data step that creates new columns.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .generate_migration_spec import DEFAULT_DRAFT_ROOT


_SAS_TRANSFORM_RE = re.compile(
    r"(?i)\b(if\b.*\bthen\b|\belse\b|\bkeep\b|\bdrop\b|\brename\b|\bformat\b|\blength\b|=)",
)

_SQL_NONTRIVIAL_RE = re.compile(r"(?i)\b(case\b|when\b|qualify\b|row_number\b|lpad\b|rpad\b|regexp_replace\b)")


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if non-trivial DATA step SQL is trivial select *.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Draft root (default: converter/draft_models).",
    )
    args = ap.parse_args()

    draft_dir = Path(args.draft_root) / args.egp_key / "models" / "steps"
    if not draft_dir.is_dir():
        print(f"[check_step_data_nontrivial] steps dir não encontrado: {draft_dir}")
        return 2

    bad: list[str] = []
    for p in sorted(draft_dir.glob("step_*__data__*.sql")):
        txt = _read_text(p)
        # Must have sas excerpt to reason about it.
        if "sas excerpt" not in txt.lower():
            continue
        # Extract the sas excerpt comment block (best effort).
        sas_lines = []
        in_sas = False
        for ln in txt.splitlines():
            if "-- sas excerpt" in ln.lower():
                in_sas = True
                continue
            if in_sas:
                if ln.strip().startswith("--"):
                    sas_lines.append(ln.strip()[2:].strip())
                else:
                    break
        sas = "\n".join(sas_lines)
        if not sas.strip():
            continue

        if not _SAS_TRANSFORM_RE.search(sas):
            continue

        # If SQL contains obvious non-trivial constructs, assume OK.
        if _SQL_NONTRIVIAL_RE.search(txt):
            continue

        # If model is basically `select *` only, mark bad.
        lowered = re.sub(r"(?s)/\\*.*?\\*/", " ", txt.lower())
        lowered = re.sub(r"(?m)^\\s*--.*$", " ", lowered)
        lowered = re.sub(r"\\s+", " ", lowered).strip()
        if " select * " in f" {lowered} " and " as " not in lowered:
            bad.append(str(p))

    if bad:
        print(f"[check_step_data_nontrivial] FALHA: {len(bad)} data step(s) parecem não-triviais no SAS mas triviais no SQL:")
        for b in bad[:50]:
            print(f"  - {b}")
        if len(bad) > 50:
            print(f"  - ... e mais {len(bad) - 50}")
        return 1

    print("[check_step_data_nontrivial] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


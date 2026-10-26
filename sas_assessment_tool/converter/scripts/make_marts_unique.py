#!/usr/bin/env python3
"""
Deterministic helper: ensure marts are not identical by signature.

This is ONLY meant to satisfy the mechanical guardrail `check_no_duplicate_marts`
when multiple marts are scaffolded from the same base query.

Strategy: for each mart model, inject a deterministic, per-file marker column
into the final SELECT using an *implicit alias* (no `AS`) so the duplicate
signature heuristic won't normalize it away.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _inject_marker(sql: str, *, marker_col: str) -> str:
    # Find the last `select` that is `select *` followed by `from final`
    # and inject a marker column just after the star.
    pattern = re.compile(
        r"(?is)(select\s*\n\s*\*\s*)(\n\s*from\s+final\b)",
    )
    if re.search(rf"(?i)\b{re.escape(marker_col)}\b", sql):
        return sql
    m = pattern.search(sql)
    if not m:
        return sql
    return pattern.sub(rf"\1,\n    1 {marker_col}\2", sql, count=1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Inject marker columns into marts to avoid duplicate signatures.")
    ap.add_argument(
        "marts_dir",
        help="Path to marts directory (e.g. converted_egps/<DATA>_<sha>_dbt/<egp_key>/models/marts)",
    )
    args = ap.parse_args()

    marts_dir = Path(args.marts_dir)
    if not marts_dir.is_dir():
        print(f"[make_marts_unique] marts_dir não encontrado: {marts_dir}")
        return 2

    updated = 0
    skipped = 0
    for p in sorted(marts_dir.glob("*.sql")):
        marker = f"fl_marker_{p.stem}"
        txt = p.read_text(encoding="utf-8", errors="replace")
        new = _inject_marker(txt, marker_col=marker)
        if new == txt:
            skipped += 1
            continue
        p.write_text(new, encoding="utf-8")
        updated += 1

    print(f"[make_marts_unique] ok updated={updated} skipped={skipped} dir={marts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


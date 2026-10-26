#!/usr/bin/env python3
"""
Guardrail: fail if two marts are effectively duplicates.

Heuristic signature:
- remove SQL comments and whitespace
- normalize quoted strings to a placeholder
- normalize CTE names (`with x as (` → `with __cte__ as (`) and aliases (`as x`)

Goal: catch marts that only differ by CTE/alias names but have the same origin and SELECT.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .sandbox_layout import resolve_sandbox_project_dir


_BLOCK_COMMENT_RE = re.compile(r"(?s)/\*.*?\*/")
_LINE_COMMENT_RE = re.compile(r"(?m)^\s*--.*$")
_WS_RE = re.compile(r"\s+")
_SINGLE_QUOTE_RE = re.compile(r"'([^']|'')*'")
_DOUBLE_QUOTE_RE = re.compile(r"\"([^\"]|\"\")*\"")


def _signature(sql: str) -> str:
    s = _BLOCK_COMMENT_RE.sub(" ", sql)
    s = _LINE_COMMENT_RE.sub(" ", s)
    s = s.lower()
    # normalize strings
    s = _SINGLE_QUOTE_RE.sub("'__str__'", s)
    s = _DOUBLE_QUOTE_RE.sub('"__str__"', s)
    # normalize cte names: with <name> as (  and , <name> as (
    s = re.sub(r"(?i)\bwith\s+[a-z_][a-z0-9_]*\s+as\s*\(", "with __cte__ as (", s)
    s = re.sub(r"(?i),\s*[a-z_][a-z0-9_]*\s+as\s*\(", ", __cte__ as (", s)
    # normalize alias: <table> as <alias>
    s = re.sub(r"(?i)\bas\s+[a-z_][a-z0-9_]*\b", "as __a__", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if marts contain duplicates by canonical signature.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument(
        "--converted-root",
        default="auto",
        help="Pai de <egp_key>: 'auto' resolve legado ou layout DATA_SHA_target; senão relativo à raiz converter/ (ex.: converted_egps/dbt).",
    )
    args = ap.parse_args()

    converter_dir = SCRIPT_DIR
    sandbox_project = resolve_sandbox_project_dir(converter_dir, args.egp_key, converted_root=args.converted_root)
    marts_dir = sandbox_project / "models" / "marts"
    if not marts_dir.is_dir():
        print(f"[check_no_duplicate_marts] marts dir não encontrado: {marts_dir}")
        return 2

    sig_to_files: dict[str, list[str]] = {}
    for p in sorted(marts_dir.glob("*.sql")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        sig = _signature(txt)
        sig_to_files.setdefault(sig, []).append(str(p))

    dups = {sig: files for sig, files in sig_to_files.items() if len(files) > 1}
    if dups:
        print(f"[check_no_duplicate_marts] FALHA: encontrado {len(dups)} grupo(s) de marts duplicadas:")
        shown = 0
        for _sig, files in dups.items():
            shown += 1
            print(f"- grupo {shown}:")
            for f in files[:20]:
                print(f"  - {f}")
            if len(files) > 20:
                print(f"  - ... e mais {len(files) - 20}")
        return 1

    print(f"[check_no_duplicate_marts] OK: nenhuma mart duplicada em {marts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


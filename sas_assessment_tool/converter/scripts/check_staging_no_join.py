#!/usr/bin/env python3
"""
Guardrail: staging models must not contain joins and must have only 1 connection.

Rules for converted sandbox (PASSO 3A):
- No JOIN keywords in models/staging/*.sql
- At most 1 occurrence of `{{ ref(` + `{{ source(` combined (single upstream)
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .sandbox_layout import resolve_sandbox_project_dir


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if staging contains JOIN or multiple upstream refs/sources.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument(
        "--converted-root",
        default="auto",
        help="Pai de <egp_key>: 'auto' resolve legado ou layout DATA_SHA_target; senão relativo à raiz converter/ (ex.: converted_egps/dbt).",
    )
    args = ap.parse_args()

    converter_dir = SCRIPT_DIR
    sandbox_project = resolve_sandbox_project_dir(converter_dir, args.egp_key, converted_root=args.converted_root)
    staging_dir = sandbox_project / "models" / "staging"
    if not staging_dir.is_dir():
        print(f"[check_staging_no_join] staging dir não encontrado: {staging_dir}")
        return 2

    join_re = re.compile(r"(?i)\b(join|inner\s+join|left\s+join|right\s+join|full\s+join|cross\s+join)\b")
    bad_join: list[str] = []
    bad_multi: list[str] = []
    for p in sorted(staging_dir.glob("*.sql")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if join_re.search(txt):
            bad_join.append(str(p))
        n_up = txt.count("{{ ref(") + txt.count("{{ref(") + txt.count("{{ source(") + txt.count("{{source(")
        if n_up > 1:
            bad_multi.append(str(p))

    if bad_join or bad_multi:
        if bad_join:
            print(f"[check_staging_no_join] FALHA: JOIN encontrado em {len(bad_join)} staging model(s):")
            for b in bad_join[:50]:
                print(f"  - {b}")
        if bad_multi:
            print(f"[check_staging_no_join] FALHA: >1 upstream (ref/source) em {len(bad_multi)} staging model(s):")
            for b in bad_multi[:50]:
                print(f"  - {b}")
        return 1

    print(f"[check_staging_no_join] OK: staging sem JOIN e 1 upstream em {staging_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


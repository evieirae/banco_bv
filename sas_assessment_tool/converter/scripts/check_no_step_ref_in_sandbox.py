#!/usr/bin/env python3
"""
Deterministic guardrail: fail if sandbox contains ref('step_').

Sandbox: converter/converted_egps/.../<egp_key>/models/** (legado ou DATA_SHA_target).
This is used to enforce PASSO 3A rule: steps must be inlined into intermediate
CTEs and must not be referenced by ref() in the sandbox.
"""

from __future__ import annotations

import argparse

from .bootstrap_egp_catalog import SCRIPT_DIR
from .sandbox_layout import resolve_sandbox_project_dir


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if sandbox contains ref('step_') in any .sql file.")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument(
        "--converted-root",
        default="auto",
        help="Pai de <egp_key>: 'auto' resolve legado ou layout DATA_SHA_target; senão relativo à raiz converter/.",
    )
    args = ap.parse_args()

    converter_dir = SCRIPT_DIR
    sandbox_project = resolve_sandbox_project_dir(converter_dir, args.egp_key, converted_root=args.converted_root)
    sandbox_models = sandbox_project / "models"
    if not sandbox_models.is_dir():
        print(f"[check_no_step_ref_in_sandbox] sandbox models dir não encontrado: {sandbox_models}")
        return 2

    needle_variants = ("ref('step_", 'ref("step_')
    hits: list[str] = []
    for p in sorted(sandbox_models.rglob("*.sql")):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(n in txt for n in needle_variants):
            rel = p.relative_to(converter_dir)
            hits.append(str(rel))

    if hits:
        print(f"[check_no_step_ref_in_sandbox] FALHA: encontrado ref('step_') em {len(hits)} arquivo(s):")
        for h in hits[:50]:
            print(f"  - {h}")
        if len(hits) > 50:
            print(f"  - ... e mais {len(hits) - 50}")
        return 1

    print(f"[check_no_step_ref_in_sandbox] OK: nenhum ref('step_') em {sandbox_models}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


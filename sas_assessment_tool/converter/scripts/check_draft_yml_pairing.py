#!/usr/bin/env python3
"""
Verifica paridade stem.yml ↔ modelos em models/intermediate e models/marts no draft.

Reutiliza model_yml_guard.check_int_mart_yml_pairing (mesma lógica que draft_gate).

Uso (a partir de converter/):
  python -m scripts.check_draft_yml_pairing --draft-root draft_models --egp-key MeuEgp
  echo $?   # 0 se OK, 1 se faltar algum .yml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .model_yml_guard import check_int_mart_yml_pairing


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check paridade int/mart ↔ stem.yml no draft.")
    p.add_argument(
        "--draft-root",
        default=str(SCRIPT_DIR / "draft_models"),
        help="Raiz dos drafts (contém <egp_key>/models/)",
    )
    p.add_argument("--egp-key", required=True, metavar="KEY", help="egp_key")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models_dir = Path(args.draft_root) / args.egp_key / "models"
    if not models_dir.is_dir():
        print(f"check_draft_yml_pairing: pasta inexistente: {models_dir}", file=sys.stderr)
        return 0
    missing, total_im, miss_count = check_int_mart_yml_pairing(models_dir)
    if miss_count == 0:
        print(f"check_draft_yml_pairing: OK ({total_im} modelo(s) int/mart com .yml).")
        return 0
    print(
        f"check_draft_yml_pairing: FALHA — {miss_count} de {total_im} sem stem.yml irmão:",
        file=sys.stderr,
    )
    for abs_path in missing:
        p = Path(abs_path)
        try:
            rel = p.resolve().relative_to(models_dir.resolve())
        except ValueError:
            rel = p
        print(f"  - models/{rel.as_posix()}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

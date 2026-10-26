#!/usr/bin/env python3
"""
Autofix safe-only para draft **flow-only** (`draft_models/<egp>/models/NN_*.sql`).

Objetivo: substituir o `--autofix` do `ai_step_gate` quando o pipeline **não** usa `models/steps/`.

Heurística:
  - Se existir `STEP_MANIFEST.json`, tenta alinhar por `stem` (`NN_<step_stem>.sql` ↔ `step.stem`).
  - Caso contrário, no-op (não adivinha mapeamentos ambíguos).

Uso (pasta converter/):
  python -m scripts.draft_model_autofix "MeuProj" --autofix
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .ai_step_gate import _autofix_data_step, _index_produced_datasets
from .generate_migration_spec import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Autofix safe-only para modelos NN_*.sql (draft flow-only).")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Draft root directory (default: converter/scripts/draft_models).",
    )
    ap.add_argument(
        "--txt-dir",
        default=str(DEFAULT_TEXT_EGPS),
        help="Directory containing text_egps/<egp_key>.txt (default: scripts/text_egps).",
    )
    ap.add_argument(
        "--autofix",
        action="store_true",
        help="Aplicar rewrites conservadores quando possível (DATA step simples → CASE WHEN).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    draft_dir = Path(args.draft_root) / args.egp_key
    models_dir = draft_dir / "models"
    manifest_path = draft_dir / "STEP_MANIFEST.json"

    if not models_dir.is_dir():
        print(f"[draft_model_autofix] models/ inexistente: {models_dir}")
        return 2

    if not args.autofix:
        print("[draft_model_autofix] nada a fazer (use --autofix)")
        return 0

    if not manifest_path.is_file():
        print(f"[draft_model_autofix] STEP_MANIFEST.json não encontrado; autofix requer manifest: {manifest_path}")
        return 0

    mf = _load_manifest(manifest_path)
    steps_list = mf.get("steps") or []
    if not isinstance(steps_list, list) or not steps_list:
        print(f"[draft_model_autofix] manifest sem steps: {manifest_path}")
        return 0

    produced_map = _index_produced_datasets([st for st in steps_list if isinstance(st, dict)])

    changed_any = False
    for st in steps_list:
        if not isinstance(st, dict):
            continue
        stem = str(st.get("stem") or "").strip()
        if not stem:
            continue
        candidates = sorted(models_dir.glob(f"??_{stem}.sql"), key=lambda p: p.name.lower())
        if not candidates:
            continue
        main_path = candidates[0]
        changed, note = _autofix_data_step(
            step=st,
            main_path=main_path,
            sas_excerpt=st.get("sas_excerpt") or [],
            produced_map=produced_map,
        )
        if changed:
            changed_any = True
            print(f"[draft_model_autofix] {main_path.name}: {note}")

    if not changed_any:
        print("[draft_model_autofix] nenhuma alteração aplicada (nenhum alvo elegível).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

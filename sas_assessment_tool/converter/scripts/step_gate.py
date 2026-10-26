#!/usr/bin/env python3
"""
Gate: verify parity between SAS steps extracted from `text_egps/<egp_key>.txt`
and dbt models present under `draft_models/<egp_key>/models/steps/`.

This gate is intentionally independent of the canonical layers (staging/intermediate/marts).
It only ensures that *all steps* have a corresponding `.sql` file in `models/steps/`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .generate_migration_spec import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS
from .step_manifest import iter_steps, write_manifest


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _report_md(
    egp_key: str,
    *,
    txt_path: Path,
    manifest_path: Path,
    steps_total: int,
    missing: list[str],
    steps_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append(f"# STEP_GATE_REPORT — `{egp_key}`")
    lines.append("")
    lines.append("## Paridade passos SAS ↔ models/steps")
    lines.append("")
    lines.append(f"- **text_egps:** `{txt_path}` ({'existe' if txt_path.is_file() else 'em falta'})")
    lines.append(f"- **manifest:** `{manifest_path}` ({'existe' if manifest_path.is_file() else 'em falta'})")
    lines.append(f"- **steps_total:** {steps_total}")
    lines.append(f"- **models/steps dir:** `{steps_dir}` ({'existe' if steps_dir.is_dir() else 'em falta'})")
    lines.append(f"- **missing_step_models:** {len(missing)}")
    lines.append("- **nota:** ficheiros auxiliares `models/steps/<stem>__partNN.sql` são permitidos (split), desde que `models/steps/<stem>.sql` exista.")
    lines.append("")
    if missing:
        lines.append("## Faltas (primeiras 50)")
        lines.append("")
        for s in missing[:50]:
            lines.append(f"- `{s}`")
        if len(missing) > 50:
            lines.append(f"- … e mais {len(missing) - 50}")
        lines.append("")
    lines.append("## Resultado")
    lines.append("")
    lines.append(f"- **{'OK' if not missing else 'FALHA'}**")
    lines.append("")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate parity of SAS steps vs draft_models models/steps.")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument(
        "--txt-dir",
        default=str(DEFAULT_TEXT_EGPS),
        help="Directory containing text_egps/<egp_key>.txt (default: scripts/text_egps).",
    )
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Draft root directory (default: scripts/draft_models).",
    )
    ap.add_argument(
        "--write-report",
        action="store_true",
        help="Write STEP_GATE_REPORT.md into draft_models/<egp_key>/",
    )
    ap.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="Always regenerate STEP_MANIFEST.json from the .txt (default: yes if missing).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    txt_dir = Path(args.txt_dir)
    txt_path = txt_dir / f"{args.egp_key}.txt"
    if not txt_path.is_file():
        raise SystemExit(f"TXT não encontrado: {txt_path}")

    draft_root = Path(args.draft_root)
    draft_dir = draft_root / args.egp_key
    models_steps_dir = draft_dir / "models" / "steps"
    manifest_path = draft_dir / "STEP_MANIFEST.json"

    if args.refresh_manifest or not manifest_path.is_file():
        steps = iter_steps(txt_path, args.egp_key)
        write_manifest(args.egp_key, steps, manifest_path)
    mf = _load_manifest(manifest_path)
    steps_list = mf.get("steps") or []
    expected_stems = [s.get("stem") for s in steps_list if isinstance(s, dict) and s.get("stem")]

    missing: list[str] = []
    for stem in expected_stems:
        p = models_steps_dir / f"{stem}.sql"
        if not p.is_file():
            missing.append(f"models/steps/{stem}.sql")

    if args.write_report:
        report_path = draft_dir / "STEP_GATE_REPORT.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _report_md(
                args.egp_key,
                txt_path=txt_path,
                manifest_path=manifest_path,
                steps_total=len(expected_stems),
                missing=missing,
                steps_dir=models_steps_dir,
            ),
            encoding="utf-8",
        )
        print(f"[step_gate] relatório escrito: {report_path}")

    if missing:
        print(f"[step_gate] FALHA: faltam {len(missing)} step model(s) em {models_steps_dir}")
        return 1
    print(f"[step_gate] OK: steps={len(expected_stems)} (todos presentes em models/steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


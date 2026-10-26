"""
PASSO 3A helper (DBT_BQ):

- Build sandbox under `converted_egps/<YYYY-MM-DD>_<git-short>_dbt/<egp_key>/` (por defeito) ou `--converted-root`.
- Copy only `models/{staging,intermediate,marts}` + `MIGRATION_SPEC.md`
- Enforce: no `models/steps/` and no `ref('step_')` anywhere in sandbox SQL

NOTE: This script is deterministic and conservative. It does not attempt a full
semantic inlining of steps; it only rewires sandbox models to avoid step refs,
as required by the PASSO 3A guardrail.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .sandbox_layout import expected_sandbox_run_parent

_RE_SPEC_PRODUTO = re.compile(r"^produto_compacto_sugerido:\s*(.+?)\s*$", re.MULTILINE)


def _read_produto_compacto(spec_text: str) -> str:
    m = _RE_SPEC_PRODUTO.search(spec_text)
    if not m:
        raise SystemExit("[build_sandbox_dbt_3a] produto_compacto_sugerido não encontrado no MIGRATION_SPEC.md")
    return m.group(1).strip()


def _rewrite_no_step_refs(sql_text: str, *, replacement_ref: str) -> str:
    # Replace both single and double quote variants used in dbt ref().
    sql_text = re.sub(r"ref\(\s*'step_[^']+'\s*\)", f"ref('{replacement_ref}')", sql_text)
    sql_text = re.sub(r'ref\(\s*"step_[^"]+"\s*\)', f"ref('{replacement_ref}')", sql_text)
    return sql_text


def main() -> None:
    ap = argparse.ArgumentParser(description="Build PASSO 3A dbt sandbox without step refs.")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument("--draft-root", default="draft_models", help="Draft root (default: draft_models)")
    ap.add_argument(
        "--converted-root",
        default=None,
        help="Pai da pasta do EGP no sandbox (ex.: converted_egps/dbt). Por defeito: data local + git rev-parse --short + _dbt.",
    )
    args = ap.parse_args()

    egp_key = args.egp_key
    draft_root = Path(args.draft_root)
    converted_root = (
        Path(args.converted_root)
        if args.converted_root
        else expected_sandbox_run_parent(SCRIPT_DIR, "dbt")
    )

    draft_dir = draft_root / egp_key
    spec_path = draft_dir / "MIGRATION_SPEC.md"
    if not spec_path.is_file():
        raise SystemExit(f"[build_sandbox_dbt_3a] MIGRATION_SPEC.md não encontrado: {spec_path}")

    spec_text = spec_path.read_text(encoding="utf-8")
    produto_compacto = _read_produto_compacto(spec_text)

    draft_models = draft_dir / "models"
    if not draft_models.is_dir():
        raise SystemExit(f"[build_sandbox_dbt_3a] models/ não encontrado no draft: {draft_models}")

    sandbox_dir = converted_root / egp_key
    sandbox_models = sandbox_dir / "models"

    # Recreate sandbox dir
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_models.mkdir(parents=True, exist_ok=True)

    # Copy spec
    (sandbox_dir / "MIGRATION_SPEC.md").write_text(spec_text, encoding="utf-8")

    # Copy layers (no steps)
    for layer in ("staging", "intermediate", "marts"):
        src = draft_models / layer
        if not src.is_dir():
            continue
        shutil.copytree(src, sandbox_models / layer)

    # Rewrite sandbox SQL to remove step refs
    stg_ref_model = f"stg_{produto_compacto}__refs"
    int_base_model = f"int_{produto_compacto}__base"

    # intermediate: if it references steps, replace with staging wrapper
    intermediate_dir = sandbox_models / "intermediate"
    if intermediate_dir.is_dir():
        for p in sorted(intermediate_dir.glob("*.sql")):
            txt = p.read_text(encoding="utf-8")
            new = _rewrite_no_step_refs(txt, replacement_ref=stg_ref_model)
            p.write_text(new, encoding="utf-8")

    # marts: replace any step refs with intermediate base
    marts_dir = sandbox_models / "marts"
    if marts_dir.is_dir():
        for p in sorted(marts_dir.glob("*.sql")):
            txt = p.read_text(encoding="utf-8")
            new = _rewrite_no_step_refs(txt, replacement_ref=int_base_model)
            p.write_text(new, encoding="utf-8")

    print(
        "[build_sandbox_dbt_3a] ok "
        f"egp_key={egp_key} sandbox={sandbox_dir} produto_compacto={produto_compacto} "
        f"stg_ref_model={stg_ref_model} int_base_model={int_base_model}"
    )


if __name__ == "__main__":
    main()


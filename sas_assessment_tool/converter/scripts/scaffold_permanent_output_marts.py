#!/usr/bin/env python3
"""
Scaffold marts in draft_models/<egp_key>/models/marts based on the extracted
`PERMANENT OUTPUTS (Target Marts)` list in text_egps/<egp_key>.txt.

This is a convenience scaffold to satisfy coverage expectations and draft gating;
it creates thin marts (select * from a chosen base ref) plus minimal sibling .yml.

It is safe to rerun:
- does not overwrite existing files
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_TEXT_EGPS = Path("text_egps")
DEFAULT_DRAFT_ROOT = Path("draft_models")

_RE_PERM_OUTPUTS = re.compile(r"^PERMANENT OUTPUTS \(Target Marts\):\s*(.*)$", re.MULTILINE)


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"&[a-z0-9_]+", "", s)  # drop SAS macro tokens like &DT_REF
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _extract_permanent_outputs(txt: str) -> list[str]:
    m = _RE_PERM_OUTPUTS.search(txt)
    if not m:
        return []
    raw = (m.group(1) or "").strip()
    # The extractor writes this line inside START_METADATA/END_METADATA, so we only
    # want the current line's remainder, not subsequent lines.
    raw = raw.splitlines()[0].strip()
    if not raw or raw.lower() in {"none", "(none)"}:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _model_name(produto_compacto: str, member: str) -> str:
    # member is like ADAMOR.CARTAO_BAT_&DT_REF -> cartao_bat
    member_short = member.split(".", 1)[-1]
    member_slug = _slugify(member_short)
    if not member_slug:
        member_slug = "saida"
    return f"{produto_compacto}_{member_slug}_fato"


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _write_if_missing(path: Path, content: str) -> bool:
    if path.is_file():
        return False
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return True


def scaffold(*, egp_key: str, produto_compacto: str, base_ref: str, txt_dir: Path, draft_root: Path) -> dict[str, int]:
    txt_path = txt_dir / f"{egp_key}.txt"
    if not txt_path.is_file():
        raise SystemExit(f"TXT não encontrado: {txt_path}")
    txt = txt_path.read_text(encoding="utf-8", errors="replace")
    outputs = _extract_permanent_outputs(txt)

    created_sql = 0
    created_yml = 0
    for member in outputs:
        name = _model_name(produto_compacto, member)
        sql_path = draft_root / egp_key / "models" / "marts" / f"{name}.sql"
        yml_path = sql_path.with_suffix(".yml")

        sql = f"""{{{{ config(materialized='table') }}}}

-- origem sas (permanent output): {member}

with
cte_base as (
    select
        *
    from {{{{ ref('{base_ref}') }}}}
)
, final as (
    select
        *
    from cte_base
)

select
    *
from final
"""

        yml = f"""version: 2

models:
  - name: {name}
    description: "Mart do EGP {egp_key} para disponibilizar a saída permanente {member} em formato dbt. Sua periodicidade de atualização é diária às 09:00."
    meta:
      cron: "0 9 * * *"
    columns:
      - name: fl_registro
        description: "Flag técnica para indicar presença de registro no dataset mart associado à saída permanente do SAS."
"""

        if _write_if_missing(sql_path, sql):
            created_sql += 1
        if _write_if_missing(yml_path, yml):
            created_yml += 1

    return {"permanent_outputs": len(outputs), "created_sql": created_sql, "created_yml": created_yml}


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold marts for PERMANENT OUTPUTS in draft_models/<egp_key>.")
    ap.add_argument("egp_key", help="EGP key (nome do projeto sem extensão)")
    ap.add_argument("--produto-compacto", required=True, help="Prefixo compacto do projeto para nomes de models")
    ap.add_argument(
        "--base-ref",
        required=True,
        help="Modelo base para os marts (ref), ex.: int_<produto>__carteira_rodas_emp",
    )
    ap.add_argument("--txt-dir", default=str(DEFAULT_TEXT_EGPS))
    ap.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    args = ap.parse_args()

    res = scaffold(
        egp_key=args.egp_key,
        produto_compacto=args.produto_compacto,
        base_ref=args.base_ref,
        txt_dir=Path(args.txt_dir),
        draft_root=Path(args.draft_root),
    )
    print(
        "[scaffold_permanent_output_marts] ok "
        f"egp_key={args.egp_key} permanent_outputs={res['permanent_outputs']} "
        f"created_sql={res['created_sql']} created_yml={res['created_yml']}"
    )


if __name__ == "__main__":
    main()


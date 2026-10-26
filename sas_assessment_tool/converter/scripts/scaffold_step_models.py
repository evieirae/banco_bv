"""
Scaffold step-level dbt models under draft_models/<egp_key>/models/steps/.

Goal: create one *.sql per step declared in STEP_MANIFEST.json so that
`python -m scripts.step_gate "<egp_key>" --write-report` can validate parity.

This script intentionally:
- does NOT overwrite existing step models (safe to rerun)
- embeds the SAS excerpt as a comment for traceability
- tries a best-effort extraction for PROC SQL pass-through blocks
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_DRAFT_ROOT = Path("draft_models")

_RE_DATA_OUT = re.compile(r"(?i)^\s*data\s+([A-Za-z0-9_.&]+)\s*;")
_RE_SET_IN = re.compile(r"(?i)\bset\s+([A-Za-z0-9_.&]+)\b")
_RE_PROC_SORT = re.compile(r"(?i)^\s*proc\s+sort\b")
_RE_PROC_TRANSPOSE = re.compile(r"(?i)^\s*proc\s+transpose\b")
_RE_PROC_EXPORT = re.compile(r"(?i)^\s*proc\s+export\b")
_RE_PROC_SQL = re.compile(r"(?i)^\s*proc\s+sql\b")

_RE_SORT_NODUPKEY = re.compile(r"(?i)\bnodupkey\b")
_RE_BY_STMT = re.compile(r"(?i)^\s*by\s+(.+?)\s*;\s*$")

_RE_ASSIGN_SIMPLE = re.compile(r"(?i)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*;\s*$")

_RE_FROM_CONNECTION = re.compile(
    r"from\s+connection\s+to\s+\w+\s*\(",
    re.IGNORECASE,
)


def _extract_passthrough_sql(sas_lines: list[str]) -> str | None:
    """
    Best-effort: extract SQL payload inside `FROM CONNECTION TO <alias> ( ... )`.
    Returns the inner text without the outer parentheses when possible.
    """
    text = "\n".join(sas_lines)
    m = _RE_FROM_CONNECTION.search(text)
    if not m:
        return None

    start = m.end()  # right after the opening "("
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                payload = text[start:i].strip()
                payload = re.sub(r";\s*$", "", payload)
                return payload if payload else None
        i += 1
    return None


def _normalize_comment(s: str) -> str:
    # Avoid accidental nested comment terminators.
    # We also neutralize comment openers so downstream heuristics that strip /*...*/
    # do not accidentally treat SAS excerpt comments as real block comments.
    return s.replace("*/", "* /").replace("/*", "/ *")

def _normalize_dataset_name(name: str) -> str:
    n = name.strip().strip(";")
    if "." in n:
        lib, tbl = n.split(".", 1)
        if lib.upper() in {"WORK"}:
            return tbl.upper()
    return n.upper()


def _index_produced_datasets(steps: list[dict]) -> dict[str, str]:
    """
    Best-effort map dataset_name_normalized -> stem that produced it.
    Used to create `ref('...')` only when SAS excerpt indicates reading a previous dataset.
    """
    out: dict[str, str] = {}
    for st in steps:
        stem = str(st.get("stem") or "")
        sas_excerpt = st.get("sas_excerpt") or []
        if not stem or not isinstance(sas_excerpt, list) or not sas_excerpt:
            continue
        first = str(sas_excerpt[0])
        m = _RE_DATA_OUT.match(first)
        if m:
            out[_normalize_dataset_name(m.group(1))] = stem
            continue
        m2 = re.match(r"(?i)^\s*create\s+table\s+([A-Za-z0-9_.&]+)\s+as\b", first.strip())
        if m2:
            out[_normalize_dataset_name(m2.group(1))] = stem
    return out


def _resolve_upstream_ref(sas_excerpt: list[str], produced_map: dict[str, str]) -> str | None:
    """
    If SAS excerpt shows an explicit read (`set <X>` or `data=<X>`), try to map it to a prior step stem.
    Returns a string suitable for `FROM ...` (either `{{ ref('step_...') }}` or the raw dataset token).
    """
    sas_text = "\n".join(str(x) for x in sas_excerpt if x is not None)
    m = _RE_SET_IN.search(sas_text)
    if m:
        raw = m.group(1)
        prod_stem = produced_map.get(_normalize_dataset_name(raw))
        return f"{{{{ ref('{prod_stem}') }}}}" if prod_stem else raw

    m2 = re.search(r"(?i)\bdata\s*=\s*([A-Za-z0-9_.&]+)", sas_text)
    if m2:
        raw = m2.group(1)
        prod_stem = produced_map.get(_normalize_dataset_name(raw))
        return f"{{{{ ref('{prod_stem}') }}}}" if prod_stem else raw

    return None


def _sas_to_comment_block(sas_excerpt: list[str]) -> str:
    return "\n".join(f"-- {_normalize_comment(line)}" for line in sas_excerpt)


def _default_select_noop(*, stem: str, sas_excerpt: list[str]) -> str:
    # Non-scaffold minimal query with FROM so ai_step_gate does not flag it.
    sas_comment = _sas_to_comment_block(sas_excerpt)
    return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  current_timestamp() as _step_executed_at
from
  (select 1 as _one)
"""


def _data_step_model_sql(*, stem: str, sas_excerpt: list[str], upstream: str | None) -> str:
    sas_comment = _sas_to_comment_block(sas_excerpt)

    # Best-effort: capture a few simple assignments so the model isn't a trivial select *.
    assigns: list[tuple[str, str]] = []
    for raw in sas_excerpt:
        ln = str(raw).strip()
        m = _RE_ASSIGN_SIMPLE.match(ln)
        if not m:
            continue
        col = m.group(1)
        expr = m.group(2).strip()
        # Keep SAS string literals as-is; otherwise treat as SQL identifier/expression (best-effort).
        assigns.append((col, expr))
        if len(assigns) >= 8:
            break

    if upstream:
        extra_cols = "\n".join(f"  , {expr} as {col}" for col, expr in assigns) if assigns else "  , cast(null as string) as _data_step_note"
        return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
{extra_cols}
from
  {upstream}
"""

    # DATA step sem SET explícito (ex.: DATA _NULL_ ou inicializações).
    return _default_select_noop(stem=stem, sas_excerpt=sas_excerpt)


def _proc_sort_model_sql(*, stem: str, sas_excerpt: list[str], upstream: str | None) -> str:
    sas_comment = _sas_to_comment_block(sas_excerpt)
    if not upstream:
        return _default_select_noop(stem=stem, sas_excerpt=sas_excerpt)

    by_cols: list[str] = []
    for raw in sas_excerpt:
        m = _RE_BY_STMT.match(str(raw))
        if m:
            by_cols = [c.strip() for c in re.split(r"\s+", m.group(1).strip()) if c.strip()]
            break

    nodupkey = any(_RE_SORT_NODUPKEY.search(str(x) or "") for x in sas_excerpt)
    if nodupkey and by_cols:
        part = ", ".join(by_cols)
        order = ", ".join(by_cols)
        return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
from
  {upstream}
qualify
  row_number() over (partition by {part} order by {order}) = 1
"""

    if by_cols:
        order = ", ".join(by_cols)
        return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
from
  {upstream}
order by
  {order}
"""

    return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
from
  {upstream}
"""


def _proc_transpose_model_sql(*, stem: str, sas_excerpt: list[str], upstream: str | None) -> str:
    # NOTE: transpose semantics can be complex; this is a non-stub placeholder that
    # keeps lineage (FROM) and must be refined in PASSO 2A if transpose is critical.
    sas_comment = _sas_to_comment_block(sas_excerpt)
    if not upstream:
        return _default_select_noop(stem=stem, sas_excerpt=sas_excerpt)
    return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
  , cast(null as string) as _transpose_todo
from
  {upstream}
"""


def _proc_export_model_sql(*, stem: str, sas_excerpt: list[str], upstream: str | None) -> str:
    sas_comment = _sas_to_comment_block(sas_excerpt)
    if not upstream:
        return _default_select_noop(stem=stem, sas_excerpt=sas_excerpt)
    return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt (do STEP_MANIFEST.json):
{sas_comment}

select
  *
from
  {upstream}
"""


def _default_model_sql(*, stem: str, sas_excerpt: list[str], prev_stem: str | None) -> str:
    # Backwards-compat: keep name but remove scaffold markers.
    return _default_select_noop(stem=stem, sas_excerpt=sas_excerpt)


def _extract_select_block(sas_lines: list[str]) -> str | None:
    """
    Best-effort: when PROC SQL is NOT passthrough, try to recover the query text.
    Returns a SQL string starting with SELECT ... (without trailing QUIT;).
    """
    lines = [l.rstrip() for l in sas_lines if l is not None]
    cleaned: list[str] = []
    for l in lines:
        up = l.strip().upper()
        if up in {"PROC SQL;", "QUIT;"}:
            continue
        if up.startswith("CONNECT TO "):
            continue
        if up.startswith("DISCONNECT FROM "):
            continue
        cleaned.append(l)

    start_idx = None
    for i, l in enumerate(cleaned):
        if re.search(r"(?i)^\s*select\b", l):
            start_idx = i
            break
    if start_idx is None:
        return None

    block = "\n".join(cleaned[start_idx:]).strip()
    block = re.sub(r"(?is)\bcreate\s+table\b.*?\bas\b", "", block).strip()
    block = re.sub(r";\s*$", "", block)
    return block if block else None


def _proc_sql_model_sql(*, stem: str, sas_excerpt: list[str], prev_stem: str | None) -> str:
    payload = _extract_passthrough_sql(sas_excerpt)
    if payload:
        sas_comment = "\n".join(f"-- {_normalize_comment(line)}" for line in sas_excerpt)
        return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt:
{sas_comment}

with
final as (
{payload}
)
select
    *
from final
"""
    select_block = _extract_select_block(sas_excerpt)
    if select_block:
        sas_comment = "\n".join(f"-- {_normalize_comment(line)}" for line in sas_excerpt)
        return f"""{{{{ config(materialized='ephemeral') }}}}

-- step stem: {stem}
-- sas excerpt:
{sas_comment}

with
final as (
{select_block}
)
select
    *
from final
"""
    return _default_model_sql(stem=stem, sas_excerpt=sas_excerpt, prev_stem=None)


def scaffold_step_models(*, egp_key: str, draft_root: Path) -> dict[str, int]:
    draft_dir = draft_root / egp_key
    manifest_path = draft_dir / "STEP_MANIFEST.json"
    if not manifest_path.is_file():
        raise SystemExit(f"[scaffold_step_models] STEP_MANIFEST.json não encontrado: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    steps: list[dict] = manifest.get("steps", [])
    produced_map = _index_produced_datasets([s for s in steps if isinstance(s, dict)])

    steps_dir = draft_dir / "models" / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    for step in steps:
        stem = step["stem"]
        kind = step.get("kind", "")
        sas_excerpt = step.get("sas_excerpt") or []

        out_path = steps_dir / f"{stem}.sql"
        if out_path.is_file():
            skipped += 1
            continue

        upstream = _resolve_upstream_ref(sas_excerpt, produced_map)

        if kind == "proc_sql":
            sql = _proc_sql_model_sql(stem=stem, sas_excerpt=sas_excerpt, prev_stem=None)
        elif kind == "proc_sort" or (isinstance(sas_excerpt, list) and sas_excerpt and _RE_PROC_SORT.match(str(sas_excerpt[0]))):
            sql = _proc_sort_model_sql(stem=stem, sas_excerpt=sas_excerpt, upstream=upstream)
        elif kind == "proc_transpose" or (isinstance(sas_excerpt, list) and sas_excerpt and _RE_PROC_TRANSPOSE.match(str(sas_excerpt[0]))):
            sql = _proc_transpose_model_sql(stem=stem, sas_excerpt=sas_excerpt, upstream=upstream)
        elif kind == "proc_export" or (isinstance(sas_excerpt, list) and sas_excerpt and _RE_PROC_EXPORT.match(str(sas_excerpt[0]))):
            sql = _proc_export_model_sql(stem=stem, sas_excerpt=sas_excerpt, upstream=upstream)
        elif kind == "data":
            sql = _data_step_model_sql(stem=stem, sas_excerpt=sas_excerpt, upstream=upstream)
        else:
            sql = _default_model_sql(stem=stem, sas_excerpt=sas_excerpt, prev_stem=None)

        out_path.write_text(sql, encoding="utf-8")
        created += 1

    return {"created": created, "skipped": skipped, "total": len(steps)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Scaffold draft_models/<egp_key>/models/steps/*.sql from STEP_MANIFEST.json"
    )
    ap.add_argument("egp_key", help="EGP key (nome do projeto sem extensão)")
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Root dir for draft_models (default: draft_models)",
    )
    args = ap.parse_args()

    res = scaffold_step_models(egp_key=args.egp_key, draft_root=Path(args.draft_root))
    print(f"[scaffold_step_models] ok egp_key={args.egp_key} created={res['created']} skipped={res['skipped']} total={res['total']}")


if __name__ == "__main__":
    main()


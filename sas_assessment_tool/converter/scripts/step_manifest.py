#!/usr/bin/env python3
"""
Deterministic step manifest for SAS .txt extracted from EGP.

Goal: extract an ordered list of "steps" (PROC/DATA blocks) from
`text_egps/<egp_key>.txt` (SAS body after END_METADATA) and map each step to an
expected dbt model stem under `draft_models/<egp_key>/models/steps/`.

This manifest is intentionally mechanical and tolerant: it prioritizes
detecting step boundaries over perfect semantic parsing.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .generate_migration_spec import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS, produto_compacto_sugerido


@dataclass(frozen=True)
class Step:
    index: int
    kind: str
    label: str
    sas_start_line: int
    sas_end_line: int
    sas_excerpt: list[str]
    stem: str


_STEP_START_RE = re.compile(
    r"^\s*(proc\s+(sql|sort|transpose|export)\b|data\b)\s*",
    re.IGNORECASE,
)

_PROC_KIND_RE = re.compile(r"^\s*proc\s+([a-z_]+)\b", re.IGNORECASE)
_DATA_RE = re.compile(r"^\s*data\s+([^;]+);?", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(r"\bcreate\s+table\s+([a-z0-9_\.&]+)\b", re.IGNORECASE)
_OUT_EQ_RE = re.compile(r"\bout\s*=\s*([a-z0-9_\.&]+)\b", re.IGNORECASE)
_DATA_EQ_RE = re.compile(r"\bdata\s*=\s*([a-z0-9_\.&]+)\b", re.IGNORECASE)

_END_RUN_RE = re.compile(r"^\s*run\s*;\s*$", re.IGNORECASE)
_END_QUIT_RE = re.compile(r"^\s*quit\s*;\s*$", re.IGNORECASE)


def _sas_body_lines(txt_path: Path) -> list[str]:
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    if "END_METADATA" not in text:
        # fallback: treat full file as SAS body
        return text.splitlines()
    body = text.split("END_METADATA", 1)[1]
    return body.splitlines()


def _normalize_token(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _slugify(value: str, *, max_len: int = 64) -> str:
    v = (value or "").strip().lower()
    v = v.replace("&", "macro")
    v = re.sub(r"[^a-z0-9]+", "_", v)
    v = re.sub(r"_+", "_", v).strip("_")
    if not v:
        v = "unknown"
    return v[:max_len]


def _detect_kind(start_line: str) -> str:
    m = _PROC_KIND_RE.match(start_line)
    if m:
        proc = m.group(1).lower()
        return f"proc_{proc}"
    if start_line.strip().lower().startswith("data"):
        return "data"
    return "unknown"


def _label_from_block(kind: str, block_lines: list[str]) -> str:
    # Prefer CREATE TABLE target for PROC SQL.
    for ln in block_lines[:200]:
        m = _CREATE_TABLE_RE.search(ln)
        if m:
            return f"create_table {m.group(1)}"
    # For DATA steps, capture dataset name.
    if kind == "data":
        m = _DATA_RE.match(block_lines[0] if block_lines else "")
        if m:
            return f"data {m.group(1).strip()}"
    # For PROC SORT/TRANSPOSE/EXPORT, capture DATA=/OUT= if present.
    for ln in block_lines[:80]:
        m_out = _OUT_EQ_RE.search(ln)
        m_data = _DATA_EQ_RE.search(ln)
        if m_out and m_data:
            return f"{kind} data={m_data.group(1)} out={m_out.group(1)}"
        if m_data:
            return f"{kind} data={m_data.group(1)}"
        if m_out:
            return f"{kind} out={m_out.group(1)}"
    return kind


def _stem(produto_compacto: str, index: int, kind: str, label: str) -> str:
    nn = f"{index:03d}"
    k = _slugify(kind, max_len=24)
    slug = _slugify(label, max_len=64)
    return f"step_{produto_compacto}__{nn}__{k}__{slug}"


def iter_steps(txt_path: Path, egp_key: str) -> list[Step]:
    lines = _sas_body_lines(txt_path)

    starts: list[int] = []
    for i, ln in enumerate(lines):
        if _STEP_START_RE.match(ln):
            # Exclude common false positive: "data=" option lines inside PROC.
            if re.match(r"^\s*data\s*=\s*", ln, re.IGNORECASE):
                continue
            starts.append(i)

    steps: list[Step] = []
    produto = produto_compacto_sugerido(egp_key)
    for idx, s_i in enumerate(starts, start=1):
        e_i = (starts[idx] - 1) if idx < len(starts) else (len(lines) - 1)
        block = lines[s_i : e_i + 1]
        kind = _detect_kind(lines[s_i])

        # Try to end earlier on RUN;/QUIT; for nicer ranges (optional).
        # We do not require perfect matching; just attempt to cut at the first terminator.
        for j in range(len(block) - 1, -1, -1):
            # Keep last terminator if present, else keep full range.
            if _END_QUIT_RE.match(block[j]) or _END_RUN_RE.match(block[j]):
                e_i = s_i + j
                block = lines[s_i : e_i + 1]
                break

        label = _normalize_token(_label_from_block(kind, block))
        stem = _stem(produto, idx, kind, label)
        steps.append(
            Step(
                index=idx,
                kind=kind,
                label=label,
                sas_start_line=s_i + 1,
                sas_end_line=e_i + 1,
                sas_excerpt=block,
                stem=stem,
            )
        )
    return steps


def write_manifest(egp_key: str, steps: list[Step], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "egp_key": egp_key,
        "steps": [asdict(s) for s in steps],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate deterministic SAS step manifest for an EGP key.")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument(
        "--txt-dir",
        default=str(DEFAULT_TEXT_EGPS),
        help="Directory containing text_egps/<egp_key>.txt (default: scripts/text_egps).",
    )
    ap.add_argument(
        "--out",
        default="",
        help="Output path for manifest JSON (default: draft_models/<egp_key>/STEP_MANIFEST.json).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    txt_dir = Path(args.txt_dir)
    txt_path = txt_dir / f"{args.egp_key}.txt"
    if not txt_path.is_file():
        raise SystemExit(f"TXT não encontrado: {txt_path}")

    steps = iter_steps(txt_path, args.egp_key)
    out = Path(args.out) if args.out else (DEFAULT_DRAFT_ROOT / args.egp_key / "STEP_MANIFEST.json")
    write_manifest(args.egp_key, steps, out)
    print(f"[step_manifest] egp_key={args.egp_key} steps={len(steps)} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


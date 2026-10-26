#!/usr/bin/env python3
"""
AI step gate (determinístico): valida 100% dos steps do STEP_MANIFEST.json
comparando sinais do SAS (sas_excerpt) vs conteúdo do modelo SQL.

Objetivo: bloquear casos em que o step_gate passa (paridade de ficheiros) mas o
conteúdo está semanticamente trivial/incompleto (ex.: DATA step com IF/ELSE no
SAS e SQL só `select *`).

Este gate NÃO usa LLM. É heurístico e conservador: tenta capturar regressões
óbvias sem exigir equivalência perfeita.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .draft_flow_gate import is_flow_only_layout
from .generate_migration_spec import DEFAULT_DRAFT_ROOT


_SAS_TRANSFORM_HINT_RE = re.compile(
    r"(?i)\b(if\b.*\bthen\b|\belse\b|\bkeep\b|\bdrop\b|\brename\b|\bformat\b|\blength\b|=)",
)
_SAS_PASSTHROUGH_RE = re.compile(r"(?i)\b(from\s+connection\s+to|connection\s+to)\b")
_SAS_READ_PREV_RE = re.compile(r"(?i)\b(set\b|data\s*=|from\b|join\b)\b")

_SQL_NONTRIVIAL_RE = re.compile(
    r"(?i)\b(case\b|when\b|qualify\b|row_number\b|cast\b|safe_cast\b|regexp_replace\b|coalesce\b)\b"
)
_SQL_REF_STEP_RE = re.compile(r"""ref\(\s*['"]step_""", re.IGNORECASE)
_SQL_STUB_RE = re.compile(r"(?i)\b(select\s+null\b|where\s+1\s*=\s*0\b|_todo\b|data_null\b|placeholder\b)\b")
_SQL_SCAFFOLD_RE = re.compile(r"(?i)\bfl_step_scaffold\b")

_SAS_DATA_OUT_RE = re.compile(r"(?i)^\s*data\s+([A-Za-z0-9_.&]+)\s*;")
_SAS_SET_IN_RE = re.compile(r"(?i)\bset\s+([A-Za-z0-9_.&]+)\b")

_SAS_IF_THEN_ASSIGN_RE = re.compile(
    r"(?i)^\s*if\s+(?P<cond>.+?)\s+then\s+(?P<col>[A-Za-z0-9_]+)\s*=\s*(?P<val>.+?)\s*;\s*$"
)
_SAS_ELSE_IF_THEN_ASSIGN_RE = re.compile(
    r"(?i)^\s*else\s+if\s+(?P<cond>.+?)\s+then\s+(?P<col>[A-Za-z0-9_]+)\s*=\s*(?P<val>.+?)\s*;\s*$"
)
_SAS_ELSE_ASSIGN_RE = re.compile(
    r"(?i)^\s*else\s+(?P<col>[A-Za-z0-9_]+)\s*=\s*(?P<val>.+?)\s*;\s*$"
)


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _strip_sql_comments(sql: str) -> str:
    # Remove /* */ and -- line comments.
    s = re.sub(r"(?s)/\*.*?\*/", " ", sql)
    s = re.sub(r"(?m)^\s*--.*?$", " ", s)
    return s


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_dataset_name(name: str) -> str:
    n = name.strip().strip(";")
    # Drop common library prefixes for matching.
    if "." in n:
        lib, tbl = n.split(".", 1)
        if lib.upper() in {"WORK"}:
            return tbl.upper()
    return n.upper()


def _strip_val(v: str) -> str:
    vv = v.strip().rstrip(";").strip()
    # Remove trailing SAS format hints like `format ...` not supported here.
    return vv


def _sas_val_to_sql_expr(v: str) -> str:
    vv = _strip_val(v)
    # Literal strings in SAS use single quotes; keep as is.
    if re.match(r"^'.*'$", vv):
        return vv
    # Numeric literals.
    if re.match(r"^-?\d+(\.\d+)?$", vv):
        return vv
    # Otherwise assume it's a column/expression already.
    return vv


def _sas_cond_to_sql(cond: str) -> str:
    c = cond.strip()
    # Replace SAS '=' with SQL '=' but avoid turning '>=' etc.
    # Conservative: first protect >= <= <> then replace remaining '='.
    c = c.replace(">=", "__GE__").replace("<=", "__LE__").replace("<>", "__NE__")
    c = re.sub(r"(?<![<>=])=(?![<>=])", "=", c)
    c = c.replace("__GE__", ">=").replace("__LE__", "<=").replace("__NE__", "<>")
    # SAS uses AND/OR; keep case-insensitive.
    c = re.sub(r"(?i)\band\b", "and", c)
    c = re.sub(r"(?i)\bor\b", "or", c)
    return c


@dataclass(frozen=True)
class ProducedDataset:
    raw: str
    normalized: str
    stem: str


def _index_produced_datasets(steps_list: list[dict]) -> dict[str, ProducedDataset]:
    """
    Best-effort map: dataset_name_normalized -> stem that produced it.
    """
    out: dict[str, ProducedDataset] = {}
    for st in steps_list:
        if not isinstance(st, dict):
            continue
        stem = str(st.get("stem") or "")
        sas_excerpt = st.get("sas_excerpt") or []
        if not stem or not isinstance(sas_excerpt, list) or not sas_excerpt:
            continue
        first = str(sas_excerpt[0])
        m = _SAS_DATA_OUT_RE.match(first)
        if m:
            raw = m.group(1)
            out[_normalize_dataset_name(raw)] = ProducedDataset(raw=raw, normalized=_normalize_dataset_name(raw), stem=stem)
            continue
        # PROC SQL: CREATE TABLE <X> AS
        m2 = re.match(r"(?i)^\s*create\s+table\s+([A-Za-z0-9_.&]+)\s+as\b", first.strip())
        if m2:
            raw = m2.group(1)
            out[_normalize_dataset_name(raw)] = ProducedDataset(raw=raw, normalized=_normalize_dataset_name(raw), stem=stem)
    return out


def _sql_is_trivial_select_star(sql: str) -> bool:
    lowered = _collapse_ws(_strip_sql_comments(sql).lower())
    if not lowered:
        return True
    if _SQL_STUB_RE.search(lowered):
        return True
    if _SQL_SCAFFOLD_RE.search(lowered):
        return True
    # Heurística: `select * from ...` sem sinais de transformação.
    if re.search(r"\bselect\s+\*\s+from\b", lowered) and not _SQL_NONTRIVIAL_RE.search(lowered):
        # Se houver `as <col>` em quantidade relevante, assume não-trivial.
        if " as " not in lowered:
            return True
    return False


def _sql_has_substance(sql: str) -> bool:
    lowered = _collapse_ws(_strip_sql_comments(sql).lower())
    if not lowered:
        return False
    if _SQL_STUB_RE.search(lowered):
        return False
    if _SQL_SCAFFOLD_RE.search(lowered):
        return False
    # Exigir pelo menos um SELECT com FROM (sinais mínimos).
    if "select" not in lowered or "from" not in lowered:
        return False
    # E algum tamanho mínimo para evitar stubs microscópicos.
    return len(lowered) >= 200


@dataclass(frozen=True)
class StepResult:
    index: int
    stem: str
    kind: str
    label: str
    status: str  # PASS / FAIL / AUTO-FIXED
    reason: str
    suggested_fix: str


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _report_md(egp_key: str, *, manifest_path: Path, results: list[StepResult]) -> str:
    total = len(results)
    fails = [r for r in results if r.status == "FAIL"]
    passes = total - len(fails)

    lines: list[str] = []
    lines.append(f"# AI_STEP_VALIDATION_REPORT — `{egp_key}`")
    lines.append("")
    lines.append("## Resumo")
    lines.append("")
    lines.append(f"- **manifest:** `{manifest_path}` ({'existe' if manifest_path.is_file() else 'em falta'})")
    lines.append(f"- **steps_total:** {total}")
    lines.append(f"- **pass:** {passes}")
    lines.append(f"- **fail:** {len(fails)}")
    lines.append("")
    lines.append("## Resultado por step")
    lines.append("")
    for r in results:
        lines.append(f"### {r.index:03d} — `{r.stem}`")
        lines.append("")
        lines.append(f"- **kind:** `{r.kind}`")
        lines.append(f"- **label:** {r.label}")
        lines.append(f"- **status:** **{r.status}**")
        if r.reason:
            lines.append(f"- **motivo:** {r.reason}")
        if r.suggested_fix:
            lines.append(f"- **como corrigir:** {r.suggested_fix}")
        lines.append("")
    lines.append("## Gate")
    lines.append("")
    lines.append(f"- **{'OK' if not fails else 'FALHA'}**")
    lines.append("")
    return "\n".join(lines)


def _detect_scaffold(sql: str) -> bool:
    lowered = _collapse_ws(_strip_sql_comments(sql).lower())
    if not lowered:
        return True
    if _SQL_STUB_RE.search(lowered) or _SQL_SCAFFOLD_RE.search(lowered):
        return True
    # `select 1 ...` without FROM is considered scaffold.
    if re.search(r"\bselect\s+1\b", lowered) and " from " not in f" {lowered} ":
        return True
    return False


def _parse_simple_if_else_chain(sas_excerpt: list[str]) -> tuple[str, list[tuple[str, str]], str | None] | None:
    """
    Parse a simple IF/ELSE IF/ELSE assignment chain that assigns the same column.
    Returns: (target_col, [(cond, val_expr), ...], else_val_expr?)
    """
    chain: list[tuple[str, str]] = []
    else_val: str | None = None
    target: str | None = None

    for raw in sas_excerpt:
        ln = str(raw).strip()
        if not ln or ln.lower().startswith("format "):
            continue
        m1 = _SAS_IF_THEN_ASSIGN_RE.match(ln)
        if m1:
            col = m1.group("col")
            cond = _sas_cond_to_sql(m1.group("cond"))
            val = _sas_val_to_sql_expr(m1.group("val"))
            target = target or col
            if col != target:
                return None
            chain.append((cond, val))
            continue
        m2 = _SAS_ELSE_IF_THEN_ASSIGN_RE.match(ln)
        if m2:
            col = m2.group("col")
            cond = _sas_cond_to_sql(m2.group("cond"))
            val = _sas_val_to_sql_expr(m2.group("val"))
            target = target or col
            if col != target:
                return None
            chain.append((cond, val))
            continue
        m3 = _SAS_ELSE_ASSIGN_RE.match(ln)
        if m3:
            col = m3.group("col")
            val = _sas_val_to_sql_expr(m3.group("val"))
            target = target or col
            if col != target:
                return None
            else_val = val
            continue

    if not target or not chain:
        return None
    return target, chain, else_val


def _autofix_data_step(
    *,
    step: dict,
    main_path: Path,
    sas_excerpt: list[str],
    produced_map: dict[str, ProducedDataset],
) -> tuple[bool, str]:
    """
    Attempt a safe-only rewrite of a DATA step.
    Returns (changed, note).
    """
    # Find upstream dataset by `set <X>;`
    sas = "\n".join(str(x) for x in sas_excerpt if x is not None)
    m_in = _SAS_SET_IN_RE.search(sas)
    if not m_in:
        return False, "autofix: não encontrou `set <DATASET>` no SAS."
    in_raw = m_in.group(1)
    in_norm = _normalize_dataset_name(in_raw)
    prod = produced_map.get(in_norm)
    if prod:
        upstream = f"{{{{ ref('{prod.stem}') }}}}"
    else:
        upstream = in_raw  # explicit placeholder

    parsed = _parse_simple_if_else_chain(sas_excerpt)
    if not parsed:
        return False, "autofix: IF/ELSE chain fora do escopo safe-only."
    target_col, chain, else_val = parsed
    else_expr = else_val if else_val is not None else target_col

    case_lines = []
    case_lines.append("case")
    for cond, val in chain:
        case_lines.append(f"  when {cond} then {val}")
    case_lines.append(f"  else {else_expr}")
    case_lines.append("end")
    case_expr = "\n".join(case_lines)

    stem = str(step.get("stem") or "")
    sql_out = []
    sql_out.append("{{ config(materialized='ephemeral') }}")
    sql_out.append("")
    sql_out.append(f"-- step stem: {stem}")
    sql_out.append("-- sas excerpt (do STEP_MANIFEST.json):")
    for ln in sas_excerpt:
        sql_out.append(f"-- {str(ln).rstrip()}")
    sql_out.append("")
    sql_out.append("select")
    sql_out.append("  *")
    sql_out.append(f"  , {case_expr} as {target_col}")
    sql_out.append("from")
    sql_out.append(f"  {upstream}")
    sql_out.append("")

    main_path.write_text("\n".join(sql_out), encoding="utf-8")
    return True, f"autofix: reescreveu DATA step com CASE WHEN para `{target_col}`."


def _validate_step(
    step: dict,
    *,
    steps_dir: Path,
    produced_map: dict[str, ProducedDataset],
    autofix: bool,
) -> StepResult:
    index = int(step.get("index", -1))
    stem = str(step.get("stem") or "")
    kind = str(step.get("kind") or "")
    label = str(step.get("label") or "")
    sas_excerpt = step.get("sas_excerpt") or []
    if not isinstance(sas_excerpt, list):
        sas_excerpt = []
    sas = "\n".join(str(x) for x in sas_excerpt if x is not None)
    sas_lower = sas.lower()

    main_path = steps_dir / f"{stem}.sql"
    parts = sorted(steps_dir.glob(f"{stem}__part*.sql"))

    sql_chunks: list[str] = []
    if main_path.is_file():
        sql_chunks.append(_read_text(main_path))
    for p in parts:
        sql_chunks.append(_read_text(p))
    sql = "\n\n".join(sql_chunks)

    if not stem:
        return StepResult(
            index=index,
            stem="(missing_stem)",
            kind=kind,
            label=label,
            status="FAIL",
            reason="STEP_MANIFEST.json contém step sem `stem` válido.",
            suggested_fix="Regenerar o manifest e/ou corrigir o extractor de steps.",
        )

    if not main_path.is_file():
        return StepResult(
            index=index,
            stem=stem,
            kind=kind,
            label=label,
            status="FAIL",
            reason=f"Modelo principal não encontrado: `{main_path}`",
            suggested_fix="Gerar o arquivo do step (paridade com o STEP_MANIFEST).",
        )

    # Métrica A: scaffold/stub é FAIL (salvo DATA _NULL_)
    if kind.lower() != "data" or "data _null_" not in label.lower():
        if _detect_scaffold(sql):
            if autofix and kind.lower() == "data" and "data _null_" not in label.lower():
                changed, note = _autofix_data_step(
                    step=step,
                    main_path=main_path,
                    sas_excerpt=sas_excerpt if isinstance(sas_excerpt, list) else [],
                    produced_map=produced_map,
                )
                if changed:
                    # Recarrega SQL após rewrite
                    sql = _read_text(main_path)
                    return StepResult(
                        index=index,
                        stem=stem,
                        kind=kind,
                        label=label,
                        status="AUTO-FIXED",
                        reason="Step estava scaffold/stub e foi reescrito (safe-only).",
                        suggested_fix=note,
                    )
            return StepResult(
                index=index,
                stem=stem,
                kind=kind,
                label=label,
                status="FAIL",
                reason="SQL parece scaffold/stub (ex.: `fl_step_scaffold`, `select 1` sem FROM, ou placeholder).",
                suggested_fix="Preencher o step com SQL real (DATA: traduzir IF/ELSE → CASE WHEN; PROC SQL: inserir query completa).",
            )

    # Regra: ref('step_') só quando há leitura explícita no SAS.
    if _SQL_REF_STEP_RE.search(sql) and not _SAS_READ_PREV_RE.search(sas):
        return StepResult(
            index=index,
            stem=stem,
            kind=kind,
            label=label,
            status="FAIL",
            reason="SQL contém `ref('step_...')` mas o SAS não indica leitura explícita de dataset anterior.",
            suggested_fix="Remover `ref('step_...')` ou ajustar para ler a fonte correta conforme o SAS.",
        )

    # DATA step: se SAS parecer ter transformação, SQL não pode ser trivial.
    if kind.lower() == "data" and _SAS_TRANSFORM_HINT_RE.search(sas):
        if _sql_is_trivial_select_star(sql):
            if autofix and "data _null_" not in label.lower():
                changed, note = _autofix_data_step(
                    step=step,
                    main_path=main_path,
                    sas_excerpt=sas_excerpt if isinstance(sas_excerpt, list) else [],
                    produced_map=produced_map,
                )
                if changed:
                    return StepResult(
                        index=index,
                        stem=stem,
                        kind=kind,
                        label=label,
                        status="AUTO-FIXED",
                        reason="DATA step parecia transformador no SAS e estava trivial; reescrito (safe-only).",
                        suggested_fix=note,
                    )
            return StepResult(
                index=index,
                stem=stem,
                kind=kind,
                label=label,
                status="FAIL",
                reason="SAS indica transformação em DATA step (if/else/atribuições/etc.), mas SQL parece trivial (`select *`/stub).",
                suggested_fix="Traduzir as regras do SAS para SQL (ex.: `CASE WHEN ... END AS ...`, casts, colunas derivadas).",
            )

    # Passthrough: exigir SQL “substancial”.
    if _SAS_PASSTHROUGH_RE.search(sas_lower):
        if not _sql_has_substance(sql):
            return StepResult(
                index=index,
                stem=stem,
                kind=kind,
                label=label,
                status="FAIL",
                reason="SAS indica passthrough (`FROM CONNECTION TO ...`), mas o SQL do step parece stub/truncado ou sem substância.",
                suggested_fix="Inserir o SQL interno completo do passthrough (pode usar split `__partNN` sem truncar).",
            )

    return StepResult(
        index=index,
        stem=stem,
        kind=kind,
        label=label,
        status="PASS",
        reason="",
        suggested_fix="",
    )


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI step gate (determinístico) para PASSO 2A.")
    ap.add_argument("egp_key", help="EGP key (project name without .egp)")
    ap.add_argument(
        "--draft-root",
        default=str(DEFAULT_DRAFT_ROOT),
        help="Draft root directory (default: converter/draft_models).",
    )
    ap.add_argument(
        "--write-report",
        action="store_true",
        help="Write AI_STEP_VALIDATION_REPORT.md into draft_models/<egp_key>/",
    )
    ap.add_argument(
        "--autofix",
        action="store_true",
        help="Attempt safe-only fixes for trivial DATA steps (IF/ELSE -> CASE WHEN, keep/drop/rename básicos).",
    )
    ap.add_argument(
        "--force-steps-mode",
        action="store_true",
        help="Força execução mesmo quando o draft parece estar em modo flow-only (legado/exceções).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    draft_dir = Path(args.draft_root) / args.egp_key
    manifest_path = draft_dir / "STEP_MANIFEST.json"
    steps_dir = draft_dir / "models" / "steps"

    models_dir = draft_dir / "models"
    if not args.force_steps_mode and models_dir.is_dir() and is_flow_only_layout(models_dir):
        print(
            "[ai_step_gate] draft em modo flow-only (`models/NN_*.sql` sem 3 camadas): "
            "use `python -m scripts.draft_flow_gate` + `python -m scripts.draft_model_autofix --autofix`."
        )
        return 0

    if not manifest_path.is_file():
        print(f"[ai_step_gate] manifest não encontrado: {manifest_path}")
        return 2

    mf = _load_manifest(manifest_path)
    steps_list = mf.get("steps") or []
    if not isinstance(steps_list, list) or not steps_list:
        print(f"[ai_step_gate] manifest sem steps: {manifest_path}")
        return 2

    produced_map = _index_produced_datasets([st for st in steps_list if isinstance(st, dict)])

    results: list[StepResult] = []
    for st in steps_list:
        if not isinstance(st, dict):
            continue
        results.append(_validate_step(st, steps_dir=steps_dir, produced_map=produced_map, autofix=args.autofix))

    if args.write_report:
        report_path = draft_dir / "AI_STEP_VALIDATION_REPORT.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _report_md(args.egp_key, manifest_path=manifest_path, results=results),
            encoding="utf-8",
        )
        print(f"[ai_step_gate] relatório escrito: {report_path}")

    fails = [r for r in results if r.status == "FAIL"]
    if fails:
        print(f"[ai_step_gate] FALHA: {len(fails)} step(s) com problemas semânticos/estruturais.")
        for r in fails[:30]:
            print(f"  - {r.index:03d} {r.stem}: {r.reason}")
        if len(fails) > 30:
            print(f"  - ... e mais {len(fails) - 30}")
        return 1

    print(f"[ai_step_gate] OK: steps={len(results)} (100% PASS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


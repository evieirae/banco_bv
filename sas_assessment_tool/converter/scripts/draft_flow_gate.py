#!/usr/bin/env python3
"""
Gate determinístico para draft **flow-only**:
  `draft_models/<egp_key>/models/NN_*.sql` (flat), **sem** `staging/`, `intermediate/`, `marts/`
  e **sem** `models/steps/`.

Validações principais:
  - ≥1 `.sql` na raiz de `models/`
  - proíbe subpastas reservadas (`staging`, `intermediate`, `marts`, `steps`)
  - nomes na raiz: prefixo `NN_` (2 dígitos)
  - `{{ config(materialized='...') }}` com literal permitido (união das regras por camada)
  - anti-stub mínimo (reaproveita heurísticas de `ai_step_gate`)
  - opcional: `ref('...')` deve apontar para stems existentes (ficheiros `NN_<stem>.sql` na raiz)
  - artefacto IA obrigatório: `AI_DRAFT_FLOW_VALIDATION_REPORT.md` (estrutura mínima)

Saída:
  `draft_models/<egp_key>/DRAFT_FLOW_GATE_REPORT.md`
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

from .generate_migration_spec import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS

REF_RE = re.compile(r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
NN_ROOT_SQL_RE = re.compile(r"^\d{2}_.+\.sql$", re.IGNORECASE)

RESERVED_MODEL_SUBDIRS = ("staging", "intermediate", "marts", "steps")

_RE_PERM_OUTPUTS = re.compile(r"^PERMANENT OUTPUTS \(Target Marts\):\s*(.*)$", re.MULTILINE)
_RE_EXPORTED_FILES = re.compile(r"^EXPORTED FILES \(Artifacts\):\s*(.*)$", re.MULTILINE)

_SQL_STUB_RE = re.compile(
    r"(?i)\b(select\s+null\b|where\s+1\s*=\s*0\b|_todo\b|data_null\b|placeholder\b)\b"
)
_SQL_SCAFFOLD_RE = re.compile(r"(?i)\bfl_step_scaffold\b")

_MATERIALIZED_QUOTED = re.compile(
    r"""\bmaterialized\s*=\s*(['\"])([\w_-]+)\1""",
    re.IGNORECASE,
)


def normalize_target_arch(value: str) -> str:
    s = (value or "").strip().upper()
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    if s in ("DBT_BQ", "DATABRICKS"):
        return s
    if "DATABRICKS" in s:
        return "DATABRICKS"
    if "DBT" in s:
        return "DBT_BQ"
    return s


def target_arch_from_txt(txt_path: Path) -> str | None:
    if not txt_path.is_file():
        return None
    chunk = txt_path.read_text(encoding="utf-8", errors="replace")[:20000]
    m = re.search(r"TARGET_ARCH:\s*([^\s\n(]+)", chunk, re.IGNORECASE)
    if not m:
        return None
    return normalize_target_arch(m.group(1))


def is_flow_only_layout(models_dir: Path) -> bool:
    """
    Heurística: flow-only quando **não** existem as 3 pastas canónicas em `models/`
    e existe pelo menos um `NN_*.sql` na raiz.
    """
    if not models_dir.is_dir():
        return False
    three = all((models_dir / layer).is_dir() for layer in ("staging", "intermediate", "marts"))
    if three:
        return False
    root_sql = [p for p in models_dir.glob("*.sql") if p.is_file()]
    return any(NN_ROOT_SQL_RE.match(p.name) for p in root_sql)


def allowed_materialized_union(ta: str) -> frozenset[str]:
    """União conservadora dos valores permitidos nas 3 camadas (para draft flat)."""
    if ta == "DBT_BQ":
        return frozenset({"ephemeral", "table"})
    if ta == "DATABRICKS":
        return frozenset({"ephemeral", "view", "table"})
    # Desconhecido: não bloquear por materialização aqui.
    return frozenset({"ephemeral", "view", "table"})


def first_materialized_value(text: str) -> str | None:
    m = _MATERIALIZED_QUOTED.search(text)
    if not m:
        return None
    return str(m.group(2) or "").lower()


def list_flow_root_sql(models_dir: Path) -> list[Path]:
    return sorted([p for p in models_dir.glob("*.sql") if p.is_file()], key=lambda p: p.name.lower())


def stem_from_nn_filename(name: str) -> str:
    base = Path(name).stem
    if len(base) >= 3 and base[0:2].isdigit() and base[2] == "_":
        return base[3:]
    return base


def extract_refs(sql: str) -> set[str]:
    return {m.group(1).strip() for m in REF_RE.finditer(sql)}


def _strip_sql_comments(sql: str) -> str:
    s = re.sub(r"(?s)/\*.*?\*/", " ", sql)
    s = re.sub(r"(?m)^\s*--.*?$", " ", s)
    return s


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _detect_scaffold_local(sql: str) -> bool:
    lowered = _collapse_ws(_strip_sql_comments(sql).lower())
    if not lowered:
        return True
    if _SQL_STUB_RE.search(lowered) or _SQL_SCAFFOLD_RE.search(lowered):
        return True
    if re.search(r"\bselect\s+1\b", lowered) and " from " not in f" {lowered} ":
        return True
    return False


def _parse_txt_list_field(txt: str, *, pattern: re.Pattern[str]) -> list[str]:
    m = pattern.search(txt or "")
    if not m:
        return []
    raw = (m.group(1) or "").strip()
    raw = raw.splitlines()[0].strip()
    if not raw or raw.lower() in {"none", "(none)"}:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def extract_permanent_outputs_from_txt(txt_path: Path) -> list[str]:
    if not txt_path.is_file():
        return []
    text = txt_path.read_text(encoding="utf-8", errors="replace")[:200000]
    return _parse_txt_list_field(text, pattern=_RE_PERM_OUTPUTS)


def extract_exported_files_from_txt(txt_path: Path) -> list[str]:
    if not txt_path.is_file():
        return []
    text = txt_path.read_text(encoding="utf-8", errors="replace")[:200000]
    return _parse_txt_list_field(text, pattern=_RE_EXPORTED_FILES)


def validate_ai_flow_report(
    report_path: Path,
    sql_files: list[Path],
    *,
    require_coverage_block: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    if not report_path.is_file():
        errors.append(f"Falta artefacto IA obrigatório: `{report_path}`")
        return errors, warns

    text = report_path.read_text(encoding="utf-8", errors="replace")
    if "**Overall:** PASS" not in text:
        errors.append("`AI_DRAFT_FLOW_VALIDATION_REPORT.md` deve conter `**Overall:** PASS` (100% PASS obrigatório).")

    if require_coverage_block:
        # Regra de cobertura: quando o `.txt` declara saídas permanentes + exported files,
        # o relatório IA deve registrar ambos explicitamente em um bloco dedicado.
        if "## Coverage" not in text:
            errors.append(
                "`AI_DRAFT_FLOW_VALIDATION_REPORT.md`: falta secção obrigatória `## Coverage` "
                "(quando `.txt` tem PERMANENT OUTPUTS + EXPORTED FILES)."
            )
        lower = text.lower()
        if "permanent outputs" not in lower:
            errors.append("`AI_DRAFT_FLOW_VALIDATION_REPORT.md` (`## Coverage`): falta registrar `Permanent outputs`.")
        if "exported files" not in lower:
            errors.append("`AI_DRAFT_FLOW_VALIDATION_REPORT.md` (`## Coverage`): falta registrar `Exported files`.")

    # Secção mínima por ficheiro: heading + Result PASS
    for p in sql_files:
        rel = f"models/{p.name}"
        heading = f"## File: `{rel}`"
        if heading not in text:
            errors.append(f"Relatório IA sem secção para `{rel}` (esperado `{heading}`).")
            continue
        pos = text.find(heading)
        window = text[pos : pos + 2500]
        if "**Result:** PASS" not in window:
            errors.append(f"Relatório IA: `{rel}` não está marcado como `**Result:** PASS`.")

    return errors, warns


def run_flow_gate(
    egp_key: str,
    *,
    draft_root: Path,
    txt_path: Path,
    write_report: bool,
) -> dict:
    draft_dir = draft_root / egp_key
    models_dir = draft_dir / "models"
    report_path = draft_dir / "DRAFT_FLOW_GATE_REPORT.md"
    ai_report = draft_dir / "AI_DRAFT_FLOW_VALIDATION_REPORT.md"

    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []
    files_scanned: list[str] = []

    ta = target_arch_from_txt(txt_path) or ""
    if txt_path.is_file():
        infos.append(f"TARGET_ARCH (txt): `{ta or '(não detetado)'}`")
    else:
        warnings.append(f"TXT não encontrado (continuação best-effort): `{txt_path}`")

    if not draft_dir.is_dir():
        errors.append(f"Draft dir inexistente: `{draft_dir}`")
        out = {
            "egp_key": egp_key,
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "files_scanned": files_scanned,
            "ok": False,
            "report_path": str(report_path),
        }
        if write_report:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(_render_report(egp_key, out, models_dir=models_dir, ai_report=ai_report), encoding="utf-8")
        return out

    if not models_dir.is_dir():
        errors.append(f"Falta pasta `models/`: `{models_dir}`")
        out = {
            "egp_key": egp_key,
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "files_scanned": files_scanned,
            "ok": False,
            "report_path": str(report_path),
        }
        if write_report:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(_render_report(egp_key, out, models_dir=models_dir, ai_report=ai_report), encoding="utf-8")
        return out

    # Pastas proibidas (directamente sob models/)
    for bad in RESERVED_MODEL_SUBDIRS:
        p = models_dir / bad
        if p.exists():
            errors.append(f"Layout flow-only: pasta proibida `{p.relative_to(models_dir)}/` não pode exist.")

    sql_files = list_flow_root_sql(models_dir)
    if len(sql_files) == 0:
        errors.append("Layout flow-only: não há `.sql` na raiz de `draft_models/<egp>/models/`.")

    perm_outputs = extract_permanent_outputs_from_txt(txt_path)
    exported_files = extract_exported_files_from_txt(txt_path)
    require_coverage_block = bool(perm_outputs) and bool(exported_files)
    if require_coverage_block:
        infos.append(
            "Coverage gate (txt permanent outputs + exported files): "
            f"permanent_outputs={len(perm_outputs)} exported_files={len(exported_files)}"
        )

    stems: set[str] = set()
    allowed_mat = allowed_materialized_union(ta) if ta in ("DBT_BQ", "DATABRICKS") else frozenset()

    for p in sql_files:
        rel = f"models/{p.name}"
        files_scanned.append(rel)
        if not NN_ROOT_SQL_RE.match(p.name):
            errors.append(f"`{rel}`: nome inválido para flow-only (esperado prefixo `NN_`, ex.: `01_*.sql`).")
        stems.add(Path(p.name).stem)
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError as ex:
            errors.append(f"`{rel}`: não foi possível ler: {ex}")
            continue

        if ta in ("DBT_BQ", "DATABRICKS"):
            mv = first_materialized_value(body)
            if mv is None:
                errors.append(
                    f"`{rel}`: falta `materialized=` com valor literal entre aspas "
                    f"(ex.: `{{{{ config(materialized='table') }}}}`)."
                )
            elif mv not in allowed_mat:
                errors.append(
                    f"`{rel}`: `materialized='{mv}'` não permitido para TARGET_ARCH={ta} no modo flow-only. "
                    f"Valores permitidos: {', '.join(sorted(allowed_mat))}."
                )

        if _detect_scaffold_local(body):
            errors.append(f"`{rel}`: SQL parece scaffold/stub (ver também `ai_step_gate` heurísticas).")

        # ref() opcional mas útil: stems devem existir como `NN_<stem>.sql` na raiz (best-effort)
        for ref in extract_refs(body):
            # `ref('01_foo')` típico: stem completo do modelo dbt costuma ser o nome do ficheiro sem `.sql`
            if ref in stems:
                continue
            # compat: ref só pelo sufixo após prefixo NN_
            if any(stem_from_nn_filename(s) == ref for s in stems):
                continue
            errors.append(f"`{rel}`: `ref('{ref}')` não mapeia para um ficheiro `NN_*.sql` na raiz de `models/`.")

    ai_errs, ai_warns = validate_ai_flow_report(
        ai_report,
        sql_files,
        require_coverage_block=require_coverage_block,
    )
    errors.extend(ai_errs)
    warnings.extend(ai_warns)

    ok = len(errors) == 0
    out = {
        "egp_key": egp_key,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "files_scanned": files_scanned,
        "ok": ok,
        "report_path": str(report_path),
    }
    if write_report:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_render_report(egp_key, out, models_dir=models_dir, ai_report=ai_report), encoding="utf-8")
        out["infos"].append(f"Relatório escrito: `{report_path}`")
    return out


def evaluate_flow_gate_ok(egp_key: str, *, draft_root: Path, txt_path: Path) -> bool:
    """Avaliação leve (sem escrever relatório) para KPIs em `batch_pipeline`."""
    r = run_flow_gate(egp_key, draft_root=draft_root, txt_path=txt_path, write_report=False)
    return bool(r.get("ok"))


def _render_report(egp_key: str, result: dict, *, models_dir: Path, ai_report: Path) -> str:
    lines: list[str] = []
    lines.append(f"# DRAFT_FLOW_GATE_REPORT — `{egp_key}`")
    lines.append("")
    lines.append("## Contexto")
    lines.append("")
    lines.append(f"- **draft_dir:** `{models_dir.parent}`")
    lines.append(f"- **models_dir:** `{models_dir}`")
    lines.append(f"- **AI report:** `{ai_report}` ({'existe' if ai_report.is_file() else 'em falta'})")
    lines.append("")
    lines.append("## Resultado")
    lines.append("")
    lines.append(f"- **{'OK' if result.get('ok') else 'FALHA'}**")
    lines.append("")
    lines.append("## Erros")
    lines.append("")
    errs = result.get("errors") or []
    if errs:
        lines.extend(f"- {e}" for e in errs)
    else:
        lines.append("- (nenhum)")
    lines.extend(["", "## Avisos", ""])
    warns = result.get("warnings") or []
    if warns:
        lines.extend(f"- {w}" for w in warns)
    else:
        lines.append("- (nenhum)")
    lines.extend(["", "## Info", ""])
    infos = result.get("infos") or []
    if infos:
        lines.extend(f"- {i}" for i in infos)
    else:
        lines.append("- (nenhum)")
    lines.extend(["", "## Ficheiros analisados", ""])
    fs = result.get("files_scanned") or []
    if fs:
        lines.extend(f"- `{f}`" for f in fs)
    else:
        lines.append("- (nenhum)")
    lines.append("")
    lines.append(
        "Checklist IA (referência): `converter/templates/AI_DRAFT_FLOW_VALIDATION_CHECKLIST.md` → "
        "preencher `AI_DRAFT_FLOW_VALIDATION_REPORT.md`."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate determinístico para draft flow-only (models/NN_*.sql).")
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
        "--write-report",
        action="store_true",
        help="Write DRAFT_FLOW_GATE_REPORT.md into draft_models/<egp_key>/",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    txt_path = Path(args.txt_dir) / f"{args.egp_key}.txt"
    r = run_flow_gate(args.egp_key, draft_root=Path(args.draft_root), txt_path=txt_path, write_report=args.write_report)
    if r["errors"]:
        print(f"[draft_flow_gate] FALHA: {len(r['errors'])} erro(s)")
        for e in r["errors"][:40]:
            print(f"  - {e}")
        return 1
    print("[draft_flow_gate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

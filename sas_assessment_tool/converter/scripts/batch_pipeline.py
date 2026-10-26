#!/usr/bin/env python3
"""
Pipeline em lote: extração (egps_extractor) + manifest + draft_gate + checagens + relatório.

Não altera egps_extractor.py — chama extract_code_from_egp para cada .egp.

Uso (pasta converter/):
  python -m scripts.batch_pipeline extract --batch-file registry/egp_keys_batch.txt
  python -m scripts.batch_pipeline draft-gate --batch-file registry/egp_keys_batch.txt
  python -m scripts.batch_pipeline run --batch-file registry/egp_keys_batch.txt
  python -m scripts.batch_pipeline run --batch-file registry/egp_keys_batch.txt --skip-int-mart-yml-pairing  # exceção legado
  python -m scripts.batch_pipeline run --batch-file registry/egp_keys_batch.txt --scaffold-yml  # gera stem.yml mínimos no draft antes do gate
  python -m scripts.batch_pipeline run --batch-file registry/egp_keys_batch.txt --strict --write-csv
  python -m scripts.batch_pipeline checks --batch-file registry/egp_keys_batch.txt
  python -m scripts.batch_pipeline set-step --egp-key MeuProj --step audit_5 --status ok
  python -m scripts.batch_pipeline batch-audit [--refresh-checks] --out registry/BATCH_AUDIT.md

Manifest padrão: registry/batch_manifest.json (schema_version 2, merge por egp_key).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .step_manifest import iter_steps

from .bootstrap_egp_catalog import (
    DEFAULT_REGISTRY_PATH,
    SCRIPT_DIR,
    index_entries,
    load_or_create_catalog,
    resolve_dbt_project_root,
    write_catalog,
)
from .draft_gate import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS, exit_code_for, normalize_target_arch, run_gate
from .draft_flow_gate import (
    evaluate_flow_gate_ok,
    extract_exported_files_from_txt,
    extract_permanent_outputs_from_txt,
    is_flow_only_layout,
)
from .draft_layer_guard import check_draft_three_layers_and_materialization
from .egps_extractor import extract_code_from_egp, infer_business_area_from_egp_path
from .generate_migration_spec import egp_slug
from .model_yml_guard import check_int_mart_yml_pairing, yml_pairing_ok
from .pii_reference import catalog_pii_reference_interno_strict, reference_pii_bundle, scan_migracao_sas_pii
from .pii_sensitive_yml_guard import check_sensitive_column_policy_tags
from .yml_documentation_guard import check_int_mart_yml_documentation, yml_documentation_ok

import yaml

from .apply_staging_map_csv import apply_rows_to_catalog_entry, read_staging_map_csv
from .sandbox_layout import find_converted_sandbox

DEFAULT_RECEIVED = SCRIPT_DIR / "received_egps"
DEFAULT_MANIFEST = SCRIPT_DIR / "registry" / "batch_manifest.json"
SENSITIVE_DATA_TYPES_YAML = SCRIPT_DIR / "registry" / "sensitive_data_types.yaml"
MANIFEST_SCHEMA_VERSION = 2

# Fases pós-extract (alinhadas ao skill orchestrator) — atualizáveis com ``set-step``.
PIPELINE_STEP_KEYS = (
    "spec_1c",
    "draft_2",
    "semantic_gate_2b",
    "governance_3",
    "validation_4",
    "audit_5",
    "handoff_6",
)
PIPELINE_STEP_LABELS = {
    "spec_1c": "1c MIGRATION_SPEC",
    "draft_2": "2 Draft",
    "semantic_gate_2b": "2b Gate semântico",
    "governance_3": "3 Governança",
    "validation_4": "4 Validação / lint",
    "audit_5": "5 Auditoria",
    "handoff_6": "6 Handoff / cópia clone",
}
VALID_PIPELINE_STATUSES = frozenset({"not_started", "pending", "ok", "fail", "skipped", "na"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_pipeline_steps() -> dict:
    return {k: {"status": "not_started", "at": None, "note": ""} for k in PIPELINE_STEP_KEYS}


def migrate_egp_record_inplace(rec: dict) -> None:
    rec.setdefault("batch_checks", {})
    ps = rec.get("pipeline_steps")
    if not isinstance(ps, dict):
        rec["pipeline_steps"] = default_pipeline_steps()
        return
    base = default_pipeline_steps()
    for k, v in base.items():
        if k not in ps or not isinstance(ps[k], dict):
            ps[k] = dict(v)
        else:
            ps[k].setdefault("status", "not_started")
            ps[k].setdefault("at", None)
            ps[k].setdefault("note", "")


def _first_existing_file(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _first_existing_dir(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_dir():
            return p
    return None


def resolve_clone_dest(converter_dir: Path, catalog: dict, entry: dict, egp_key: str) -> Path | None:
    """
    Resolve destino canónico no clone dbt:
      <dbt_root>/<model_path>/workspace/<workspace_subdir>/migracao_sas/<EGP_SLUG>
    """
    try:
        dbt_root = resolve_dbt_project_root(converter_dir, catalog, entry)
    except ValueError:
        return None

    # Garantir que o componente foi clonado/atualizado ANTES de inferir workspace_subdir via `dbt_project.yml`.
    # Único caminho permitido para git: `bootstrap_egp_catalog ensure-repo`.
    if not (dbt_root / "dbt_project.yml").is_file():
        try:
            _ensure_repo_for_egp_key(converter_dir=converter_dir, egp_key=egp_key)
        except Exception:
            # Best-effort: se falhar, seguimos com fallback corp_<AREA>.
            pass

    slug = egp_slug(egp_key)
    area = (entry.get("area") if isinstance(entry, dict) else None) or ""
    workspace_subdir, model_path = resolve_workspace_subdir_and_model_path(dbt_root, area=str(area))
    return (dbt_root / model_path / "workspace" / workspace_subdir / "migracao_sas" / slug).resolve()


def _ensure_repo_for_egp_key(*, converter_dir: Path, egp_key: str) -> None:
    """
    Best-effort: chama `python -m scripts.bootstrap_egp_catalog ensure-repo --egp-key <egp_key>`.
    Não dá commit/push; respeita guardrails.
    """
    cmd = [
        sys.executable,
        "-m",
        "scripts.bootstrap_egp_catalog",
        "ensure-repo",
        "--egp-key",
        egp_key,
        "--catalog",
        str(DEFAULT_REGISTRY_PATH),
        "--area-map",
        str(SCRIPT_DIR / "registry" / "area_componente_dbt.yaml"),
    ]
    subprocess.run(cmd, cwd=str(converter_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _read_dbt_project_model_paths(dbt_root: Path) -> list[Path]:
    """
    Lê `model-paths` do dbt_project.yml (quando existir) e devolve paths relativos ao root.
    Fallback: ['models'].
    """
    yml_path = dbt_root / "dbt_project.yml"
    if not yml_path.is_file():
        return [Path("models")]
    try:
        data = yaml.safe_load(yml_path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return [Path("models")]
    mp = data.get("model-paths")
    if isinstance(mp, list):
        out: list[Path] = []
        for x in mp:
            if isinstance(x, str) and x.strip():
                out.append(Path(x.strip()))
        return out or [Path("models")]
    return [Path("models")]


def _read_dbt_project_name_and_models(dbt_root: Path) -> tuple[str, dict]:
    """
    Best-effort read of dbt_project.yml.
    Returns (project_name, models_dict). If unavailable, returns ("", {}).
    """
    yml_path = dbt_root / "dbt_project.yml"
    if not yml_path.is_file():
        return "", {}
    try:
        data = yaml.safe_load(yml_path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return "", {}
    name = str(data.get("name") or "").strip()
    models = data.get("models") or {}
    return name, (models if isinstance(models, dict) else {})


def _workspace_subdir_from_yaml(dbt_root: Path) -> str:
    """
    YAML wins: derive workspace subdir from:
      models.<project_name>.workspace.<subdir>
    Returns "" if not present.
    """
    project_name, models = _read_dbt_project_name_and_models(dbt_root)
    if not project_name:
        return ""
    proj_cfg = models.get(project_name) if isinstance(models, dict) else None
    if not isinstance(proj_cfg, dict):
        return ""
    ws = proj_cfg.get("workspace")
    if not isinstance(ws, dict) or not ws:
        return ""
    # First key in insertion order (yaml preserves order).
    for k in ws.keys():
        if isinstance(k, str) and k.strip():
            return k.strip()
    return ""


def resolve_workspace_subdir_and_model_path(dbt_root: Path, area: str) -> tuple[str, Path]:
    """
    Resolve qual subpasta vem após `workspace/` dentro de um `model-path` do dbt.

    Regra:
    - YAML wins: se `dbt_project.yml` declarar `models.<project>.workspace.<subpasta>`, usar essa subpasta.
      Para `model-paths`, preferir o primeiro path que contenha `workspace/<subpasta>/` no disco.
    - Preferir `corp_<AREA>` se existir como `.../<model_path>/workspace/corp_<AREA>/`.
    - Senão, se existir qualquer `.../<model_path>/workspace/*/migracao_sas/`, usar a primeira (ordem alfabética).
    - Fallback (se não conseguir inferir): `corp_<AREA>` e model_path=`models`.
    """
    area_slug = (area or "").strip().lower()
    preferred = f"corp_{area_slug}" if area_slug else ""

    model_paths = _read_dbt_project_model_paths(dbt_root)
    yaml_ws = _workspace_subdir_from_yaml(dbt_root)
    if yaml_ws:
        # Choose first model_path where the declared workspace subdir exists.
        for mp in model_paths:
            if (dbt_root / mp / "workspace" / yaml_ws).is_dir():
                return yaml_ws, mp
        # If none exist on disk, still use YAML subdir, but keep deterministic model_path.
        return yaml_ws, (model_paths[0] if model_paths else Path("models"))

    for mp in model_paths:
        ws = dbt_root / mp / "workspace"
        if not ws.is_dir():
            continue
        if preferred and (ws / preferred).is_dir():
            return preferred, mp
        mig_hits = sorted([p for p in ws.glob("*/migracao_sas") if p.is_dir()], key=lambda p: str(p).lower())
        if mig_hits:
            return mig_hits[0].parent.name, mp

    # Fallback: se não der para ler repo/estrutura, usar corp_<AREA> sob models/
    return (preferred or "corp_unknown"), Path("models")


def _txt_target_arch_eff(txt_path: Path) -> str | None:
    """Lê TARGET_ARCH do cabeçalho do .txt (primeiros ~20k chars)."""
    if not txt_path.is_file():
        return None
    chunk = txt_path.read_text(encoding="utf-8", errors="replace")[:20000]
    m = re.search(r"TARGET_ARCH:\s*([^\s\n(]+)", chunk, re.IGNORECASE)
    if not m:
        return None
    return normalize_target_arch(m.group(1))


def find_converted_anywhere(converter_dir: Path, catalog: dict, entry: dict, egp_key: str) -> tuple[str | None, Path | None]:
    """
    Compatibilidade:
    - layout antigo sandbox: converted_egps/dbt/<egp_key> (ou databricks)
    - layout novo sandbox: converted_egps/<YYYY-MM-DD>_<sha>_{dbt|databricks}/<egp_key>
    - layout clone (canónico): converted_egps/<componente>/models/.../migracao_sas/<slug>
    - snapshots locais: converted_egps/dbt_old_*/<egp_key>
    """
    arch, p = find_converted_sandbox(converter_dir, egp_key)
    if p:
        return arch, p

    clone_dest = resolve_clone_dest(converter_dir, catalog, entry, egp_key)
    if clone_dest and clone_dest.is_dir():
        return "dbt", clone_dest

    old_dir = _first_existing_dir(
        [
            converter_dir / "converted_egps" / "dbt_old_2" / egp_key,
            converter_dir / "converted_egps" / "dbt_old_1" / egp_key,
        ]
    )
    if old_dir:
        return "dbt", old_dir

    return None, None


def compute_batch_checks(
    converter_dir: Path,
    egp_key: str,
    draft_root: Path,
    txt_dir: Path,
    catalog: dict,
    entry: dict,
    *,
    skip_yml_doc: bool = False,
    reference_interno_strict_cli: bool = False,
) -> dict:
    txt_path = txt_dir / f"{egp_key}.txt"
    draft_dir = draft_root / egp_key
    txt_arch_eff = _txt_target_arch_eff(txt_path)
    draft_models_dir = draft_dir / "models"
    catalog_layout = (entry.get("draft_layout") or "").strip().lower() if isinstance(entry, dict) else ""
    draft_layout_flow = catalog_layout == "flow" or (not catalog_layout and is_flow_only_layout(draft_models_dir))

    draft_three_layers_ok_flag = True
    draft_staging_model_count = 0
    draft_intermediate_layer_count = 0
    draft_marts_layer_count = 0
    if txt_arch_eff in ("DBT_BQ", "DATABRICKS"):
        ok_layers, _layer_errs, layer_sum = check_draft_three_layers_and_materialization(
            draft_models_dir, txt_arch_eff
        )
        draft_three_layers_ok_flag = ok_layers if not draft_layout_flow else True
        draft_staging_model_count = int(layer_sum.get("staging_model_count", 0))
        draft_intermediate_layer_count = int(layer_sum.get("intermediate_model_count", 0))
        draft_marts_layer_count = int(layer_sum.get("marts_model_count", 0))
    draft_int_mart_model_count = 0
    draft_int_mart_yml_missing_count = 0
    draft_int_mart_yml_missing_sample = ""
    draft_yml_pairing_ok_flag = True
    if draft_models_dir.is_dir():
        dm_missing, dm_total, dm_mc = check_int_mart_yml_pairing(draft_models_dir)
        draft_int_mart_model_count = dm_total
        draft_int_mart_yml_missing_count = dm_mc
        draft_int_mart_yml_missing_sample = " | ".join(dm_missing[:5])
        draft_yml_pairing_ok_flag = yml_pairing_ok(dm_mc)

    # Step-level parity gate (PROC/DATA ↔ models/steps). Independent from 3-layer layout.
    step_gate_ok_flag = True
    missing_step_models_count = 0
    missing_step_models_sample = ""
    if txt_path.is_file() and not draft_layout_flow:
        try:
            steps = iter_steps(txt_path, egp_key)
            expected = [s.stem for s in steps]
            steps_dir = draft_dir / "models" / "steps"
            missing = [f"models/steps/{stem}.sql" for stem in expected if not (steps_dir / f"{stem}.sql").is_file()]
            missing_step_models_count = len(missing)
            missing_step_models_sample = " | ".join(missing[:5])
            step_gate_ok_flag = missing_step_models_count == 0
        except Exception:
            # Conservative: if we can't compute, do not block checks by default.
            step_gate_ok_flag = True
            missing_step_models_count = 0
            missing_step_models_sample = ""

    draft_flow_gate_ok_flag: bool | None
    if draft_layout_flow and draft_models_dir.is_dir():
        draft_flow_gate_ok_flag = evaluate_flow_gate_ok(egp_key, draft_root=draft_root, txt_path=txt_path)
    elif draft_layout_flow:
        draft_flow_gate_ok_flag = False
    else:
        draft_flow_gate_ok_flag = None

    # Coverage gate (flow-only): quando `.txt` declara ambos os campos, exigir registro explícito no relatório IA.
    flow_coverage_ok_flag: bool | None
    if draft_layout_flow and txt_path.is_file():
        perm = extract_permanent_outputs_from_txt(txt_path)
        exp = extract_exported_files_from_txt(txt_path)
        if perm and exp:
            # Reaproveita a regra do `draft_flow_gate`: se `draft_flow_gate_ok` passou, coverage foi validado.
            flow_coverage_ok_flag = bool(draft_flow_gate_ok_flag is True)
        else:
            flow_coverage_ok_flag = True
    elif draft_layout_flow:
        flow_coverage_ok_flag = False
    else:
        flow_coverage_ok_flag = None
    clone_dest = resolve_clone_dest(converter_dir, catalog, entry, egp_key)
    spec_path = _first_existing_file(
        [
            draft_dir / "MIGRATION_SPEC.md",
            (clone_dest / "MIGRATION_SPEC.md") if clone_dest else Path("__missing__"),
            converter_dir / "converted_egps" / "dbt_old_2" / egp_key / "MIGRATION_SPEC.md",
            converter_dir / "converted_egps" / "dbt_old_1" / egp_key / "MIGRATION_SPEC.md",
        ]
    )
    has_contract_yaml = False
    if spec_path and spec_path.is_file():
        try:
            st = spec_path.read_text(encoding="utf-8", errors="replace")
            # Checagem leve: basta existir um code fence yaml com schema_version
            has_contract_yaml = ("```yaml" in st) and ("schema_version:" in st)
        except OSError:
            has_contract_yaml = False
    sql_py_count = 0
    draft_blob = ""
    if draft_dir.is_dir():
        for p in sorted(draft_dir.rglob("*.sql")) + sorted(draft_dir.rglob("*.py")):
            sql_py_count += 1
            try:
                draft_blob += p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    arch, conv_root = find_converted_anywhere(converter_dir, catalog, entry, egp_key)
    sandbox_arch, sandbox_root = find_converted_sandbox(converter_dir, egp_key)
    draft_gate_report = _first_existing_file(
        [
            draft_dir / "DRAFT_GATE_REPORT.md",
            (clone_dest / "DRAFT_GATE_REPORT.md") if clone_dest else Path("__missing__"),
            converter_dir / "converted_egps" / "dbt_old_2" / egp_key / "DRAFT_GATE_REPORT.md",
            converter_dir / "converted_egps" / "dbt_old_1" / egp_key / "DRAFT_GATE_REPORT.md",
        ]
    )
    auditoria_path = ""
    if conv_root and conv_root.is_dir():
        for p in sorted(conv_root.glob("AUDITORIA_*.md")):
            auditoria_path = str(p.resolve())
            break

    # PASSO 3B — verificação de publicação no componente (report persistido no sandbox)
    component_publish_report_path = ""
    component_publish_ok_flag: bool | None = None
    component_publish_applicable = False
    if sandbox_root and sandbox_root.is_dir():
        report = sandbox_root / "COMPONENT_PUBLISH_VERIFICATION_REPORT.md"
        component_publish_report_path = str(report.resolve()) if report.is_file() else str(report)

        # Aplicável quando há output convertido (intermediate/marts) no sandbox e o clone_dest existe.
        sandbox_models = sandbox_root / "models"
        sandbox_has_int = (sandbox_models / "intermediate").is_dir() and any(
            p.is_file() for p in (sandbox_models / "intermediate").rglob("*")
        )
        sandbox_has_marts = (sandbox_models / "marts").is_dir() and any(
            p.is_file() for p in (sandbox_models / "marts").rglob("*")
        )
        component_publish_applicable = bool((sandbox_has_int or sandbox_has_marts) and clone_dest and clone_dest.is_dir())

        if component_publish_applicable:
            if report.is_file():
                try:
                    rt = report.read_text(encoding="utf-8", errors="replace")
                    component_publish_ok_flag = "**Overall:** PASS" in rt
                except OSError:
                    component_publish_ok_flag = False
            else:
                component_publish_ok_flag = False
        else:
            component_publish_ok_flag = None

    int_mart_model_count = 0
    int_mart_yml_missing_count = 0
    int_mart_yml_missing_sample = ""
    yml_pairing_ok_flag = True
    models_dir = (conv_root / "models") if conv_root else None
    if models_dir and models_dir.is_dir():
        missing, total, mc = check_int_mart_yml_pairing(models_dir)
        int_mart_model_count = total
        int_mart_yml_missing_count = mc
        int_mart_yml_missing_sample = " | ".join(missing[:5])
        yml_pairing_ok_flag = yml_pairing_ok(mc)

    dbt_root_ref: Path | None = None
    try:
        dbt_root_ref = resolve_dbt_project_root(converter_dir, catalog, entry)
    except ValueError:
        dbt_root_ref = None
    ref_pii, allowed_ref = reference_pii_bundle(dbt_root_ref)
    mig_pii = scan_migracao_sas_pii(clone_dest, allowed_reference=allowed_ref)

    ri_strict = bool(reference_interno_strict_cli) or catalog_pii_reference_interno_strict(entry, catalog)

    pii_yml_errors: list[str] = []
    pii_sensitive_total = 0
    pii_sensitive_missing = 0
    pii_sensitive_yml_ok_flag = True
    if arch == "dbt" and models_dir and models_dir.is_dir():
        pii_yml_errors, pii_sensitive_total, pii_sensitive_missing = check_sensitive_column_policy_tags(
            models_dir,
            SENSITIVE_DATA_TYPES_YAML,
            allowed_ref if allowed_ref else None,
            reference_interno_strict=ri_strict,
            reference_pii_var_suggestion=str(ref_pii.get("pii_reference_var") or ""),
            allow_confidenciais_without_interno=False,
        )
        pii_sensitive_yml_ok_flag = len(pii_yml_errors) == 0

    yml_doc_errors: list[str] = []
    yml_documentation_ok_flag = True
    if not skip_yml_doc and arch == "dbt" and models_dir and models_dir.is_dir() and int_mart_model_count > 0:
        yml_doc_errors = check_int_mart_yml_documentation(models_dir)
        yml_documentation_ok_flag = yml_documentation_ok(yml_doc_errors)

    return {
        "at": utc_now_iso(),
        "has_txt": txt_path.is_file(),
        "txt_path": str(txt_path.resolve()) if txt_path.is_file() else "",
        "has_draft_dir": draft_dir.is_dir(),
        "has_migration_spec": bool(spec_path and spec_path.is_file()),
        "spec_path": str(spec_path.resolve()) if (spec_path and spec_path.is_file()) else "",
        "spec_has_contract_yaml": bool(has_contract_yaml),
        "draft_sql_py_count": sql_py_count,
        "draft_has_ref": "{{ ref(" in draft_blob or "{{ref(" in draft_blob,
        "has_draft_gate_report": bool(draft_gate_report and draft_gate_report.is_file()),
        "draft_gate_report_path": str(draft_gate_report.resolve())
        if (draft_gate_report and draft_gate_report.is_file())
        else "",
        "converted_target_arch": arch or "",
        "has_converted_sandbox": bool(conv_root and conv_root.is_dir()),
        "converted_root": str(conv_root.resolve()) if conv_root else "",
        "has_auditoria": bool(auditoria_path),
        "auditoria_path": auditoria_path,
        "clone_dest": str(clone_dest) if clone_dest else "",
        "component_publish_report_path": component_publish_report_path,
        "component_publish_applicable": bool(component_publish_applicable),
        "component_publish_ok": component_publish_ok_flag,
        "pii_reference_var": ref_pii.get("pii_reference_var", ""),
        "pii_reference_top2": ref_pii.get("pii_reference_top2", ""),
        "pii_reference_scope": ref_pii.get("pii_reference_scope", ""),
        "pii_reference_04_marts_fallback": ref_pii.get("pii_reference_04_marts_fallback", ""),
        "pii_reference_files_scanned": int(ref_pii.get("pii_reference_files_scanned", 0)),
        "pii_reference_hits": int(ref_pii.get("pii_reference_hits", 0)),
        "pii_migracao_policy_tags_blocks": int(mig_pii.get("pii_migracao_policy_tags_blocks", 0)),
        "pii_migracao_vars": mig_pii.get("pii_migracao_vars", ""),
        "pii_migracao_hits": int(mig_pii.get("pii_migracao_hits", 0)),
        "pii_mismatch": mig_pii.get("pii_mismatch", "na"),
        "pii_reference_interno_strict_applied": "sim" if ri_strict else "não",
        "int_mart_model_count": int_mart_model_count,
        "int_mart_yml_missing_count": int_mart_yml_missing_count,
        "int_mart_yml_missing_sample": int_mart_yml_missing_sample,
        "yml_pairing_ok": yml_pairing_ok_flag,
        "pii_sensitive_yml_ok": pii_sensitive_yml_ok_flag,
        "pii_sensitive_yml_errors": pii_yml_errors[:20],
        "pii_sensitive_yml_error_count": len(pii_yml_errors),
        "pii_sensitive_columns_catalogued": int(pii_sensitive_total),
        "pii_sensitive_columns_policy_gap": int(pii_sensitive_missing),
        "yml_documentation_ok": yml_documentation_ok_flag,
        "yml_documentation_errors": yml_doc_errors[:20],
        "yml_documentation_error_count": len(yml_doc_errors),
        "txt_target_arch": txt_arch_eff or "",
        "draft_layout_mode": "flow" if draft_layout_flow else "layers",
        "draft_flow_gate_ok": draft_flow_gate_ok_flag,
        "flow_coverage_ok": flow_coverage_ok_flag,
        "draft_three_layers_ok": draft_three_layers_ok_flag,
        "draft_staging_model_count": draft_staging_model_count,
        "draft_intermediate_layer_count": draft_intermediate_layer_count,
        "draft_marts_layer_count": draft_marts_layer_count,
        "draft_int_mart_model_count": draft_int_mart_model_count,
        "draft_int_mart_yml_missing_count": draft_int_mart_yml_missing_count,
        "draft_int_mart_yml_missing_sample": draft_int_mart_yml_missing_sample,
        "draft_yml_pairing_ok": draft_yml_pairing_ok_flag,
        "step_gate_ok": step_gate_ok_flag,
        "missing_step_models_count": missing_step_models_count,
        "missing_step_models_sample": missing_step_models_sample,
    }


def read_batch_keys(batch_path: Path) -> list[str]:
    if not batch_path.is_file():
        print(f"Ficheiro inexistente: {batch_path}", file=sys.stderr)
        return []
    keys: list[str] = []
    for ln in batch_path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        keys.append(s)
    return keys


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "egps": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Manifest JSON inválido {path}: {e}", file=sys.stderr)
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "egps": {},
        }
    if not isinstance(data, dict):
        data = {}
    sv = data.get("schema_version", 1)
    try:
        sv_int = int(sv)
    except (TypeError, ValueError):
        sv_int = 1
    data.setdefault("egps", {})
    egps = data.get("egps")
    if not isinstance(egps, dict):
        data["egps"] = {}
        egps = data["egps"]
    if sv_int < MANIFEST_SCHEMA_VERSION:
        for _k, rec in egps.items():
            if isinstance(rec, dict):
                migrate_egp_record_inplace(rec)
        data["schema_version"] = MANIFEST_SCHEMA_VERSION
    else:
        data.setdefault("schema_version", MANIFEST_SCHEMA_VERSION)
        for _k, rec in egps.items():
            if isinstance(rec, dict):
                migrate_egp_record_inplace(rec)
    return data


def save_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now_iso()
    data["schema_version"] = MANIFEST_SCHEMA_VERSION
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_egp_record(data: dict, egp_key: str, componente_dbt: str | None) -> dict:
    egps: dict = data["egps"]
    if egp_key not in egps or not isinstance(egps[egp_key], dict):
        egps[egp_key] = {
            "egp_key": egp_key,
            "componente_dbt": componente_dbt,
            "extract": {},
            "draft_gate": {},
        }
    rec = egps[egp_key]
    if componente_dbt and not rec.get("componente_dbt"):
        rec["componente_dbt"] = componente_dbt
    rec.setdefault("extract", {})
    rec.setdefault("draft_gate", {})
    migrate_egp_record_inplace(rec)
    return rec


def resolve_egp_path(egp_key: str, catalog: dict, received_dir: Path) -> Path | None:
    by_key = index_entries(catalog.get("entries") or [])
    entry = by_key.get(egp_key)
    candidates: list[Path] = []
    if entry and entry.get("egp_file"):
        candidates.append(received_dir / str(entry["egp_file"]).strip())
    candidates.append(received_dir / f"{egp_key}.egp")
    for p in candidates:
        if p.is_file():
            return p
    return None


def normalize_txt_for_egp_key(
    output_dir: Path,
    egp_key: str,
    egp_path: Path,
) -> tuple[Path, str | None]:
    """
    O extrator grava ``<stem_do_egp>.txt``. O pipeline usa ``text_egps/<egp_key>.txt``.
    Se stem != egp_key, copia para egp_key.txt.
    """
    stem = egp_path.stem
    produced = output_dir / f"{stem}.txt"
    target = output_dir / f"{egp_key}.txt"
    if not produced.is_file():
        return target, "ficheiro .txt não gerado após extract"
    if stem == egp_key:
        return produced, None
    shutil.copy2(produced, target)
    return target, None


def cmd_extract(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch_file)
    keys = read_batch_keys(batch_path)
    if not keys:
        return 1 if batch_path.is_file() else 2

    catalog_path = Path(args.catalog)
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog.get("entries") or [])
    received = Path(args.received_dir).resolve()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    staging_map_rows: list | None = None
    if getattr(args, "apply_staging_map_csv", None):
        try:
            staging_map_rows = read_staging_map_csv(Path(args.apply_staging_map_csv))
        except ValueError as e:
            print(f"[extract] apply-staging-map-csv: {e}", file=sys.stderr)
            return 1
    catalog_changed = False

    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    worst = 0

    for egp_key in keys:
        entry = by_key.get(egp_key) or {}
        if staging_map_rows is not None:
            rows_for_key = [r for r in staging_map_rows if getattr(r, "egp_key", None) == egp_key]
            if rows_for_key:
                if not entry:
                    err = (
                        "egp_key não existe no catálogo; rode bootstrap_egp_catalog scan/add antes de usar apply-staging-map-csv."
                    )
                    worst = max(worst, 1)
                    if not args.quiet:
                        print(f"[FAIL extract] {egp_key}: {err}")
                    continue
                if apply_rows_to_catalog_entry(entry, rows_for_key):
                    catalog_changed = True
                    by_key = index_entries(catalog.get("entries") or [])
        comp = entry.get("componente_dbt")
        rec = ensure_egp_record(data, egp_key, comp if isinstance(comp, str) else None)
        egp_path = resolve_egp_path(egp_key, catalog, received)

        if args.resume:
            ex = rec.get("extract") or {}
            txt_path = output_dir / f"{egp_key}.txt"
            if ex.get("status") == "ok" and txt_path.is_file():
                if not args.quiet:
                    print(f"[SKIP extract] {egp_key} (já ok no manifest e .txt existe)")
                continue

        if not egp_path:
            err = f".egp não encontrado em {received} (catálogo egp_file ou {egp_key}.egp)"
            rec["extract"] = {
                "status": "fail",
                "at": utc_now_iso(),
                "egp_path": None,
                "txt_path": str(output_dir / f"{egp_key}.txt"),
                "error": err,
            }
            worst = max(worst, 1)
            if not args.quiet:
                print(f"[FAIL extract] {egp_key}: {err}")
            continue

        catalog_area = (entry.get("area") or "").strip()
        if catalog_area:
            business_area = catalog_area
        else:
            business_area = infer_business_area_from_egp_path(egp_path, received_root=received)
        if not business_area:
            err = (
                "area ausente no catálogo e não inferível a partir do caminho do .egp "
                "(coloque o ficheiro em received_egps/<AREA>/… ou defina o campo area na entrada do catálogo)."
            )
            rec["extract"] = {
                "status": "fail",
                "at": utc_now_iso(),
                "egp_path": str(egp_path),
                "txt_path": str(output_dir / f"{egp_key}.txt"),
                "error": err,
            }
            worst = max(worst, 1)
            if not args.quiet:
                print(f"[FAIL extract] {egp_key}: {err}")
            continue

        try:
            extract_code_from_egp(
                str(egp_path),
                str(output_dir),
                business_area=business_area,
            )
        except Exception as e:
            err = str(e)
            rec["extract"] = {
                "status": "fail",
                "at": utc_now_iso(),
                "egp_path": str(egp_path),
                "txt_path": str(output_dir / f"{egp_key}.txt"),
                "error": err,
            }
            worst = max(worst, 1)
            if not args.quiet:
                print(f"[FAIL extract] {egp_key}: {err}")
            continue

        target_txt, norm_err = normalize_txt_for_egp_key(output_dir, egp_key, egp_path)
        if norm_err:
            rec["extract"] = {
                "status": "fail",
                "at": utc_now_iso(),
                "egp_path": str(egp_path),
                "txt_path": str(target_txt),
                "error": norm_err,
            }
            worst = max(worst, 1)
            if not args.quiet:
                print(f"[FAIL extract] {egp_key}: {norm_err}")
            continue

        rec["extract"] = {
            "status": "ok",
            "at": utc_now_iso(),
            "egp_path": str(egp_path),
            "txt_path": str(target_txt.resolve()),
            "error": None,
        }
        if not args.quiet:
            print(f"[OK extract] {egp_key} -> {target_txt.name}")

        if egp_key in by_key and not catalog_area and business_area:
            row = by_key[egp_key]
            if not (row.get("area") or "").strip():
                row["area"] = business_area
                write_catalog(catalog_path, catalog)

    save_manifest(manifest_path, data)
    if catalog_changed:
        write_catalog(catalog_path, catalog)
    if args.write_csv:
        write_manifest_csv(data, Path(args.csv_out))
    return worst


def cmd_draft_gate(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch_file)
    keys = read_batch_keys(batch_path)
    if not keys:
        return 1 if batch_path.is_file() else 2

    catalog_path = Path(args.catalog)
    draft_root = Path(args.draft_root)
    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog.get("entries") or [])

    worst = 0
    for egp_key in keys:
        entry = by_key.get(egp_key) or {}
        comp = entry.get("componente_dbt")
        rec = ensure_egp_record(data, egp_key, comp if isinstance(comp, str) else None)

        txt = Path(args.txt_dir) / f"{egp_key}.txt" if args.txt_dir else (DEFAULT_TEXT_EGPS / f"{egp_key}.txt")

        r = run_gate(
            egp_key,
            catalog_path=catalog_path,
            draft_root=draft_root,
            txt_path=txt,
            strict=False,
            write_report=args.write_report,
            parity_tables_all_arch=args.parity_tables_all_arch,
            allow_legacy_spec=getattr(args, "allow_legacy_spec", False),
            require_filtros_aplicados=getattr(args, "require_filtros_aplicados", False),
            skip_pii_yml=getattr(args, "skip_pii_yml", False),
            skip_yml_doc=getattr(args, "skip_yml_doc", False),
            skip_int_mart_yml_pairing=getattr(args, "skip_int_mart_yml_pairing", False),
            reference_interno_strict_cli=getattr(args, "reference_interno_strict", False),
        )
        code = exit_code_for(r, args.strict)
        worst = max(worst, code)

        st = "fail" if r["errors"] else ("warn" if r["warnings"] else "ok")
        rec["draft_gate"] = {
            "status": st,
            "at": utc_now_iso(),
            "exit_code": code,
            "errors": list(r["errors"]),
            "warnings": list(r["warnings"]),
            "files_scanned_count": len(r.get("files_scanned") or []),
        }
        if not args.quiet and not args.json:
            tag = "FAIL" if r["errors"] else ("WARN" if r["warnings"] else "OK")
            print(f"[{tag}] {egp_key}")

    save_manifest(manifest_path, data)
    if args.write_csv:
        write_manifest_csv(data, Path(args.csv_out))
    if args.json:
        print(json.dumps(data["egps"], ensure_ascii=False, indent=2))
    return worst


def cmd_run(args: argparse.Namespace) -> int:
    """extract + draft_gate; reutiliza os mesmos argumentos de ficheiro."""
    ex = argparse.Namespace(
        batch_file=args.batch_file,
        catalog=args.catalog,
        received_dir=args.received_dir,
        output_dir=args.output_dir,
        manifest=args.manifest,
        resume=args.resume_extract,
        quiet=args.quiet,
        write_csv=False,
        csv_out=args.csv_out,
    )
    code_e = cmd_extract(ex)
    if getattr(args, "scaffold_yml", False):
        from scaffold_int_mart_yml import scaffold_draft_models

        batch_path = Path(args.batch_file)
        draft_root = Path(args.draft_root)
        for egp_key in read_batch_keys(batch_path):
            scaffold_draft_models(draft_root / egp_key / "models", egp_key=egp_key)
    dg = argparse.Namespace(
        batch_file=args.batch_file,
        catalog=args.catalog,
        draft_root=args.draft_root,
        manifest=args.manifest,
        strict=args.strict,
        write_report=args.write_report,
        txt_dir=args.txt_dir,
        quiet=args.quiet,
        json=args.json,
        write_csv=args.write_csv,
        csv_out=args.csv_out,
        parity_tables_all_arch=getattr(args, "parity_tables_all_arch", False),
        allow_legacy_spec=getattr(args, "allow_legacy_spec", False),
        require_filtros_aplicados=getattr(args, "require_filtros_aplicados", False),
        skip_pii_yml=getattr(args, "skip_pii_yml", False),
        skip_yml_doc=getattr(args, "skip_yml_doc", False),
        skip_int_mart_yml_pairing=getattr(args, "skip_int_mart_yml_pairing", False),
        reference_interno_strict=getattr(args, "reference_interno_strict", False),
    )
    code_d = cmd_draft_gate(dg)
    return max(code_e, code_d)


def cmd_checks(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch_file)
    keys = read_batch_keys(batch_path)
    if not keys:
        return 1 if batch_path.is_file() else 2

    catalog = load_or_create_catalog(Path(args.catalog))
    by_key = index_entries(catalog.get("entries") or [])
    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    draft_root = Path(args.draft_root)
    txt_dir = Path(args.txt_dir) if args.txt_dir else DEFAULT_TEXT_EGPS
    converter_dir = SCRIPT_DIR
    worst = 0

    for egp_key in keys:
        entry = by_key.get(egp_key) or {}
        comp = entry.get("componente_dbt")
        rec = ensure_egp_record(data, egp_key, comp if isinstance(comp, str) else None)
        rec["batch_checks"] = compute_batch_checks(
            converter_dir=converter_dir,
            egp_key=egp_key,
            draft_root=draft_root,
            txt_dir=txt_dir,
            catalog=catalog,
            entry=entry,
            skip_yml_doc=getattr(args, "skip_yml_doc", False),
            reference_interno_strict_cli=getattr(args, "reference_interno_strict", False),
        )
        if getattr(args, "strict", False):
            bc = rec["batch_checks"]
            ex = rec.get("extract") or {}
            flow_mode = str(bc.get("draft_layout_mode") or "") == "flow"
            if ex.get("status") == "ok" and not bc.get("has_migration_spec"):
                worst = max(worst, 1)
            if ex.get("status") == "ok" and bc.get("has_migration_spec") and bc.get("draft_sql_py_count", 0) == 0:
                worst = max(worst, 1)
            if ex.get("status") == "ok" and bc.get("has_migration_spec") and not bc.get("spec_has_contract_yaml"):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_migration_spec")
                and str(bc.get("txt_target_arch") or "") == "DBT_BQ"
                and int(bc.get("draft_int_mart_model_count") or 0) > 0
                and not bc.get("draft_yml_pairing_ok", True)
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_migration_spec")
                and (not flow_mode)
                and str(bc.get("txt_target_arch") or "") in ("DBT_BQ", "DATABRICKS")
                and int(bc.get("draft_sql_py_count") or 0) > 0
                and not bc.get("draft_three_layers_ok", True)
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_migration_spec")
                and flow_mode
                and int(bc.get("draft_sql_py_count") or 0) > 0
                and bc.get("draft_flow_gate_ok") is not True
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_migration_spec")
                and flow_mode
                and int(bc.get("draft_sql_py_count") or 0) > 0
                and bc.get("flow_coverage_ok") is not True
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_converted_sandbox")
                and int(bc.get("int_mart_model_count") or 0) > 0
                and not bc.get("yml_pairing_ok", True)
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_converted_sandbox")
                and bc.get("converted_target_arch") == "dbt"
                and int(bc.get("int_mart_model_count") or 0) > 0
                and not bc.get("pii_sensitive_yml_ok", True)
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("has_converted_sandbox")
                and bc.get("converted_target_arch") == "dbt"
                and int(bc.get("int_mart_model_count") or 0) > 0
                and not bc.get("yml_documentation_ok", True)
            ):
                worst = max(worst, 1)
            if (
                ex.get("status") == "ok"
                and bc.get("component_publish_applicable") is True
                and bc.get("component_publish_ok") is not True
            ):
                worst = max(worst, 1)
            if bc.get("has_txt") and (not flow_mode) and not bc.get("step_gate_ok", True):
                worst = max(worst, 1)
        if not args.quiet:
            bc = rec["batch_checks"]
            yml_s = (
                "na"
                if int(bc.get("int_mart_model_count") or 0) == 0
                else ("ok" if bc.get("yml_pairing_ok") else f"falta({bc.get('int_mart_yml_missing_count', 0)})")
            )
            draft_yml_s = (
                "na"
                if int(bc.get("draft_int_mart_model_count") or 0) == 0
                else ("ok" if bc.get("draft_yml_pairing_ok") else f"falta({bc.get('draft_int_mart_yml_missing_count', 0)})")
            )
            ta_chk = str(bc.get("txt_target_arch") or "")
            flow_mode = str(bc.get("draft_layout_mode") or "") == "flow"
            if ta_chk not in ("DBT_BQ", "DATABRICKS"):
                draft_3l_s = "na"
            elif flow_mode:
                draft_3l_s = "na(flow)"
            else:
                draft_3l_s = "ok" if bc.get("draft_three_layers_ok", True) else "falha"
            pii_yml_s = "na"
            yml_doc_s = "na"
            if int(bc.get("int_mart_model_count") or 0) > 0 and bc.get("converted_target_arch") == "dbt":
                yml_doc_s = "ok" if bc.get("yml_documentation_ok", True) else f"falha({bc.get('yml_documentation_error_count', 0)})"
            if bc.get("converted_target_arch") == "dbt" and int(bc.get("int_mart_model_count") or 0) > 0:
                pii_yml_s = "ok" if bc.get("pii_sensitive_yml_ok", True) else f"falha({bc.get('pii_sensitive_yml_error_count', 0)})"
            if flow_mode:
                dfg = bc.get("draft_flow_gate_ok")
                step_gate_s = "na(flow)"
                draft_flow_s = "ok" if dfg is True else "falha"
            else:
                step_gate_s = "ok" if bc.get("step_gate_ok", True) else f"falha({bc.get('missing_step_models_count', 0)})"
                draft_flow_s = "na"
            print(
                f"[checks] {egp_key}: txt={bc['has_txt']} spec={bc['has_migration_spec']} contract={bc.get('spec_has_contract_yaml')} "
                f"draft_files={bc['draft_sql_py_count']} draft_3layer={draft_3l_s} draft_flow_gate={draft_flow_s} converted={bc['has_converted_sandbox']} "
                f"auditoria={bc['has_auditoria']} step_gate={step_gate_s} draft_int_yml={draft_yml_s} int_mart_yml={yml_s} yml_doc={yml_doc_s} pii_yml={pii_yml_s}"
            )

    save_manifest(manifest_path, data)
    if args.write_csv:
        write_manifest_csv(data, Path(args.csv_out))
    return worst


def cmd_set_step(args: argparse.Namespace) -> int:
    egp_key = args.egp_key.strip()
    step = args.step.strip()
    status = args.status.strip()
    if step not in PIPELINE_STEP_KEYS:
        print(f"Step inválido: {step}. Use: {', '.join(PIPELINE_STEP_KEYS)}", file=sys.stderr)
        return 2
    if status not in VALID_PIPELINE_STATUSES:
        print(f"Status inválido: {status}. Use: {', '.join(sorted(VALID_PIPELINE_STATUSES))}", file=sys.stderr)
        return 2

    catalog = load_or_create_catalog(Path(args.catalog))
    by_key = index_entries(catalog.get("entries") or [])
    entry = by_key.get(egp_key) or {}
    comp = entry.get("componente_dbt")

    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    rec = ensure_egp_record(data, egp_key, comp if isinstance(comp, str) else None)
    note = (args.note or "").strip()
    rec["pipeline_steps"][step] = {
        "status": status,
        "at": utc_now_iso(),
        "note": note,
    }
    save_manifest(manifest_path, data)
    if not args.quiet:
        print(f"[set-step] {egp_key} {step} -> {status}")
    return 0


def _md_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def cmd_batch_audit(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch_file)
    keys = read_batch_keys(batch_path)
    if not keys:
        return 1 if batch_path.is_file() else 2

    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    catalog = load_or_create_catalog(Path(args.catalog))
    by_key = index_entries(catalog.get("entries") or [])

    if args.refresh_checks:
        draft_root = Path(args.draft_root)
        txt_dir = Path(args.txt_dir) if args.txt_dir else DEFAULT_TEXT_EGPS
        for egp_key in keys:
            entry = by_key.get(egp_key) or {}
            comp = entry.get("componente_dbt")
            rec = ensure_egp_record(data, egp_key, comp if isinstance(comp, str) else None)
            rec["batch_checks"] = compute_batch_checks(
                converter_dir=SCRIPT_DIR,
                egp_key=egp_key,
                draft_root=draft_root,
                txt_dir=txt_dir,
                catalog=catalog,
                entry=entry,
                skip_yml_doc=getattr(args, "skip_yml_doc", False),
                reference_interno_strict_cli=getattr(args, "reference_interno_strict", False),
            )
        save_manifest(manifest_path, data)

    out_path = Path(args.out)
    lines: list[str] = [
        "# BATCH_AUDIT",
        "",
        f"Gerado em `{utc_now_iso()}` a partir do manifest `{manifest_path.as_posix()}` e lista `{batch_path.as_posix()}`.",
        "Regenerar: `python -m scripts.batch_pipeline batch-audit -b <batch-file> [--refresh-checks]`.",
        "",
        "| egp_key | componente_dbt | extract | draft_gate | txt | spec | draft # | ref | converted | int_mart_yml | yml_doc | pii_yml | auditoria | pipeline (resumo) | pii_ref | pii_migracao | pii_mismatch |",
        "|---------|----------------|---------|------------|-----|------|---------|-----|-----------|--------------|---------|---------|-----------|-------------------|---------|--------------|--------------|",
    ]

    for egp_key in keys:
        egps = data.get("egps") or {}
        rec = egps.get(egp_key) if isinstance(egps.get(egp_key), dict) else {}
        if not rec:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(egp_key),
                        "",
                        "(sem registo no manifest)",
                        *([""] * 14),
                    ]
                )
                + " |"
            )
            continue
        comp = _md_cell(str(rec.get("componente_dbt") or ""))
        ex = rec.get("extract") or {}
        dg = rec.get("draft_gate") or {}
        bc = rec.get("batch_checks") or {}
        exs = _md_cell(str(ex.get("status", "")))
        dgs_raw = str(dg.get("status", "")).strip()
        if not dgs_raw:
            if bc.get("has_draft_gate_report"):
                dgs_raw = "report"
            else:
                dgs_raw = "na"
        dgs = _md_cell(dgs_raw)
        txt_ok = "sim" if bc.get("has_txt") else "não"
        spec_ok = "sim" if bc.get("has_migration_spec") else "não"
        dcnt = str(bc.get("draft_sql_py_count", ""))
        ref_ok = "sim" if bc.get("draft_has_ref") else "não"
        conv_ok = "sim" if bc.get("has_converted_sandbox") else "não"
        imc = int(bc.get("int_mart_model_count") or 0)
        if imc == 0:
            int_yml = "na"
            yml_doc_cell = "na"
            pii_yml_cell = "na"
        else:
            int_yml = "sim" if bc.get("yml_pairing_ok") else "não"
            if bc.get("converted_target_arch") != "dbt":
                yml_doc_cell = "na"
                pii_yml_cell = "na"
            else:
                yml_doc_cell = "sim" if bc.get("yml_documentation_ok", True) else "não"
                pii_yml_cell = "sim" if bc.get("pii_sensitive_yml_ok", True) else "não"
        aud = _md_cell(bc.get("auditoria_path") or ("sim" if bc.get("has_auditoria") else "não"))
        ps = rec.get("pipeline_steps") or {}
        summary_parts: list[str] = []
        for k in PIPELINE_STEP_KEYS:
            st = (ps.get(k) or {}).get("status", "")
            if st and st != "not_started":
                short = PIPELINE_STEP_LABELS.get(k, k).split()[0]
                summary_parts.append(f"{short}:{st}")
        pipe_s = _md_cell(", ".join(summary_parts) if summary_parts else "—")
        pii_ref_s = _md_cell(str(bc.get("pii_reference_top2") or bc.get("pii_reference_var") or "—"))
        mig_bits = (
            f"policy_tags={bc.get('pii_migracao_policy_tags_blocks', 0)}; "
            f"pii_hits={bc.get('pii_migracao_hits', 0)}; "
            f"{bc.get('pii_migracao_vars') or '—'}"
        )
        pii_mig_s = _md_cell(mig_bits[:200])
        pii_mm = _md_cell(str(bc.get("pii_mismatch", "na")))

        lines.append(
            f"| {_md_cell(egp_key)} | {comp} | {exs} | {dgs} | {txt_ok} | {spec_ok} | {dcnt} | {ref_ok} | {conv_ok} | {int_yml} | {yml_doc_cell} | {pii_yml_cell} | {aud} | {pipe_s} | {pii_ref_s} | {pii_mig_s} | {pii_mm} |"
        )

    lines.append("")
    lines.append("## Legenda `pipeline`")
    lines.append("")
    for k in PIPELINE_STEP_KEYS:
        lines.append(f"- `{k}` — {PIPELINE_STEP_LABELS[k]}")
    lines.append("")
    lines.append("Atualizar estados: `python -m scripts.batch_pipeline set-step --egp-key <key> --step audit_5 --status ok`")
    lines.append("")
    lines.append("## Coluna `int_mart_yml`")
    lines.append("")
    lines.append(
        "- **`na`:** sem modelos `intermediate/` ou `marts/` (`.sql`/`.py`) na pasta convertida, ou sem `models/`."
    )
    lines.append(
        "- **`sim`:** cada ficheiro nessas pastas tem `stem.yml` irmão no mesmo diretório (paridade mínima pós-governança)."
    )
    lines.append(
        "- **`não`:** falta pelo menos um `.yml` irmão — ver `batch_checks.int_mart_yml_missing_sample` no manifest."
    )
    lines.append("")
    lines.append("## KPI paridade YAML (draft vs convertido)")
    lines.append("")
    lines.append(
        "- **`draft_yml_pairing_ok` / `check_draft_yml_pairing_ok` (CSV):** paridade `stem.yml` ↔ `.sql`/`.py` "
        "em `draft_models/<egp>/models/intermediate` e `.../marts`. Com `TARGET_ARCH: DBT_BQ` no `.txt`, "
        "`python -m scripts.batch_pipeline checks --strict` falha se houver modelos int/mart no draft sem irmão `.yml` "
        "(alinhado ao `draft_gate` sem `--skip-int-mart-yml-pairing`)."
    )
    lines.append(
        "- **`draft_layout_mode` / `check_draft_layout_mode` (CSV):** `flow` quando o draft está em modo **flow-only** "
        "(`draft_models/<egp>/models/NN_*.sql` sem as 3 pastas canónicas) **ou** quando o catálogo define `draft_layout: flow`; "
        "caso contrário `layers`."
    )
    lines.append(
        "- **`draft_flow_gate_ok` / `check_draft_flow_gate_ok` (CSV):** no modo **`flow`**, validações determinísticas "
        "equivalentes a `python -m scripts.draft_flow_gate` (inclui presença/estrutura mínima do relatório IA). "
        "`checks --strict` falha se `draft_flow_gate_ok` for `no` quando há ficheiros no draft."
    )
    lines.append(
        "- **`flow_coverage_ok` / `check_flow_coverage_ok` (CSV):** no modo **`flow`**, quando o cabeçalho do `.txt` "
        "declara **`PERMANENT OUTPUTS (Target Marts)`** e **`EXPORTED FILES (Artifacts)`** (ambos não-`(none)`), "
        "exige que o relatório IA registre explicitamente os dois em `## Coverage` (regra do `draft_flow_gate`). "
        "`checks --strict` falha se `flow_coverage_ok` for `no` quando há ficheiros no draft."
    )
    lines.append(
        "- **`draft_three_layers_ok` / `check_draft_three_layers_ok` (CSV):** no modo **`layers`**, com `TARGET_ARCH: DBT_BQ` ou "
        "`DATABRICKS` no `.txt` e ficheiros no draft, exige `models/staging/`, `intermediate/` e `marts/` com "
        "≥1 modelo cada e `materialized='…'` literal permitido por camada (`draft_layer_guard.py` / `draft_gate`). "
        "`checks --strict` falha se `draft_three_layers_ok` for falso."
    )
    lines.append(
        "- **`step_gate_ok` / `check_step_gate_ok` (CSV):** no modo **`layers`**, paridade determinística entre passos SAS (PROC/DATA) "
        "extraídos de `text_egps/<egp>.txt` e ficheiros em `draft_models/<egp>/models/steps/*.sql`. "
        "`checks --strict` falha se `step_gate_ok` for falso. No modo **`flow`**, este KPI fica **não aplicável** (não bloqueia)."
    )
    lines.append(
        "- **`yml_pairing_ok` / coluna `int_mart_yml`:** mesmo critério sobre a pasta **convertida** (sandbox/clone), "
        "útil após governança e materialização."
    )
    lines.append(
        "- **Série por EGP:** tratar cada linha do manifesto como um pipeline independente; só avançar PASSO 3+ "
        "quando o gate mecânico do draft (`draft_gate` em modo **layers**, ou `draft_flow_gate` em modo **flow**) "
        "e `checks --strict` estiverem verdes para esse `egp_key`."
    )
    lines.append("")
    lines.append("## Coluna `yml_doc`")
    lines.append("")
    lines.append(
        "- **`na`:** não é `dbt`, ou sem modelos `intermediate/`/`marts/` na saída convertida — guardrail de documentação YAML não aplicável."
    )
    lines.append(
        "- **`sim`:** cada `stem.yml` existente cumpre regras mínimas (`columns` não vazio, `meta.cron`, descrições; campo `yml_documentation_ok` em `batch_checks`)."
    )
    lines.append(
        "- **`não`:** ver `yml_documentation_errors` / `yml_documentation_error_count` em `batch_checks` no manifest."
    )
    lines.append("")
    lines.append("## Coluna `pii_yml`")
    lines.append("")
    lines.append(
        "- **`na`:** não é `dbt` ou sem modelos `intermediate/`/`marts/` na saída convertida — guardrail de colunas sensíveis não aplicável."
    )
    lines.append(
        "- **`sim`:** colunas listadas nos `stem.yml` que casam com `registry/sensitive_data_types.yaml` têm `policy_tags` e variável aceite (ver `batch_checks.pii_sensitive_yml_ok`)."
    )
    lines.append(
        "- **`não`:** ver `batch_checks.pii_sensitive_yml_errors` / `pii_sensitive_yml_error_count` no manifest."
    )
    lines.append("")
    lines.append("## Colunas PII (resumo)")
    lines.append("")
    lines.append(
        "- **`pii_ref`:** top-2 de `PII_INTERNO_*` inferido primeiro dos YAMLs em `models/**/04_marts/**/*.yml` "
        "(excluindo `migracao_sas`); se não houver ocorrências, **fallback** para todo `models/**` exceto "
        "`migracao_sas` (ver `batch_checks.pii_reference_scope` e `pii_reference_04_marts_fallback`)."
    )
    lines.append(
        "- **`pii_migracao`:** contagens e variáveis `PII_INTERNO_*` encontradas nos YAML sob `.../migracao_sas/<slug>/` (saída da conversão)."
    )
    lines.append(
        "- **`pii_mismatch`:** `sim` se as vars em `migracao_sas` não forem subconjunto do top-2 de referência; `na` se não aplicável."
    )
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    if not args.quiet:
        print(f"[batch-audit] escrito {out_path.resolve()}")
    return 0


def write_manifest_csv(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    egps = data.get("egps") or {}
    for k in sorted(egps.keys()):
        rec = egps[k] if isinstance(egps[k], dict) else {}
        ex = rec.get("extract") or {}
        dg = rec.get("draft_gate") or {}
        bc = rec.get("batch_checks") or {}
        rows.append(
            {
                "egp_key": k,
                "componente_dbt": rec.get("componente_dbt") or "",
                "extract_status": ex.get("status", ""),
                "extract_error": (ex.get("error") or "") if isinstance(ex.get("error"), str) else "",
                "txt_path": ex.get("txt_path", ""),
                "draft_gate_status": dg.get("status", ""),
                "draft_gate_exit_code": str(dg.get("exit_code", "")),
                "draft_gate_errors": " | ".join(dg.get("errors") or []) if isinstance(dg.get("errors"), list) else "",
                "draft_gate_warnings": " | ".join(dg.get("warnings") or [])
                if isinstance(dg.get("warnings"), list)
                else "",
                "check_has_txt": "yes" if bc.get("has_txt") else "no",
                "check_has_spec": "yes" if bc.get("has_migration_spec") else "no",
                "check_draft_sql_py_count": str(bc.get("draft_sql_py_count", "")),
                "check_draft_has_ref": "yes" if bc.get("draft_has_ref") else "no",
                "check_converted_arch": bc.get("converted_target_arch", ""),
                "check_has_auditoria": "yes" if bc.get("has_auditoria") else "no",
                "check_auditoria_path": bc.get("auditoria_path", ""),
                "check_component_publish_ok": (
                    "yes"
                    if bc.get("component_publish_ok") is True
                    else ("no" if bc.get("component_publish_ok") is False else "")
                ),
                "check_component_publish_report_path": str(bc.get("component_publish_report_path", "")),
                "check_pii_reference_var": str(bc.get("pii_reference_var", "")),
                "check_pii_reference_top2": str(bc.get("pii_reference_top2", "")),
                "check_pii_reference_scope": str(bc.get("pii_reference_scope", "")),
                "check_pii_reference_04_marts_fallback": str(bc.get("pii_reference_04_marts_fallback", "")),
                "check_pii_reference_files": str(bc.get("pii_reference_files_scanned", "")),
                "check_pii_reference_hits": str(bc.get("pii_reference_hits", "")),
                "check_pii_migracao_policy_tags_blocks": str(bc.get("pii_migracao_policy_tags_blocks", "")),
                "check_pii_migracao_hits": str(bc.get("pii_migracao_hits", "")),
                "check_pii_migracao_vars": str(bc.get("pii_migracao_vars", "")),
                "check_pii_mismatch": str(bc.get("pii_mismatch", "")),
                "check_int_mart_model_count": str(bc.get("int_mart_model_count", "")),
                "check_int_mart_yml_missing_count": str(bc.get("int_mart_yml_missing_count", "")),
                "check_yml_pairing_ok": "yes" if bc.get("yml_pairing_ok") else "no",
                "check_int_mart_yml_missing_sample": bc.get("int_mart_yml_missing_sample", ""),
                "check_txt_target_arch": str(bc.get("txt_target_arch", "")),
                "check_draft_layout_mode": str(bc.get("draft_layout_mode", "")),
                "check_draft_flow_gate_ok": (
                    "yes"
                    if bc.get("draft_flow_gate_ok") is True
                    else ("no" if bc.get("draft_flow_gate_ok") is False else "")
                ),
                "check_flow_coverage_ok": (
                    "yes"
                    if bc.get("flow_coverage_ok") is True
                    else ("no" if bc.get("flow_coverage_ok") is False else "")
                ),
                "check_draft_three_layers_ok": "yes" if bc.get("draft_three_layers_ok", True) else "no",
                "check_draft_staging_model_count": str(bc.get("draft_staging_model_count", "")),
                "check_draft_intermediate_layer_count": str(bc.get("draft_intermediate_layer_count", "")),
                "check_draft_marts_layer_count": str(bc.get("draft_marts_layer_count", "")),
                "check_draft_int_mart_model_count": str(bc.get("draft_int_mart_model_count", "")),
                "check_draft_yml_pairing_ok": "yes" if bc.get("draft_yml_pairing_ok", True) else "no",
                "check_draft_int_mart_yml_missing_count": str(bc.get("draft_int_mart_yml_missing_count", "")),
                "check_draft_int_mart_yml_missing_sample": bc.get("draft_int_mart_yml_missing_sample", ""),
                "check_step_gate_ok": "yes" if bc.get("step_gate_ok", True) else "no",
                "check_missing_step_models_count": str(bc.get("missing_step_models_count", "")),
                "check_missing_step_models_sample": bc.get("missing_step_models_sample", ""),
                "check_pii_sensitive_yml_ok": "yes" if bc.get("pii_sensitive_yml_ok", True) else "no",
                "check_pii_sensitive_yml_error_count": str(bc.get("pii_sensitive_yml_error_count", "")),
                "check_pii_sensitive_columns_catalogued": str(bc.get("pii_sensitive_columns_catalogued", "")),
                "check_pii_sensitive_columns_policy_gap": str(bc.get("pii_sensitive_columns_policy_gap", "")),
                "check_pii_sensitive_yml_errors_sample": " | ".join(bc.get("pii_sensitive_yml_errors") or [])[:500],
                "check_yml_documentation_ok": "yes" if bc.get("yml_documentation_ok", True) else "no",
                "check_yml_documentation_error_count": str(bc.get("yml_documentation_error_count", "")),
                "check_yml_documentation_errors_sample": " | ".join(bc.get("yml_documentation_errors") or [])[:500],
            }
        )
    fieldnames = [
        "egp_key",
        "componente_dbt",
        "extract_status",
        "extract_error",
        "txt_path",
        "draft_gate_status",
        "draft_gate_exit_code",
        "draft_gate_errors",
        "draft_gate_warnings",
        "check_has_txt",
        "check_has_spec",
        "check_draft_sql_py_count",
        "check_draft_has_ref",
        "check_converted_arch",
        "check_has_auditoria",
        "check_auditoria_path",
        "check_pii_reference_var",
        "check_pii_reference_top2",
        "check_pii_reference_scope",
        "check_pii_reference_04_marts_fallback",
        "check_pii_reference_files",
        "check_pii_reference_hits",
        "check_pii_migracao_policy_tags_blocks",
        "check_pii_migracao_hits",
        "check_pii_migracao_vars",
        "check_pii_mismatch",
        "check_int_mart_model_count",
        "check_int_mart_yml_missing_count",
        "check_yml_pairing_ok",
        "check_int_mart_yml_missing_sample",
        "check_txt_target_arch",
        "check_draft_layout_mode",
        "check_draft_flow_gate_ok",
        "check_draft_three_layers_ok",
        "check_draft_staging_model_count",
        "check_draft_intermediate_layer_count",
        "check_draft_marts_layer_count",
        "check_draft_int_mart_model_count",
        "check_draft_yml_pairing_ok",
        "check_draft_int_mart_yml_missing_count",
        "check_draft_int_mart_yml_missing_sample",
        "check_step_gate_ok",
        "check_missing_step_models_count",
        "check_missing_step_models_sample",
        "check_pii_sensitive_yml_ok",
        "check_pii_sensitive_yml_error_count",
        "check_pii_sensitive_columns_catalogued",
        "check_pii_sensitive_columns_policy_gap",
        "check_pii_sensitive_yml_errors_sample",
        "check_yml_documentation_ok",
        "check_yml_documentation_error_count",
        "check_yml_documentation_errors_sample",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Lote: extract + manifest + draft_gate")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--batch-file", "-b", required=True, metavar="PATH", help="Um egp_key por linha (# comentário)")
    common.add_argument("--catalog", default=str(DEFAULT_REGISTRY_PATH), help="egp_catalog.yaml")
    common.add_argument(
        "--manifest",
        "-m",
        default=str(DEFAULT_MANIFEST),
        help="JSON de manifest (merge por egp_key)",
    )
    common.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Menos linhas do batch_pipeline (o egps_extractor continua a imprimir em extract)",
    )
    common.add_argument("--write-csv", action="store_true", help="Grava CSV resumo (após operação)")
    common.add_argument(
        "--csv-out",
        default=str(SCRIPT_DIR / "registry" / "batch_manifest.csv"),
        metavar="PATH",
        help="Destino do CSV quando --write-csv",
    )
    common.add_argument(
        "--reference-interno-strict",
        action="store_true",
        help="PII (dbt): força modo estrito — exige PII_INTERNO_* de referência para tipos em STRICT_REFERENCE_ENTRY_IDS "
        "(além de `pii_reference_interno_strict` no catálogo). Ver `pii_sensitive_yml_guard.py`.",
    )

    px = sub.add_parser("extract", parents=[common], help="Só extração (egps_extractor) + manifest.extract")
    px.add_argument("--received-dir", default=str(DEFAULT_RECEIVED), help="Pasta com .egp")
    px.add_argument("--output-dir", default=str(DEFAULT_TEXT_EGPS), help="Saída .txt (text_egps)")
    px.add_argument(
        "--resume",
        action="store_true",
        help="Ignorar EGPs com extract.status=ok e text_egps/<key>.txt existente",
    )
    px.add_argument(
        "--apply-staging-map-csv",
        default=None,
        metavar="PATH",
        help="Aplica um CSV (egp_key,sas_table,bq_fqtn) no catálogo ANTES de extrair. "
        "Somente para egp_key já existente no catálogo (Opção A).",
    )
    px.set_defaults(func=cmd_extract)

    pd = sub.add_parser("draft-gate", parents=[common], help="Só draft_gate + manifest.draft_gate")
    pd.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    pd.add_argument("--strict", action="store_true", help="avisos também => exit 1")
    pd.add_argument("--write-report", action="store_true")
    pd.add_argument(
        "--txt-dir",
        default=None,
        help="Pasta dos .txt (default: text_egps do projeto)",
    )
    pd.add_argument("--json", action="store_true", help="Imprime egps{} JSON no stdout")
    pd.add_argument(
        "--parity-tables-all-arch",
        action="store_true",
        help="Repassa ao draft_gate: heurística DETECTED_TABLES_* também em DATABRICKS",
    )
    pd.add_argument(
        "--allow-legacy-spec",
        action="store_true",
        help="Repassa ao draft_gate: permite MIGRATION_SPEC.md sem contrato YAML (modo legado)",
    )
    pd.add_argument(
        "--require-filtros-aplicados",
        action="store_true",
        help="Repassa ao draft_gate: se houver FILTERS_ORIGINAIS, exige _FILTROS_APLICADOS.md (erro se faltar)",
    )
    pd.add_argument(
        "--skip-pii-yml",
        action="store_true",
        help="Repassa ao draft_gate: não validar policy_tags vs sensitive_data_types.yaml",
    )
    pd.add_argument(
        "--skip-yml-doc",
        action="store_true",
        help="Repassa ao draft_gate: não validar documentação mínima dos stem.yml (intermediate/marts)",
    )
    pd.add_argument(
        "--skip-int-mart-yml-pairing",
        action="store_true",
        dest="skip_int_mart_yml_pairing",
        help="Repassa ao draft_gate: não exigir stem.yml irmão por modelo em models/intermediate e models/marts (draft)",
    )
    pd.set_defaults(func=cmd_draft_gate)

    pr = sub.add_parser("run", parents=[common], help="extract depois draft-gate")
    pr.add_argument("--received-dir", default=str(DEFAULT_RECEIVED))
    pr.add_argument("--output-dir", default=str(DEFAULT_TEXT_EGPS))
    pr.add_argument("--resume-extract", action="store_true", help="Mesmo que extract --resume")
    pr.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    pr.add_argument("--strict", action="store_true")
    pr.add_argument("--write-report", action="store_true")
    pr.add_argument("--txt-dir", default=None)
    pr.add_argument("--json", action="store_true")
    pr.add_argument(
        "--parity-tables-all-arch",
        action="store_true",
        help="Repassa ao draft_gate: heurística DETECTED_TABLES_* também em DATABRICKS",
    )
    pr.add_argument(
        "--allow-legacy-spec",
        action="store_true",
        help="Repassa ao draft_gate: permite MIGRATION_SPEC.md sem contrato YAML (modo legado)",
    )
    pr.add_argument(
        "--require-filtros-aplicados",
        action="store_true",
        help="Repassa ao draft_gate: se houver FILTERS_ORIGINAIS, exige _FILTROS_APLICADOS.md (erro se faltar)",
    )
    pr.add_argument(
        "--skip-pii-yml",
        action="store_true",
        help="Repassa ao draft_gate: não validar policy_tags vs sensitive_data_types.yaml",
    )
    pr.add_argument(
        "--skip-yml-doc",
        action="store_true",
        help="Repassa ao draft_gate: não validar documentação mínima dos stem.yml (intermediate/marts)",
    )
    pr.add_argument(
        "--skip-int-mart-yml-pairing",
        action="store_true",
        dest="skip_int_mart_yml_pairing",
        help="Repassa ao draft_gate: não exigir stem.yml irmão por modelo em models/intermediate e models/marts (draft)",
    )
    pr.add_argument(
        "--scaffold-yml",
        action="store_true",
        dest="scaffold_yml",
        help="Após draft_gate (run): gera stem.yml mínimos em falta no draft (intermediate/marts). Ver scaffold_int_mart_yml.py.",
    )
    pr.set_defaults(func=cmd_run)

    pc = sub.add_parser("checks", parents=[common], help="Checagens leves no disco + manifest.batch_checks")
    pc.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    pc.add_argument("--txt-dir", default=None, help="Pasta dos .txt (default: text_egps)")
    pc.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 se extract=ok mas falta spec/contrato YAML ou .sql/.py no draft; "
        "ou (modo **layers**) se TARGET_ARCH é DBT_BQ ou DATABRICKS no .txt, há ficheiros no draft e falta três camadas "
        "staging/intermediate/marts com materialized literal (`draft_three_layers_ok`); "
        "ou (modo **flow**) se o draft está em `draft_models/<egp>/models/NN_*.sql` (heurística/`draft_layout: flow`) "
        "e `draft_flow_gate_ok` é falso; "
        "ou se TARGET_ARCH=DBT_BQ no .txt e há modelos int/mart no draft sem stem.yml irmão (`draft_yml_pairing_ok`); "
        "ou se há convertido dbt com models int/mart sem .yml irmão; "
        "ou se há gaps PII (colunas sensíveis sem policy_tags aceites nos stem.yml; "
        "com `pii_reference_interno_strict` ou --reference-interno-strict, também exige PII_INTERNO_* "
        "de referência para tipos alvo); "
        "ou se stem.yml int/mart não cumpre documentação mínima (salvo --skip-yml-doc); "
        "ou (modo **layers**) se `step_gate_ok` falhar quando existe `.txt`",
    )
    pc.add_argument(
        "--skip-yml-doc",
        action="store_true",
        help="Não calcular / não falhar (em --strict) o guardrail de documentação YAML dos stem.yml",
    )
    pc.set_defaults(func=cmd_checks)

    ps = sub.add_parser(
        "set-step",
        help="Atualiza manifest.pipeline_steps[step] (agente/humano regista progresso)",
    )
    ps.add_argument("--batch-file", "-b", required=False, metavar="PATH", help="(opcional) só para contexto")
    ps.add_argument("--catalog", default=str(DEFAULT_REGISTRY_PATH))
    ps.add_argument("--manifest", "-m", default=str(DEFAULT_MANIFEST))
    ps.add_argument("--egp-key", required=True, metavar="KEY")
    ps.add_argument(
        "--step",
        required=True,
        choices=list(PIPELINE_STEP_KEYS),
        metavar="STEP",
        help="Um de: " + ", ".join(PIPELINE_STEP_KEYS),
    )
    ps.add_argument(
        "--status",
        required=True,
        choices=sorted(VALID_PIPELINE_STATUSES),
        help="not_started | pending | ok | fail | skipped | na",
    )
    ps.add_argument("--note", default="", help="Nota curta (opcional)")
    ps.add_argument("--quiet", "-q", action="store_true")
    ps.set_defaults(func=cmd_set_step)

    pa = sub.add_parser(
        "batch-audit",
        parents=[common],
        help="Gera BATCH_AUDIT.md (tabela resumo + links implícitos nos paths)",
    )
    pa.add_argument(
        "--out",
        "-o",
        default=str(SCRIPT_DIR / "registry" / "BATCH_AUDIT.md"),
        help="Destino do relatório markdown",
    )
    pa.add_argument(
        "--refresh-checks",
        action="store_true",
        help="Antes de gerar, corre compute_batch_checks para cada chave do batch",
    )
    pa.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    pa.add_argument("--txt-dir", default=None)
    pa.add_argument(
        "--skip-yml-doc",
        action="store_true",
        help="Com --refresh-checks: não validar documentação mínima dos stem.yml (intermediate/marts)",
    )
    pa.set_defaults(func=cmd_batch_audit)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

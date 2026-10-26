#!/usr/bin/env python3
"""
Gate híbrido pós-draft: checagens mecânicas (CI / lote) + checklist semântica para o agente.

Guardrails: exige ``text_egps/<egp_key>.txt`` (saída do extrator); valida paridade
``MIGRATION_SPEC.md`` (TARGET_ARCH efetivo, PROJECT) vs cabeçalho do ``.txt`` + catálogo
quando o spec existir no draft.

Para **DBT_BQ** e **DATABRICKS**, exige em ``draft_models/<egp_key>/models/`` as três pastas
``staging/``, ``intermediate/`` e ``marts/`` com pelo menos um ``.sql`` ou ``.py`` cada, e que
cada modelo declare ``materialized='...'`` (valor literal entre aspas) permitido por camada
(ver ``draft_layer_guard.py``).

Se ``MIGRATION_SPEC.md`` contiver um segundo bloco `` ```yaml`` com chave ``draft_manifest`` (secção 9)
e ``models`` não vazio, valida que cada ``(layer, stem)`` existe como ficheiro no draft.

Uso (pasta converter/):
  python -m scripts.draft_gate "Analise_mix_vulneraveis"
  python -m scripts.draft_gate "Analise_mix_vulneraveis" --strict
  python -m scripts.draft_gate --batch-file registry/egp_keys_batch.txt --strict
  python -m scripts.draft_gate "X" --write-report
  python -m scripts.draft_gate "X" --parity-tables-all-arch   # heurística DETECTED_TABLES também em DATABRICKS
  python -m scripts.draft_gate "X" --skip-pii-yml             # não validar policy_tags vs sensitive_data_types.yaml
  python -m scripts.draft_gate "X" --skip-yml-doc             # não validar documentação mínima dos stem.yml int/mart
  python -m scripts.draft_gate "X" --skip-int-mart-yml-pairing # não exigir stem.yml irmão de cada .sql em int/mart (draft)
  python -m scripts.draft_gate "X" --reference-interno-strict # PII: exige PII_INTERNO_* de referência para tipos alvo (dbt)

Requer: draft em draft_models/<egp_key>/ (SQL ou Py), text_egps/<egp_key>.txt, entrada no catálogo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .bootstrap_egp_catalog import (
    DEFAULT_REGISTRY_PATH,
    SCRIPT_DIR,
    index_entries,
    load_or_create_catalog,
    resolve_dbt_project_root,
)
from .generate_migration_spec import parse_txt_metadata, target_arch_effective
from .draft_layer_guard import check_draft_three_layers_and_materialization
from .model_yml_guard import check_int_mart_yml_pairing
from .pii_reference import catalog_pii_reference_interno_strict, reference_pii_bundle
from .pii_sensitive_yml_guard import check_sensitive_column_policy_tags
from .yml_documentation_guard import check_int_mart_yml_documentation

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_TEXT_EGPS = SCRIPT_DIR / "text_egps"
DEFAULT_DRAFT_ROOT = SCRIPT_DIR / "draft_models"
SENSITIVE_DATA_TYPES_YAML = SCRIPT_DIR / "registry" / "sensitive_data_types.yaml"

# Aviso se o corpo SAS após END_METADATA for menor que isto (extração vazia/truncada).
MIN_SAS_BODY_CHARS_WARN = 200

SPEC_ROW_TARGET_ARCH_RE = re.compile(
    r"\|\s*\*\*TARGET_ARCH efetivo\*\*\s*\|\s*`([^`]*)`\s*\|",
    re.IGNORECASE,
)
SPEC_ROW_PROJECT_RE = re.compile(
    r"\|\s*\*\*PROJECT \(extrator\)\*\*\s*\|\s*`([^`]*)`\s*\|",
    re.IGNORECASE,
)

SPEC_CONTRACT_YAML_RE = re.compile(r"```yaml\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)

REF_RE = re.compile(r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
SOURCE_RE = re.compile(
    r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
)


def collect_draft_sql(draft_dir: Path) -> tuple[str, list[str]]:
    """Concatena .sql e .py do draft; retorna (texto, lista de ficheiros)."""
    parts: list[str] = []
    files: list[str] = []
    if not draft_dir.is_dir():
        return "", []
    for p in sorted(draft_dir.rglob("*.sql")):
        files.append(str(p.relative_to(draft_dir)))
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    for p in sorted(draft_dir.rglob("*.py")):
        files.append(str(p.relative_to(draft_dir)))
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts), files


def extract_refs(sql_py: str) -> set[str]:
    return {m.group(1).strip() for m in REF_RE.finditer(sql_py)}


def extract_sources(sql_py: str) -> set[tuple[str, str]]:
    return {(m.group(1).strip(), m.group(2).strip()) for m in SOURCE_RE.finditer(sql_py)}


def parse_table_list(value: str) -> list[str]:
    if not value or value.strip().lower() in ("", "none"):
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


def table_mentioned_in_code(table_id: str, haystack_lower: str) -> bool:
    t = table_id.strip().lower()
    if not t:
        return True
    if t in haystack_lower:
        return True
    short = t.split(".")[-1]
    if short and short in haystack_lower:
        return True
    return False


def staging_ref_models(entry: dict) -> list[str]:
    srm = entry.get("staging_ref_map")
    if not srm:
        return []
    out: list[str] = []
    if isinstance(srm, list):
        for row in srm:
            if isinstance(row, dict) and row.get("ref_model"):
                out.append(str(row["ref_model"]).strip())
    elif isinstance(srm, dict):
        for v in srm.values():
            if isinstance(v, str):
                out.append(v.strip())
    return [x for x in out if x]


def effective_staging_mode(entry: dict, defaults: dict) -> str:
    sm = entry.get("staging_mode")
    if sm is not None and str(sm).strip():
        return str(sm).strip().lower()
    d = (defaults or {}).get("staging_mode")
    if d is not None and str(d).strip():
        return str(d).strip().lower()
    return "reuse_existing"


def txt_has_filters_originais(txt_path: Path) -> bool:
    if not txt_path.is_file():
        return False
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    return "FILTERS_ORIGINAIS" in text.upper()


def normalize_target_arch(value: str) -> str:
    """Normaliza para DBT_BQ ou DATABRICKS (maiúsculas)."""
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


def sas_body_after_metadata(txt_path: Path) -> str | None:
    """Texto SAS após END_METADATA; None se o ficheiro ou o marcador não existir."""
    if not txt_path.is_file():
        return None
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    if "END_METADATA" not in text:
        return None
    return text.split("END_METADATA", 1)[1]


def parse_spec_target_arch_efetivo(spec_text: str) -> str | None:
    m = SPEC_ROW_TARGET_ARCH_RE.search(spec_text)
    if not m:
        return None
    return (m.group(1) or "").strip()


def parse_spec_project_extrator(spec_text: str) -> str | None:
    m = SPEC_ROW_PROJECT_RE.search(spec_text)
    if not m:
        return None
    return (m.group(1) or "").strip()


def parse_spec_contract_yaml(spec_text: str) -> dict | None:
    """
    Tenta extrair o primeiro bloco ```yaml``` do MIGRATION_SPEC (se houver) e parsear.
    Retorna dict ou None.
    """
    if yaml is None:
        return None
    m = SPEC_CONTRACT_YAML_RE.search(spec_text)
    if not m:
        return None
    raw = (m.group(1) or "").strip()
    if not raw:
        return None
    try:
        data = yaml.safe_load(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


DRAFT_MANIFEST_LAYERS = frozenset({"staging", "intermediate", "marts"})


def parse_draft_manifest_from_spec(spec_text: str) -> dict | None:
    """
    Percorre todos os fences ```yaml ... ``` e devolve o dict `draft_manifest` interno
    (chaves schema_version, models, …) quando um bloco YAML tem top-level `draft_manifest`.
    """
    if yaml is None:
        return None
    for m in SPEC_CONTRACT_YAML_RE.finditer(spec_text):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = yaml.safe_load(raw)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        inner = data.get("draft_manifest")
        if isinstance(inner, dict):
            return inner
    return None


def validate_draft_manifest_models(
    draft_manifest: dict | None,
    draft_models_dir: Path,
) -> tuple[list[str], int, str]:
    """
    Valida `draft_manifest.models` contra ficheiros no disco.

    Returns:
        (errors, n_declared, resumo_para_relatorio)
    """
    if not draft_manifest:
        return [], 0, "manifest ausente (sem validação de lista)"
    models = draft_manifest.get("models")
    if models is None:
        return [], 0, "sem chave `models` (sem validação de lista)"
    if not isinstance(models, list):
        return (
            [f"draft_manifest.models deve ser lista; obtido: {type(models).__name__}"],
            0,
            "FALHA (schema)",
        )
    if len(models) == 0:
        return [], 0, "0 modelo(s) declarados (validação de lista desativada)"

    errors: list[str] = []
    for i, item in enumerate(models):
        if not isinstance(item, dict):
            errors.append(f"draft_manifest.models[{i}]: cada item deve ser um objeto com `layer` e `stem`")
            continue
        layer = str(item.get("layer") or "").strip()
        stem = str(item.get("stem") or "").strip()
        if layer not in DRAFT_MANIFEST_LAYERS:
            errors.append(
                f"draft_manifest.models[{i}]: `layer` inválido {layer!r} — use staging, intermediate ou marts"
            )
        if not stem or "/" in stem or "\\" in stem or ".." in stem:
            errors.append(f"draft_manifest.models[{i}]: `stem` inválido ou inseguro: {stem!r}")
            continue
        base = draft_models_dir / layer
        sql_f = base / f"{stem}.sql"
        py_f = base / f"{stem}.py"
        if not sql_f.is_file() and not py_f.is_file():
            errors.append(
                f"draft_manifest: falta `models/{layer}/{stem}.sql` ou `models/{layer}/{stem}.py` no draft"
            )
    n = len(models)
    ok = len(errors) == 0
    return errors, n, f"{n} declarados; {'OK' if ok else 'FALHA'}"


def run_gate(
    egp_key: str,
    *,
    catalog_path: Path,
    draft_root: Path,
    txt_path: Path,
    strict: bool,
    write_report: bool,
    parity_tables_all_arch: bool = False,
    allow_legacy_spec: bool = False,
    require_filtros_aplicados: bool = False,
    skip_pii_yml: bool = False,
    skip_yml_doc: bool = False,
    skip_int_mart_yml_pairing: bool = False,
    reference_interno_strict_cli: bool = False,
) -> dict:
    """Retorna dict com errors, warnings, ok, files_scanned."""
    result: dict = {
        "egp_key": egp_key,
        "errors": [],
        "warnings": [],
        "infos": [],
        "files_scanned": [],
    }

    draft_dir = draft_root / egp_key
    combined, files = collect_draft_sql(draft_dir)
    result["files_scanned"] = files
    combined_lower = combined.lower()

    if not files:
        if (draft_dir / "MIGRATION_SPEC.md").is_file():
            result["warnings"].append(
                "Nenhum .sql/.py no draft — só MIGRATION_SPEC? Concluir o draft (Agent 1) antes do gate."
            )
        else:
            result["errors"].append(f"Nenhum .sql/.py em {draft_dir}")

    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog["entries"])
    entry = by_key.get(egp_key)
    if not entry:
        result["errors"].append(f"egp_key não encontrado no catálogo: {egp_key!r}")

    if not txt_path.is_file():
        result["errors"].append(
            f"Ficheiro do extrator em falta: {txt_path} — correr `python -m scripts.egps_extractor` com o `.egp` "
            f"(ficheiro: `scripts/egps_extractor.py`) / PASSO 1 antes do gate."
        )

    meta = parse_txt_metadata(txt_path)
    if txt_path.is_file():
        text_full = txt_path.read_text(encoding="utf-8", errors="replace")
        if "START_METADATA" not in text_full or "END_METADATA" not in text_full:
            result["warnings"].append(
                f"Marcadores START_METADATA/END_METADATA ausentes ou incompletos em {txt_path} "
                "(extrator desatualizado ou ficheiro corrompido)."
            )
        elif not meta:
            result["warnings"].append(
                f"Cabeçalho START_METADATA/END_METADATA sem chaves parseáveis: {txt_path}"
            )

    defaults = catalog.get("defaults") or {}
    staging_mode = effective_staging_mode(entry or {}, defaults) if entry else "reuse_existing"

    expected_arch_raw, arch_note = target_arch_effective(meta, entry or {}, defaults)
    ta = normalize_target_arch(expected_arch_raw)
    if ta not in ("DBT_BQ", "DATABRICKS"):
        result["warnings"].append(
            f"TARGET_ARCH efetivo inesperado após normalização: {expected_arch_raw!r} — usar DBT_BQ ou DATABRICKS."
        )
        ta = "DBT_BQ" if "DATABRICKS" not in (expected_arch_raw or "").upper() else "DATABRICKS"

    refs = extract_refs(combined)
    sources = extract_sources(combined)
    if refs:
        result["infos"].append(f"refs únicos encontrados: {len(refs)}")
    if sources:
        result["infos"].append(f"source() encontrados: {len(sources)}")
    result["infos"].append(f"TARGET_ARCH efetivo (gate): {ta} — origem: {arch_note}")

    spec_path = draft_dir / "MIGRATION_SPEC.md"
    spec_full_text: str | None = None
    parity_lines: list[str] = []
    parity_lines.append(f"- **text_egps:** `{txt_path}` ({'existe' if txt_path.is_file() else 'em falta'})")
    parity_lines.append(f"- **TARGET_ARCH efetivo (catálogo + .txt):** `{ta}` ({arch_note})")

    if spec_path.is_file():
        spec_text = spec_path.read_text(encoding="utf-8", errors="replace")
        spec_full_text = spec_text
        contract = parse_spec_contract_yaml(spec_text)
        if contract is None and not allow_legacy_spec:
            result["errors"].append(
                "MIGRATION_SPEC.md presente mas contrato YAML (## 0. CONTRATO com bloco ```yaml ... ```) "
                "não encontrado ou inválido. Regenerar com "
                f"`python -m scripts.generate_migration_spec \"{egp_key}\"`."
            )
        elif contract is None and allow_legacy_spec:
            result["warnings"].append(
                "MIGRATION_SPEC.md sem contrato YAML (modo legado habilitado: --allow-legacy-spec). "
                "Recomenda-se regenerar o spec para ativar validações robustas."
            )

        spec_ta_raw = None
        spec_proj = None
        if contract:
            spec_ta_raw = (contract.get("target_arch_effective") or "").strip() or None
            spec_proj = (contract.get("project_extrator") or "").strip() or None
        if spec_ta_raw is None:
            spec_ta_raw = parse_spec_target_arch_efetivo(spec_text)
        if spec_proj is None:
            spec_proj = parse_spec_project_extrator(spec_text)
        if spec_ta_raw is None:
            result["warnings"].append(
                "MIGRATION_SPEC.md presente mas não foi possível ler a linha da tabela "
                "**TARGET_ARCH efetivo** (formato esperado: | **TARGET_ARCH efetivo** | `DBT_BQ` |)."
            )
            parity_lines.append("- **Paridade TARGET_ARCH (spec):** não verificada (célula não encontrada).")
        else:
            spec_ta = normalize_target_arch(spec_ta_raw)
            parity_lines.append(f"- **TARGET_ARCH no spec:** `{spec_ta_raw}` → normalizado `{spec_ta}`")
            if spec_ta != ta:
                result["errors"].append(
                    f"MIGRATION_SPEC.md: TARGET_ARCH efetivo `{spec_ta}` ≠ esperado `{ta}` "
                    f"(extrator + catálogo: {arch_note}). Regenerar com "
                    f"`python -m scripts.generate_migration_spec \"{egp_key}\"` após alinhar o `.txt`/catálogo."
                )
            else:
                parity_lines.append("- **Paridade TARGET_ARCH (spec vs extrator+catálogo):** OK")

        txt_project = (meta.get("PROJECT") or "").strip()
        if spec_proj is not None:
            sp = spec_proj.strip()
            parity_lines.append(f"- **PROJECT (extrator) no spec:** `{sp}`")
            if txt_project and sp and sp != txt_project:
                result["warnings"].append(
                    f"MIGRATION_SPEC.md: PROJECT (extrator) `{sp}` ≠ cabeçalho do .txt `{txt_project}`. "
                    "Regenerar o spec após re-extração ou alinhar manualmente."
                )
            elif txt_project and sp == txt_project:
                parity_lines.append("- **Paridade PROJECT (spec vs .txt):** OK")
        else:
            parity_lines.append("- **PROJECT (extrator) no spec:** não lido (célula não encontrada).")
    else:
        result["infos"].append(
            "Sem MIGRATION_SPEC.md no draft — paridade TARGET_ARCH/PROJECT (spec vs extrator) não verificada."
        )
        parity_lines.append("- **MIGRATION_SPEC.md:** ausente (paridade spec↔txt não aplicada).")

    if txt_path.is_file():
        body_tail = sas_body_after_metadata(txt_path)
        if body_tail is not None:
            body_stripped = body_tail.strip()
            n = len(body_stripped)
            parity_lines.append(f"- **Tamanho do corpo SAS após END_METADATA:** {n} caracteres")
            if n < MIN_SAS_BODY_CHARS_WARN:
                result["warnings"].append(
                    f"Corpo SAS após END_METADATA muito pequeno ({n} < {MIN_SAS_BODY_CHARS_WARN} caracteres) — "
                    "possível extração vazia ou truncada."
                )

    # staging_ref_map obrigatório em reuse/hybrid quando definido
    if entry and staging_mode in ("reuse_existing", "hybrid"):
        needed = staging_ref_models(entry)
        for model in needed:
            if model not in refs:
                result["errors"].append(
                    f"staging_ref_map exige ref('{model}') no draft — não encontrado (modo {staging_mode})"
                )

    # Cobertura heurística DETECTED_TABLES (DBT_BQ; opcionalmente DATABRICKS com --parity-tables-all-arch)
    if combined and (ta == "DBT_BQ" or parity_tables_all_arch):
        hard = parse_table_list(meta.get("DETECTED_TABLES_HARDCODED", ""))
        dyn = parse_table_list(meta.get("DETECTED_TABLES_DYNAMIC", ""))
        for tbl in hard + dyn:
            if not table_mentioned_in_code(tbl, combined_lower):
                result["warnings"].append(
                    f"Tabela do extrator possivelmente não refletida no draft (heurística): {tbl!r}"
                )
        if parity_tables_all_arch and ta == "DATABRICKS":
            result["infos"].append(
                "Heurística DETECTED_TABLES_* aplicada também em DATABRICKS (--parity-tables-all-arch); "
                "possíveis falsos positivos em .py."
            )

    # FILTERS_ORIGINAIS → ficheiro de checklist
    filt_path = draft_dir / "_FILTROS_APLICADOS.md"
    if txt_has_filters_originais(txt_path) and not filt_path.is_file():
        msg = "Existe FILTERS_ORIGINAIS no .txt mas falta draft_models/.../_FILTROS_APLICADOS.md"
        if require_filtros_aplicados:
            result["errors"].append(msg)
        else:
            result["warnings"].append(msg)

    # Três camadas (staging / intermediate / marts) + materialized literal por ficheiro (DBT_BQ e DATABRICKS)
    draft_models_dir = draft_dir / "models"
    if ta in ("DBT_BQ", "DATABRICKS"):
        ok_layers, layer_errors, layer_summary = check_draft_three_layers_and_materialization(
            draft_models_dir, ta
        )
        result["errors"].extend(layer_errors)
        sn = int(layer_summary.get("staging_model_count", 0))
        inn = int(layer_summary.get("intermediate_model_count", 0))
        mn = int(layer_summary.get("marts_model_count", 0))
        parity_lines.append(
            f"- **Três camadas + materialized (draft, {ta}):** "
            f"staging={sn}, intermediate={inn}, marts={mn}; "
            f"{'OK' if ok_layers else 'FALHA (ver erros acima)'}"
        )
    if skip_int_mart_yml_pairing:
        parity_lines.append(
            "- **Paridade int/mart ↔ stem.yml (draft):** ignorada (`--skip-int-mart-yml-pairing`)."
        )
    elif ta == "DBT_BQ" and draft_models_dir.is_dir():
        missing, total_im, miss_count = check_int_mart_yml_pairing(draft_models_dir)
        parity_lines.append(
            f"- **Paridade int/mart ↔ stem.yml (draft):** "
            f"{miss_count} modelo(s) sem `.yml` irmão (total int/mart: {total_im})."
        )
        if miss_count:
            max_show = 15
            for abs_path in missing[:max_show]:
                pth = Path(abs_path)
                try:
                    rel = pth.relative_to(draft_models_dir)
                except ValueError:
                    rel = pth
                result["errors"].append(
                    "Paridade stem.yml (draft): falta `stem.yml` para "
                    f"`models/{rel.as_posix()}` (mesmo nome base que o `.sql`/`.py`)."
                )
            extra = miss_count - min(len(missing), max_show)
            if extra > 0:
                result["errors"].append(
                    f"Paridade stem.yml (draft): … e mais {extra} ficheiro(s) em `intermediate/` ou `marts/` sem `.yml`."
                )
    elif ta == "DBT_BQ":
        parity_lines.append("- **Paridade int/mart ↔ stem.yml (draft):** N/A (sem pasta `draft_models/.../models/`).")

    # draft_manifest (MIGRATION_SPEC §9): lista opcional → ficheiros em models/{staging,intermediate,marts}/
    if spec_full_text is not None:
        dm_inner = parse_draft_manifest_from_spec(spec_full_text)
        mf_errs, n_mf_decl, mf_sum = validate_draft_manifest_models(dm_inner, draft_models_dir)
        result["errors"].extend(mf_errs)
        parity_lines.append(f"- **draft_manifest (MIGRATION_SPEC §9):** {n_mf_decl} modelo(s); {mf_sum}")
    else:
        parity_lines.append("- **draft_manifest (MIGRATION_SPEC §9):** N/A (sem MIGRATION_SPEC.md)")

    # PII: colunas sensíveis (registry) → policy_tags nos stem.yml de int/mart na saída convertida
    if not skip_pii_yml and ta == "DBT_BQ" and yaml is not None:
        from .batch_pipeline import find_converted_anywhere

        _ar, conv_root = find_converted_anywhere(SCRIPT_DIR, catalog, entry or {}, egp_key)
        if conv_root and (conv_root / "models").is_dir():
            try:
                dbt_root = resolve_dbt_project_root(SCRIPT_DIR, catalog, entry or {})
                ref_pii_info, allowed = reference_pii_bundle(dbt_root)
                scope = str(ref_pii_info.get("pii_reference_scope") or "")
                fb = str(ref_pii_info.get("pii_reference_04_marts_fallback") or "não")
                parity_lines.append(
                    f"- **PII referência (inferência):** âmbito `{scope or 'n/a'}`; "
                    f"fallback para `models/` exceto `migracao_sas`: **{fb}** "
                    "(se `sim`, não há `PII_INTERNO_*` nos YAML sob `**/04_marts/**` — alinhar marts de referência)."
                )
                ri_strict = bool(reference_interno_strict_cli) or catalog_pii_reference_interno_strict(
                    entry or {}, catalog
                )
                if ri_strict:
                    parity_lines.append(
                        "- **PII reference_interno_strict:** ativo (CLI `--reference-interno-strict` e/ou "
                        "`pii_reference_interno_strict` no catálogo) — exige `PII_INTERNO_*` de referência "
                        "para tipos sensíveis alvo; ver `pii_sensitive_yml_guard.STRICT_REFERENCE_ENTRY_IDS`."
                    )
                pii_errs, n_sens, n_gap = check_sensitive_column_policy_tags(
                    conv_root / "models",
                    SENSITIVE_DATA_TYPES_YAML,
                    allowed if allowed else None,
                    reference_interno_strict=ri_strict,
                    reference_pii_var_suggestion=str(ref_pii_info.get("pii_reference_var") or ""),
                    allow_confidenciais_without_interno=False,
                )
                parity_lines.append(
                    f"- **PII YAML (sensitive_data_types ↔ policy_tags):** "
                    f"{len(pii_errs)} erro(s); colunas catalogadas={n_sens}; gaps={n_gap}"
                )
                result["errors"].extend(pii_errs)
            except Exception as ex:
                result["warnings"].append(f"PII YAML guard não executado: {ex}")
        else:
            parity_lines.append(
                "- **PII YAML (sensitive_data_types ↔ policy_tags):** N/A (sem sandbox/clone com `models/`)"
            )
    elif skip_pii_yml:
        parity_lines.append("- **PII YAML:** ignorado (`--skip-pii-yml`).")

    # Documentação mínima stem.yml (sandbox convertido DBT_BQ)
    if skip_yml_doc:
        parity_lines.append("- **YAML documentação (int/mart):** ignorado (`--skip-yml-doc`).")
    elif ta != "DBT_BQ":
        parity_lines.append("- **YAML documentação (int/mart):** N/A (TARGET_ARCH ≠ DBT_BQ).")
    elif yaml is None:
        parity_lines.append("- **YAML documentação (int/mart):** N/A (PyYAML não disponível).")
    else:
        from .batch_pipeline import find_converted_anywhere

        _ar_doc, conv_root_doc = find_converted_anywhere(SCRIPT_DIR, catalog, entry or {}, egp_key)
        if conv_root_doc and (conv_root_doc / "models").is_dir():
            try:
                doc_errs = check_int_mart_yml_documentation(conv_root_doc / "models")
                parity_lines.append(
                    f"- **YAML documentação (int/mart):** {len(doc_errs)} erro(s) "
                    "(columns/meta.cron/descrições; ver `yml_documentation_guard.py`)"
                )
                result["errors"].extend(doc_errs)
            except Exception as ex:
                result["warnings"].append(f"YAML documentação guard não executado: {ex}")
        else:
            parity_lines.append(
                "- **YAML documentação (int/mart):** N/A (sem sandbox/clone com `models/` convertido)"
            )

    if write_report and draft_dir.is_dir():
        report_path = draft_dir / "DRAFT_GATE_REPORT.md"
        lines = [
            f"# DRAFT_GATE_REPORT — `{egp_key}`",
            "",
            "## Paridade extrator ↔ spec/draft",
            "",
            *parity_lines,
            "",
            "## Erros",
            "",
        ]
        if result["errors"]:
            lines.extend(f"- {e}" for e in result["errors"])
        else:
            lines.append("- (nenhum)")
        lines.extend(["", "## Avisos", ""])
        if result["warnings"]:
            lines.extend(f"- {w}" for w in result["warnings"])
        else:
            lines.append("- (nenhum)")
        lines.extend(["", "## Info", ""])
        if result["infos"]:
            lines.extend(f"- {i}" for i in result["infos"])
        else:
            lines.append("- (nenhum)")
        lines.extend(["", "## Ficheiros analisados", ""])
        if result["files_scanned"]:
            lines.extend(f"- `{f}`" for f in result["files_scanned"])
        else:
            lines.append("- (nenhum)")
        lines.append("")
        lines.append(
            "Complete a **checklist semântica** em "
            "`converter/templates/DRAFT_GATE_CHECKLIST.md` (copiar para o draft se desejado)."
        )
        report_path.write_text("\n".join(lines), encoding="utf-8")
        result["infos"].append(f"Relatório escrito: {report_path}")

    result["ok"] = len(result["errors"]) == 0
    return result


def exit_code_for(result: dict, strict: bool) -> int:
    if result["errors"]:
        return 1
    if strict and result["warnings"]:
        return 1
    return 0


def print_text_report(result: dict) -> None:
    print(f"=== draft_gate: {result['egp_key']} ===")
    if result["errors"]:
        print("ERROS:")
        for e in result["errors"]:
            print(f"  - {e}")
    if result["warnings"]:
        print("AVISOS:")
        for w in result["warnings"]:
            print(f"  - {w}")
    if result["infos"]:
        for i in result["infos"]:
            print(f"  ({i})")
    print(f"Ficheiros: {len(result['files_scanned'])}")
    if result["errors"]:
        print("RESULTADO: FALHA (erros)")
    elif result["warnings"]:
        print("RESULTADO: AVISOS (rever checklist do agente)")
    else:
        print("RESULTADO: OK (mecânico)")


def cmd_one(args: argparse.Namespace) -> int:
    txt = Path(args.txt) if args.txt else (DEFAULT_TEXT_EGPS / f"{args.egp_key}.txt")
    result = run_gate(
        args.egp_key,
        catalog_path=Path(args.catalog),
        draft_root=Path(args.draft_root),
        txt_path=txt,
        strict=args.strict,
        write_report=args.write_report,
        parity_tables_all_arch=args.parity_tables_all_arch,
        allow_legacy_spec=args.allow_legacy_spec,
        require_filtros_aplicados=args.require_filtros_aplicados,
        skip_pii_yml=getattr(args, "skip_pii_yml", False),
        skip_yml_doc=getattr(args, "skip_yml_doc", False),
        skip_int_mart_yml_pairing=getattr(args, "skip_int_mart_yml_pairing", False),
        reference_interno_strict_cli=getattr(args, "reference_interno_strict", False),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text_report(result)
    return exit_code_for(result, args.strict)


def cmd_batch(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch_file)
    if not batch_path.is_file():
        print(f"Ficheiro inexistente: {batch_path}", file=sys.stderr)
        return 1
    keys = []
    for ln in batch_path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        keys.append(s)
    worst = 0
    batch_out: list[dict] = []
    for k in keys:
        txt = DEFAULT_TEXT_EGPS / f"{k}.txt"
        r = run_gate(
            k,
            catalog_path=Path(args.catalog),
            draft_root=Path(args.draft_root),
            txt_path=txt,
            strict=False,
            write_report=args.write_report,
            parity_tables_all_arch=args.parity_tables_all_arch,
            allow_legacy_spec=args.allow_legacy_spec,
            require_filtros_aplicados=args.require_filtros_aplicados,
            skip_pii_yml=getattr(args, "skip_pii_yml", False),
            skip_yml_doc=getattr(args, "skip_yml_doc", False),
            skip_int_mart_yml_pairing=getattr(args, "skip_int_mart_yml_pairing", False),
            reference_interno_strict_cli=getattr(args, "reference_interno_strict", False),
        )
        code = exit_code_for(r, args.strict)
        worst = max(worst, code)
        r["exit_code"] = code
        batch_out.append(r)
        if not args.json:
            st = "FAIL" if r["errors"] else ("WARN" if r["warnings"] else "OK")
            print(f"[{st}] {k}")
    if args.json:
        print(json.dumps(batch_out, ensure_ascii=False, indent=2))
    return worst


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gate híbrido pós-draft (mecânico + relatório para agente)")
    p.add_argument(
        "egp_key",
        nargs="?",
        default=None,
        help="egp_key (omitir se usar --batch-file)",
    )
    p.add_argument(
        "--batch-file",
        "-b",
        default=None,
        metavar="PATH",
        help="Ficheiro com um egp_key por linha (modo lote)",
    )
    p.add_argument("--catalog", default=str(DEFAULT_REGISTRY_PATH))
    p.add_argument("--draft-root", default=str(DEFAULT_DRAFT_ROOT))
    p.add_argument("--txt", default=None, help="text_egps (só modo um EGP; default text_egps/<egp_key>.txt)")
    p.add_argument("--strict", action="store_true", help="Avisos também retornam exit 1")
    p.add_argument("--write-report", action="store_true", help="Gera DRAFT_GATE_REPORT.md em cada draft/")
    p.add_argument("--json", action="store_true", help="Saída JSON (lote = array)")
    p.add_argument(
        "--parity-tables-all-arch",
        action="store_true",
        help="Aplicar heurística DETECTED_TABLES_* também quando TARGET_ARCH=DATABRICKS (mais ruído em .py)",
    )
    p.add_argument(
        "--allow-legacy-spec",
        action="store_true",
        help="Permite MIGRATION_SPEC.md sem contrato YAML (modo legado). Recomendado só para specs antigos.",
    )
    p.add_argument(
        "--require-filtros-aplicados",
        action="store_true",
        help="Se houver FILTERS_ORIGINAIS no .txt, exige _FILTROS_APLICADOS.md (senão: erro).",
    )
    p.add_argument(
        "--skip-pii-yml",
        action="store_true",
        help="Não validar policy_tags em stem.yml (intermediate/marts) vs registry/sensitive_data_types.yaml.",
    )
    p.add_argument(
        "--skip-yml-doc",
        action="store_true",
        help="Não validar documentação mínima dos stem.yml (intermediate/marts) no sandbox convertido (DBT_BQ).",
    )
    p.add_argument(
        "--skip-int-mart-yml-pairing",
        action="store_true",
        dest="skip_int_mart_yml_pairing",
        help="Não exigir ficheiro `stem.yml` irmão para cada `.sql`/`.py` em `models/intermediate/` e `models/marts/` no draft (DBT_BQ).",
    )
    p.add_argument(
        "--reference-interno-strict",
        action="store_true",
        dest="reference_interno_strict",
        help="PII (dbt): força modo estrito — exige PII_INTERNO_* de referência para tipos alvo "
        "(além de `pii_reference_interno_strict` no catálogo). Ver `pii_sensitive_yml_guard.py`.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.batch_file:
        return int(cmd_batch(args))
    if not args.egp_key:
        print("Indique egp_key ou --batch-file", file=sys.stderr)
        return 2
    return int(cmd_one(args))


if __name__ == "__main__":
    raise SystemExit(main())

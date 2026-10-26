"""
Inferência de policy tags `PII_INTERNO_*` a partir dos YAMLs do projeto dbt (referência).

Ordem de preferência:
1. YAMLs sob qualquer `.../04_marts/...` dentro de `dbt_root/models` (exclui `migracao_sas`).
2. Se não houver ocorrências de `PII_INTERNO_*` aí, fallback ao scan legado:
   `dbt_root/models/**/*.yml` exceto paths com `migracao_sas`.

Usado por `batch_pipeline.compute_batch_checks`, `draft_gate` e testes.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

# Captura nomes de variável PII_INTERNO_* em policy_tags / Jinja.
PII_INTERNO_NAME_RE = re.compile(r"\bPII_INTERNO_[A-Z0-9_]+\b")


def extract_pii_interno_var_names(text: str) -> list[str]:
    return list(PII_INTERNO_NAME_RE.findall(text or ""))


def _iter_model_ymls(models_dir: Path) -> list[Path]:
    if not models_dir.is_dir():
        return []
    return sorted(models_dir.rglob("*.yml"))


def _path_parts_lower(yml: Path) -> set[str]:
    return {p.lower() for p in yml.parts}


def _path_has_04_marts(yml: Path) -> bool:
    return "04_marts" in _path_parts_lower(yml)


def _path_has_migracao_sas(yml: Path) -> bool:
    return "migracao_sas" in _path_parts_lower(yml)


def _reference_pii_counts_scoped(
    dbt_root: Path, *, only_under_04_marts: bool
) -> tuple[Counter[str], int]:
    """
    Conta `PII_INTERNO_*` em YAMLs sob `dbt_root/models`.

    Se ``only_under_04_marts``: só ficheiros cujo path contém o segmento ``04_marts``
    (case-insensitive), excluindo ``migracao_sas``.
    Caso contrário: todo ``models/**/*.yml`` exceto ``migracao_sas`` (legado).
    """
    models = (dbt_root / "models").resolve()
    counts: Counter[str] = Counter()
    scanned = 0
    for yml in _iter_model_ymls(models):
        parts_lower = _path_parts_lower(yml)
        if "migracao_sas" in parts_lower:
            continue
        if only_under_04_marts and "04_marts" not in parts_lower:
            continue
        try:
            body = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        for name in extract_pii_interno_var_names(body):
            counts[name] += 1
    return counts, scanned


def allowed_from_reference_counts(counts: Counter[str]) -> frozenset[str]:
    """Top-2 nomes de variável PII_INTERNO_* (para tolerar mistura legítima rara)."""
    if not counts:
        return frozenset()
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = {ranked[0][0]}
    if len(ranked) > 1:
        out.add(ranked[1][0])
    return frozenset(out)


def _fill_bundle_counts(
    out: dict[str, str | int],
    counts: Counter[str],
    scanned: int,
    *,
    scope: str,
    fallback_used: bool,
) -> tuple[dict[str, str | int], frozenset[str]]:
    out["pii_reference_files_scanned"] = scanned
    out["pii_reference_hits"] = int(sum(counts.values()))
    out["pii_reference_scope"] = scope
    out["pii_reference_04_marts_fallback"] = "sim" if fallback_used else "não"
    if not counts:
        return out, frozenset()
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out["pii_reference_var"] = ranked[0][0]
    top2 = [ranked[0][0]]
    if len(ranked) > 1:
        top2.append(ranked[1][0])
    out["pii_reference_top2"] = "|".join(top2)
    return out, allowed_from_reference_counts(counts)


def reference_pii_bundle(dbt_root: Path | None) -> tuple[dict[str, str | int], frozenset[str]]:
    """
    Metadados + conjunto permitido (top-2) a partir dos YAMLs de referência.

    Prioridade: contagens só em ``**/04_marts/**/*.yml``. Se não houver nenhum
    ``PII_INTERNO_*`` nesse conjunto, usa o scan legado (todo ``models/`` exceto
    ``migracao_sas``) e define ``pii_reference_04_marts_fallback`` a ``sim``.
    """
    out: dict[str, str | int] = {
        "pii_reference_var": "",
        "pii_reference_top2": "",
        "pii_reference_files_scanned": 0,
        "pii_reference_hits": 0,
        "pii_reference_scope": "",
        "pii_reference_04_marts_fallback": "não",
    }
    if not dbt_root:
        return out, frozenset()

    counts_04, scanned_04 = _reference_pii_counts_scoped(dbt_root, only_under_04_marts=True)
    if counts_04:
        info, allowed = _fill_bundle_counts(
            out,
            counts_04,
            scanned_04,
            scope="04_marts",
            fallback_used=False,
        )
        return info, allowed

    counts_fb, scanned_fb = _reference_pii_counts_scoped(dbt_root, only_under_04_marts=False)
    info, allowed = _fill_bundle_counts(
        out,
        counts_fb,
        scanned_fb,
        scope="models_excl_migracao_sas",
        fallback_used=True,
    )
    return info, allowed


def infer_reference_pii_from_component(dbt_root: Path | None) -> dict[str, str | int]:
    """
    Conta ocorrências de `PII_INTERNO_*` (primeiro em ``04_marts``, depois fallback
    como em ``reference_pii_bundle``) e devolve o top-1 / top-2.
    """
    info, _ = reference_pii_bundle(dbt_root)
    return info


def reference_allowed_vars(dbt_root: Path | None) -> frozenset[str]:
    _, allowed = reference_pii_bundle(dbt_root)
    return allowed


def scan_migracao_sas_pii(
    migracao_root: Path | None,
    *,
    allowed_reference: frozenset[str],
) -> dict[str, str | int]:
    """
    Analisa YAMLs sob `migracao_root` (ex.: clone .../migracao_sas/<slug>/).
    Conta blocos com `policy_tags:` e recolhe `PII_INTERNO_*` usados.
    """
    out: dict[str, str | int] = {
        "pii_migracao_policy_tags_blocks": 0,
        "pii_migracao_vars": "",
        "pii_migracao_hits": 0,
        "pii_mismatch": "na",
    }
    if not migracao_root or not migracao_root.is_dir():
        return out
    counts: Counter[str] = Counter()
    tag_blocks = 0
    for yml in sorted(migracao_root.rglob("*.yml")):
        try:
            body = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tag_blocks += body.count("policy_tags:")
        for name in extract_pii_interno_var_names(body):
            counts[name] += 1
    out["pii_migracao_policy_tags_blocks"] = tag_blocks
    out["pii_migracao_hits"] = int(sum(counts.values()))
    if counts:
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out["pii_migracao_vars"] = ",".join(f"{k}:{v}" for k, v in ordered[:6])
    vars_set = frozenset(counts.keys())
    if not vars_set:
        out["pii_mismatch"] = "na"
    elif not allowed_reference:
        out["pii_mismatch"] = "na"
    elif vars_set.issubset(allowed_reference):
        out["pii_mismatch"] = "não"
    else:
        out["pii_mismatch"] = "sim"
    return out


def _truthy_yaml_bool(v: object) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "sim", "1", "on"):
            return True
        if s in ("false", "no", "não", "nao", "0", "off"):
            return False
    return None


def catalog_pii_reference_interno_strict(entry: dict, catalog: dict) -> bool:
    """
    Lê ``pii_reference_interno_strict`` na entrada do catálogo EGP, com fallback para ``defaults``.
    Usado por ``draft_gate`` / ``batch_pipeline.compute_batch_checks``.
    """
    defaults = catalog.get("defaults") if isinstance(catalog.get("defaults"), dict) else {}
    e = entry or {}
    for src in (e, defaults):
        if not isinstance(src, dict):
            continue
        raw = src.get("pii_reference_interno_strict")
        t = _truthy_yaml_bool(raw)
        if t is not None:
            return t
    return False

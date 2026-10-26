"""
Validação mecânica: draft com três camadas (staging / intermediate / marts)
e `materialized=` explícito por ficheiro, alinhado a 01_sas_to_dbt / 02_sas_to_databricks.

Usado por `draft_gate` e `batch_pipeline.compute_batch_checks`.
"""

from __future__ import annotations

import re
from pathlib import Path

DRAFT_LAYERS = ("staging", "intermediate", "marts")

# Valores literais entre aspas (SQL/Jinja ou Python).
_MATERIALIZED_QUOTED = re.compile(
    r"""\bmaterialized\s*=\s*(['\"])([\w_-]+)\1""",
    re.IGNORECASE,
)


def collect_layer_model_paths(models_dir: Path, layer: str) -> list[Path]:
    """Lista `.sql` e `.py` na raiz de `models/<layer>/` (não recursivo)."""
    base = models_dir / layer
    if not base.is_dir():
        return []
    files = list(base.glob("*.sql")) + list(base.glob("*.py"))
    return sorted(files, key=lambda p: str(p).lower())


def first_materialized_value(text: str) -> str | None:
    """Primeiro valor literal de `materialized=` no ficheiro (aspas simples ou duplas)."""
    m = _MATERIALIZED_QUOTED.search(text)
    if m:
        return m.group(2).lower()
    return None


def allowed_materialized_for_layer(layer: str, ta: str) -> frozenset[str]:
    if ta == "DBT_BQ":
        if layer == "staging":
            return frozenset({"ephemeral"})
        return frozenset({"table"})
    if ta == "DATABRICKS":
        if layer == "staging":
            return frozenset({"ephemeral", "view"})
        return frozenset({"table"})
    return frozenset()


def check_draft_three_layers_and_materialization(
    models_dir: Path,
    ta: str,
) -> tuple[bool, list[str], dict[str, int | bool]]:
    """
    Valida `models/staging`, `intermediate`, `marts` com ≥1 modelo cada e
    `materialized=` literal permitido por camada.

    Returns:
        (ok, errors, summary) — summary com contagens e materialization_ok.
    """
    summary: dict[str, int | bool] = {
        "staging_model_count": 0,
        "intermediate_model_count": 0,
        "marts_model_count": 0,
        "materialization_ok": False,
    }
    errors: list[str] = []

    if ta not in ("DBT_BQ", "DATABRICKS"):
        return True, [], summary

    if not models_dir.is_dir():
        errors.append(
            f"Draft sem pasta `models/`: {models_dir} — esperado `models/staging/`, "
            "`models/intermediate/` e `models/marts/` com modelos."
        )
        return False, errors, summary

    for layer in DRAFT_LAYERS:
        paths = collect_layer_model_paths(models_dir, layer)
        key = f"{layer}_model_count"
        summary[key] = len(paths)
        if len(paths) == 0:
            errors.append(
                f"Draft sem {layer}: não há `.sql`/`.py` em "
                f"`draft_models/<egp_key>/models/{layer}/` ({ta}). "
                "Crie ao menos um modelo nesta camada."
            )
            continue

        allowed = allowed_materialized_for_layer(layer, ta)
        allowed_s = ", ".join(sorted(allowed))
        for p in paths:
            try:
                body = p.read_text(encoding="utf-8", errors="replace")
            except OSError as ex:
                errors.append(f"Não foi possível ler `{p}`: {ex}")
                summary["materialization_ok"] = False
                continue
            mv = first_materialized_value(body)
            try:
                rel = p.relative_to(models_dir)
            except ValueError:
                rel = p
            rel_s = f"models/{rel.as_posix()}"
            if mv is None:
                summary["materialization_ok"] = False
                errors.append(
                    f"`{rel_s}`: falta `materialized=` com valor literal entre aspas "
                    f"(ex.: `materialized='table'` ou `materialized=\"view\"`). "
                    f"Camada `{layer}` ({ta}): valores permitidos: {allowed_s}."
                )
            elif mv not in allowed:
                summary["materialization_ok"] = False
                errors.append(
                    f"`{rel_s}`: `materialized='{mv}'` não permitido na camada `{layer}` ({ta}). "
                    f"Valores permitidos: {allowed_s}."
                )

    ok = len(errors) == 0
    summary["materialization_ok"] = ok
    return ok, errors, summary


def draft_three_layers_and_materialization_ok(models_dir: Path, ta: str) -> bool:
    ok, _, _ = check_draft_three_layers_and_materialization(models_dir, ta)
    return ok

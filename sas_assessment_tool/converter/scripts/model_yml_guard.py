#!/usr/bin/env python3
"""
Guardrail mecânico: paridade intermediate/mart ↔ `.yml` (irmão com o mesmo stem).

Alinhado a `.cursor/rules/01_sas_to_dbt.mdc` §5 e ao AGENTE 2 (um YAML por modelo int/mart).
Não aplica a `staging/` (sources agregados em `src_*.yml`).
"""

from __future__ import annotations

from pathlib import Path

LAYERS = ("intermediate", "marts")


def iter_int_mart_model_files(models_dir: Path) -> list[Path]:
    """Lista `.sql` e `.py` (Databricks) sob models/intermediate e models/marts."""
    out: list[Path] = []
    for layer in LAYERS:
        base = models_dir / layer
        if not base.is_dir():
            continue
        out.extend(sorted(base.rglob("*.sql")))
        out.extend(sorted(base.rglob("*.py")))
    # Ordem estável por caminho
    return sorted(out, key=lambda p: str(p).lower())


def check_int_mart_yml_pairing(models_dir: Path) -> tuple[list[str], int, int]:
    """
    Para cada modelo em intermediate/marts, exige ficheiro `stem.yml` no mesmo diretório.

    Returns:
        (missing_sql_paths, total_models, missing_count)
    """
    if not models_dir.is_dir():
        return [], 0, 0

    missing: list[str] = []
    files = iter_int_mart_model_files(models_dir)
    for f in files:
        yml = f.with_suffix(".yml")
        if not yml.is_file():
            missing.append(str(f.resolve()))
    return missing, len(files), len(missing)


def yml_pairing_ok(missing_count: int) -> bool:
    return missing_count == 0

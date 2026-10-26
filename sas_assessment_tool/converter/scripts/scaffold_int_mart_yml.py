#!/usr/bin/env python3
"""
Gera stem.yml mínimos em falta para modelos em models/intermediate e models/marts (draft).

MVP conservador: placeholders genéricos e columns: []. O AGENTE 2 / yml_documentation_guard
no sandbox continua a obrigar enriquecimento antes do destino final.

Uso (a partir de converter/):
  python -m scripts.scaffold_int_mart_yml --draft-root draft_models --egp-key MeuEgp
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .model_yml_guard import iter_int_mart_model_files


def _default_cron_for_path(model_path: Path) -> str:
    parts = {p.lower() for p in model_path.parts}
    if "marts" in parts:
        return "0 9 * * *"
    return "0 8 * * *"


def _minimal_yml_text(*, model_name: str, cron: str, egp_key: str) -> str:
    egp_note = f" EGP `{egp_key}`." if egp_key else ""
    return (
        "version: 2\n\n"
        "models:\n"
        f"  - name: {model_name}\n"
        f'    description: "TODO (scaffold automático): descrever propósito, granularidade e fontes.{egp_note}"\n'
        "    meta:\n"
        f'      cron: "{cron}"\n'
        "    columns: []\n"
    )


def scaffold_draft_models(models_dir: Path, *, egp_key: str = "") -> int:
    """
    Para cada .sql/.py em intermediate/marts sem stem.yml irmão, grava stem.yml mínimo.

    Returns:
        Número de ficheiros .yml criados.
    """
    if not models_dir.is_dir():
        return 0
    created = 0
    for sql_py in iter_int_mart_model_files(models_dir):
        yml = sql_py.with_suffix(".yml")
        if yml.is_file():
            continue
        stem = sql_py.stem
        cron = _default_cron_for_path(sql_py)
        yml.write_text(
            _minimal_yml_text(model_name=stem, cron=cron, egp_key=egp_key),
            encoding="utf-8",
        )
        created += 1
    return created


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scaffold stem.yml mínimos (intermediate/marts).")
    p.add_argument(
        "--draft-root",
        default=str(SCRIPT_DIR / "draft_models"),
        help="Raiz dos drafts (contém <egp_key>/models/)",
    )
    p.add_argument("--egp-key", required=True, metavar="KEY", help="egp_key (pasta sob draft-root)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models_dir = Path(args.draft_root) / args.egp_key / "models"
    n = scaffold_draft_models(models_dir, egp_key=args.egp_key)
    print(f"scaffold_int_mart_yml: criados {n} ficheiro(s) .yml em {models_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

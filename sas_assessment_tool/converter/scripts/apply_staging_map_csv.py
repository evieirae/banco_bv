#!/usr/bin/env python3
"""
Aplica um CSV operacional (staging_map.csv) no registry/egp_catalog.yaml.

Escopo (Opção A):
- Só atualiza entries já existentes no catálogo (egp_key deve existir).
- Preenche/atualiza staging_mode=reuse_existing e staging_ref_map:
    sas_or_source_id: "LIB.MEMBRO"
    ref_model: "stg_dvry_<schema>_<table>"

CSV esperado:
  egp_key,sas_table,bq_fqtn
  FECHAMENTO_CARDIF_ICATU,BASES.TBPRODUCAO,bv-pdbd-prd.trusted_negc_rodas.tbproducao
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .bootstrap_egp_catalog import DEFAULT_REGISTRY_PATH, index_entries, load_or_create_catalog, write_catalog


_SAS_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_BQ_FQTN_RE = re.compile(r"^[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class StagingMapRow:
    egp_key: str
    sas_table: str
    bq_fqtn: str

    @property
    def bq_schema(self) -> str:
        return self.bq_fqtn.split(".")[1]

    @property
    def bq_table(self) -> str:
        return self.bq_fqtn.split(".")[2]

    @property
    def ref_model(self) -> str:
        return f"stg_dvry_{self.bq_schema}_{self.bq_table}"


def read_staging_map_csv(csv_path: Path) -> list[StagingMapRow]:
    if not csv_path.is_file():
        raise ValueError(f"CSV não encontrado: {csv_path}")
    rows: list[StagingMapRow] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"egp_key", "sas_table", "bq_fqtn"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"CSV inválido: colunas obrigatórias = {sorted(required)}; encontrado = {reader.fieldnames}"
            )
        for i, raw in enumerate(reader, start=2):
            egp_key = str(raw.get("egp_key") or "").strip()
            sas_table = str(raw.get("sas_table") or "").strip()
            bq_fqtn = str(raw.get("bq_fqtn") or "").strip()
            if not egp_key:
                raise ValueError(f"CSV inválido (linha {i}): egp_key vazio")
            if not _SAS_TABLE_RE.match(sas_table):
                raise ValueError(f"CSV inválido (linha {i}): sas_table inválido: {sas_table!r} (esperado LIB.MEMBRO)")
            if not _BQ_FQTN_RE.match(bq_fqtn):
                raise ValueError(
                    f"CSV inválido (linha {i}): bq_fqtn inválido: {bq_fqtn!r} (esperado projeto.schema.tabela)"
                )
            rows.append(StagingMapRow(egp_key=egp_key, sas_table=sas_table.upper(), bq_fqtn=bq_fqtn))
    return rows


def apply_rows_to_catalog_entry(entry: dict, rows: list[StagingMapRow]) -> bool:
    """
    Aplica mapeamentos no entry. Retorna True se algo mudou.
    """
    changed = False
    if entry.get("staging_mode") != "reuse_existing":
        entry["staging_mode"] = "reuse_existing"
        changed = True

    srm = entry.get("staging_ref_map")
    if not isinstance(srm, list):
        srm = []
        entry["staging_ref_map"] = srm
        changed = True

    # index existing by sas_or_source_id
    by_sas: dict[str, dict] = {}
    for item in srm:
        if isinstance(item, dict):
            k = str(item.get("sas_or_source_id") or "").strip().upper()
            if k:
                by_sas[k] = item

    for r in rows:
        existing = by_sas.get(r.sas_table)
        if existing is None:
            srm.append({"sas_or_source_id": r.sas_table, "ref_model": r.ref_model})
            changed = True
        else:
            if str(existing.get("ref_model") or "").strip() != r.ref_model:
                existing["ref_model"] = r.ref_model
                changed = True

    return changed


def apply_staging_map_csv(*, egp_key: str, csv_path: Path, catalog_path: Path) -> bool:
    """
    Aplica o CSV para um egp_key específico. Retorna True se o catálogo foi alterado.
    """
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog.get("entries") or [])
    entry = by_key.get(egp_key)
    if not entry:
        raise ValueError(
            f"egp_key não encontrado no catálogo: {egp_key!r}. Rode `python -m scripts.bootstrap_egp_catalog scan/add` primeiro."
        )

    rows = [r for r in read_staging_map_csv(csv_path) if r.egp_key == egp_key]
    if not rows:
        return False

    changed = apply_rows_to_catalog_entry(entry, rows)
    if changed:
        write_catalog(catalog, catalog_path)
    return changed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aplica registry/staging_map.csv no registry/egp_catalog.yaml (Opção A).")
    p.add_argument("egp_key", help="EGP key existente no catálogo.")
    p.add_argument(
        "--csv",
        default="registry/staging_map.csv",
        help="Caminho do staging_map.csv (default: registry/staging_map.csv).",
    )
    p.add_argument(
        "--catalog",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"egp_catalog.yaml (default: {DEFAULT_REGISTRY_PATH})",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        changed = apply_staging_map_csv(
            egp_key=str(args.egp_key).strip(),
            csv_path=Path(args.csv),
            catalog_path=Path(args.catalog),
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if changed:
        print("[apply_staging_map_csv] OK: catálogo atualizado")
    else:
        print("[apply_staging_map_csv] OK: sem alterações (sem linhas no CSV para este egp_key)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


#!/usr/bin/env python3
"""
Preflight: verifica se o staging canónico (ref_model do catálogo) expõe as colunas usadas no SAS (text_egps/*.txt).

Estratégia fixa (contrato do time): se faltar coluna → ação recomendada = extend_canonical.

Saída:
- stdout (sempre)
- opcional: escreve draft_models/<egp_key>/STAGING_PREFLIGHT_REPORT.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .bootstrap_egp_catalog import DEFAULT_REGISTRY_PATH, index_entries, load_or_create_catalog, resolve_dbt_project_root
from .draft_gate import DEFAULT_DRAFT_ROOT, DEFAULT_TEXT_EGPS
from .generate_migration_spec import resolve_workspace_subdir_and_model_path


_T1_COL_RE = re.compile(r"(?i)\bt1\.([a-z_][a-z0-9_]*)\b")
_CLOSED_PAREN_ALIAS_RE = re.compile(r"(?i)\)\s+as\s+([a-z_][a-z0-9_]*)\b")
_CAST_SRC_ALIAS_RE = re.compile(
    r"(?i)\bcast\(\s*([a-z_][a-z0-9_]*)\s+as\s+([a-z0-9_]+)\s*\)\s+as\s+([a-z_][a-z0-9_]*)\b"
)

_BQ_TYPES = {
    "string",
    "int64",
    "numeric",
    "bignumeric",
    "float64",
    "boolean",
    "date",
    "datetime",
    "timestamp",
}


@dataclass(frozen=True)
class PreflightResult:
    egp_key: str
    sas_table: str
    bq_schema: str
    bq_table: str
    ref_model: str
    staging_path: str
    needed_columns: list[str]
    exposed_columns: list[str]
    missing_columns: list[str]
    action: str


def _parse_sas_table(s: str) -> tuple[str, str]:
    parts = [p.strip() for p in str(s).split(".", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"sas_table inválido: {s!r} (esperado LIB.MEMBRO)")
    return parts[0].upper(), parts[1].upper()


def _infer_schema_table_from_ref_model(ref_model: str) -> tuple[str, str]:
    """
    Ref_model esperado: stg_dvry_<schema>_<table>
    """
    stem = ref_model.strip()
    prefix = "stg_dvry_"
    if not stem.startswith(prefix):
        raise ValueError(f"ref_model fora do padrão stg_dvry_<schema>_<table>: {ref_model!r}")
    rest = stem[len(prefix) :]
    parts = rest.split("_")
    if len(parts) < 2:
        raise ValueError(f"ref_model fora do padrão stg_dvry_<schema>_<table>: {ref_model!r}")
    schema = "_".join(parts[:-1])
    table = parts[-1]
    return schema, table


def extract_needed_columns_from_txt(txt_path: Path) -> list[str]:
    if not txt_path.is_file():
        raise ValueError(f".txt não encontrado: {txt_path}")
    txt = txt_path.read_text(encoding="utf-8", errors="replace")
    cols = sorted({m.group(1).lower() for m in _T1_COL_RE.finditer(txt)})
    return cols


def extract_exposed_aliases_from_staging_sql(staging_path: Path) -> list[str]:
    if not staging_path.is_file():
        raise ValueError(f"staging .sql não encontrado: {staging_path}")
    sql = staging_path.read_text(encoding="utf-8", errors="replace")
    # Heurística: pegar aliases após ") as <alias>" e filtrar tipos conhecidos (evita pegar "as string" dentro do CAST).
    aliases = sorted(
        {
            m.group(1).lower()
            for m in _CLOSED_PAREN_ALIAS_RE.finditer(sql)
            if m.group(1) and m.group(1).lower() not in _BQ_TYPES
        }
    )
    return aliases


def extract_cast_source_to_alias_map(staging_path: Path) -> dict[str, str]:
    """
    Extrai pares (source_col -> alias) de padrões:
      cast(source_col as <type>) as alias
    """
    sql = staging_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for m in _CAST_SRC_ALIAS_RE.finditer(sql):
        src = (m.group(1) or "").strip().lower()
        _typ = (m.group(2) or "").strip().lower()
        alias = (m.group(3) or "").strip().lower()
        if not src or not alias:
            continue
        # Se houver duplicidade, o último ganha (staging canónico deve ser consistente).
        out[src] = alias
    return out


def resolve_staging_sql_path(*, converter_dir: Path, catalog: dict, entry: dict, ref_model: str) -> Path:
    dbt_root = resolve_dbt_project_root(converter_dir, catalog, entry)
    area = str(entry.get("area") or "")
    workspace_subdir, model_path = resolve_workspace_subdir_and_model_path(dbt_root, area=area)
    schema, _table = _infer_schema_table_from_ref_model(ref_model)

    # Convenção: models/workspace/<workspace_subdir>/01_staging/<schema>/<ref_model>.sql
    candidate = dbt_root / model_path / "workspace" / workspace_subdir / "01_staging" / schema / f"{ref_model}.sql"
    if candidate.is_file():
        return candidate

    # Fallback: procurar em workspace/<workspace_subdir> qualquer 01_staging/**/<ref_model>.sql
    ws_root = dbt_root / model_path / "workspace" / workspace_subdir
    hits = list(ws_root.glob(f"01_staging/**/{ref_model}.sql"))
    if hits:
        return hits[0]

    raise ValueError(f"Não foi possível localizar o staging canónico: {ref_model}.sql sob {ws_root}")


def build_report_md(r: PreflightResult) -> str:
    lines = [
        f"# STAGING_PREFLIGHT_REPORT — `{r.egp_key}`",
        "",
        "## Summary",
        "",
        f"- **EGP:** `{r.egp_key}`",
        f"- **SAS table:** `{r.sas_table}`",
        f"- **BQ (inferido por naming):** `{r.bq_schema}.{r.bq_table}`",
        f"- **ref_model (catálogo):** `{r.ref_model}`",
        f"- **staging_path:** `{r.staging_path}`",
        f"- **Action (contrato):** `{r.action}`",
        "",
        "## Columns",
        "",
        f"- **needed_columns (SAS heuristic, t1.<col>):** {', '.join(r.needed_columns) if r.needed_columns else '(none)'}",
        f"- **exposed_columns (staging aliases):** {', '.join(r.exposed_columns) if r.exposed_columns else '(none)'}",
        f"- **missing_columns:** {', '.join(r.missing_columns) if r.missing_columns else '(none)'}",
        "",
        "## Notes",
        "",
        "- Este preflight é heurístico (regex). Ele serve para detectar cedo discrepâncias entre o SAS e o staging canónico.",
        "- Se `missing_columns` não estiver vazio, a ação recomendada é **alargar** o staging canónico (extend_canonical).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preflight de colunas: SAS txt vs staging canónico do componente.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument("--catalog", default=str(DEFAULT_REGISTRY_PATH), help="egp_catalog.yaml")
    ap.add_argument("--sas-table", default="BASES.TBPRODUCAO", help="SAS table a validar (default: BASES.TBPRODUCAO)")
    ap.add_argument("--txt", default=None, help="text_egps/<egp_key>.txt (default: text_egps/<egp_key>.txt)")
    ap.add_argument("--write-report", action="store_true", help="Escreve draft_models/<egp_key>/STAGING_PREFLIGHT_REPORT.md")
    args = ap.parse_args()

    egp_key = str(args.egp_key).strip()
    sas_table = str(args.sas_table).strip().upper()
    _lib, _member = _parse_sas_table(sas_table)

    catalog_path = Path(args.catalog)
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog.get("entries") or [])
    entry = by_key.get(egp_key)
    if not entry:
        print(
            f"egp_key não encontrado no catálogo: {egp_key!r}. Rode `python -m scripts.bootstrap_egp_catalog scan/add`.",
            file=sys.stderr,
        )
        return 1

    srm = entry.get("staging_ref_map") or []
    ref_model = None
    if isinstance(srm, list):
        for item in srm:
            if not isinstance(item, dict):
                continue
            if str(item.get("sas_or_source_id") or "").strip().upper() == sas_table:
                ref_model = str(item.get("ref_model") or "").strip()
                break
    if not ref_model:
        print(
            f"staging_ref_map não possui mapeamento para {sas_table!r} em {egp_key!r}. "
            "Aplique o CSV antes (apply_staging_map_csv).",
            file=sys.stderr,
        )
        return 1

    converter_dir = DEFAULT_DRAFT_ROOT.parent
    try:
        staging_path = resolve_staging_sql_path(converter_dir=converter_dir, catalog=catalog, entry=entry, ref_model=ref_model)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    txt_path = Path(args.txt) if args.txt else (DEFAULT_TEXT_EGPS / f"{egp_key}.txt")
    try:
        needed_cols = extract_needed_columns_from_txt(txt_path)
        exposed_cols = extract_exposed_aliases_from_staging_sql(staging_path)
        cast_map = extract_cast_source_to_alias_map(staging_path)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    schema, table = _infer_schema_table_from_ref_model(ref_model)
    # Considera como "coberto" se:
    # - a coluna aparece como alias exposto no staging (ex.: já está em snake_case), OU
    # - a coluna é coluna de origem do CAST e portanto vira alias (ex.: nuanomes -> nu_ano_mes).
    exposed_set = set(exposed_cols)
    cast_src_set = set(cast_map.keys())
    missing = sorted([c for c in needed_cols if c not in exposed_set and c not in cast_src_set])

    result = PreflightResult(
        egp_key=egp_key,
        sas_table=sas_table,
        bq_schema=schema,
        bq_table=table,
        ref_model=ref_model,
        staging_path=str(staging_path),
        needed_columns=needed_cols,
        exposed_columns=exposed_cols,
        missing_columns=missing,
        action="extend_canonical",
    )

    report = build_report_md(result)
    print(report)

    if args.write_report:
        out_path = DEFAULT_DRAFT_ROOT / egp_key / "STAGING_PREFLIGHT_REPORT.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\n[staging_preflight] report escrito em: {out_path}")

    # Exit code: 0 se ok, 2 se houver missing (para facilitar CI/automação)
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())


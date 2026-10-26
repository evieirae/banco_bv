"""
PASSO 3 helper: inject or refresh dbt ``config(...)`` labels in intermediate + marts.

- Injects full governance block when no ``labels`` dict is present.
- Refreshes in-place: ``nm_engenheiro_responsavel_pela_transformacao``,
  ``nm_grupo_de_acesso``, ``fl_modernizacao_legacy`` (sempre ``'false'``;
  corrige modelos antigos com ``'true'``). Não altera ``nm_delivery_legacy``:
  o inject deixa ``''`` como último recurso — o Agente 2 deve preencher antes
  do merge conforme ``01_sas_to_dbt.mdc`` §4 (formato ``sas__<tabela>``
  minúsculo, sem ``[SAS]``/libref/``WORK.``, com a tabela SAS principal; ver
  regras).

``nm_grupo_de_acesso`` default: ``pdbd_gcp-<workspace_subdir>-dados_interno``, where
``workspace_subdir`` is the first path segment after ``workspace/`` in the clone layout.

Resolution order for ``workspace_subdir`` (when grupo is not overridden):

1. ``dbt_clone_dest`` in ``MIGRATION_SPEC.md``;
2. any ``.../workspace/<subdir>/...`` in the resolved ``--models-root`` path;
3. ``resolve_workspace_subdir_and_model_path`` on the dbt component from ``egp_catalog``.

Never touches staging models.

Run from ``converter/`` (or set cwd so ``registry/`` resolves).
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from .bootstrap_egp_catalog import (
    DEFAULT_REGISTRY_PATH,
    SCRIPT_DIR,
    index_entries,
    load_or_create_catalog,
    resolve_dbt_project_root,
)
from .generate_migration_spec import resolve_workspace_subdir_and_model_path
from .sandbox_layout import find_converted_sandbox

_RE_SPEC_EGP_SLUG = re.compile(r"^egp_slug:\s*(.+?)\s*$", re.MULTILINE)
_RE_SPEC_CD_GOV = re.compile(r"^cd_governanca:\s*'?(\d+)'?\s*$", re.MULTILINE)
_RE_DBT_CLONE_DEST = re.compile(r"^dbt_clone_dest:\s*(.+?)\s*$", re.MULTILINE)


def _read_spec(spec_path: Path) -> tuple[str, str]:
    text = spec_path.read_text(encoding="utf-8")
    m_slug = _RE_SPEC_EGP_SLUG.search(text)
    m_cd = _RE_SPEC_CD_GOV.search(text)
    if not m_slug or not m_cd:
        raise SystemExit(
            f"[apply_governance_config] não foi possível ler egp_slug/cd_governanca de {spec_path}"
        )
    return m_slug.group(1).strip(), m_cd.group(1).strip()


def workspace_subdir_from_path(path_like: str) -> str | None:
    norm = path_like.replace("\\", "/")
    m = re.search(r"/workspace/([^/]+)/", norm)
    return m.group(1) if m else None


def _parse_dbt_clone_dest(spec_text: str) -> str | None:
    m = _RE_DBT_CLONE_DEST.search(spec_text)
    if not m:
        return None
    return m.group(1).strip()


def resolve_workspace_subdir_for_grupo(
    *,
    spec_text: str,
    models_root: Path,
    egp_key: str,
) -> str:
    clone = _parse_dbt_clone_dest(spec_text)
    if clone:
        seg = workspace_subdir_from_path(clone)
        if seg:
            return seg

    seg = workspace_subdir_from_path(str(models_root.resolve()))
    if seg:
        return seg

    catalog_path = DEFAULT_REGISTRY_PATH
    if not catalog_path.is_file():
        raise SystemExit(
            "[apply_governance_config] não foi possível inferir workspace_subdir: "
            f"sem dbt_clone_dest útil no spec, path sem /workspace/<subdir>/, e sem {catalog_path}"
        )
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog["entries"])
    entry = by_key.get(egp_key)
    if not entry:
        raise SystemExit(f"[apply_governance_config] egp_key não encontrado no catálogo: {egp_key!r}")
    area_str = str(entry.get("area") or "")
    try:
        dbt_root = resolve_dbt_project_root(SCRIPT_DIR, catalog, entry)
    except ValueError as e:
        raise SystemExit(f"[apply_governance_config] {e}") from e
    if not (dbt_root / "dbt_project.yml").is_file():
        raise SystemExit(
            "[apply_governance_config] fallback catálogo requer clone dbt com dbt_project.yml em "
            f"{dbt_root}"
        )
    workspace_subdir, _mp = resolve_workspace_subdir_and_model_path(dbt_root, area=area_str)
    if not workspace_subdir.strip():
        raise SystemExit("[apply_governance_config] workspace_subdir vazio após resolução.")
    return workspace_subdir.strip()


def nm_grupo_from_workspace_subdir(workspace_subdir: str) -> str:
    return f"pdbd_gcp-{workspace_subdir}-dados_interno"


def _replace_single_quoted_label(text: str, key: str, new_val: str) -> tuple[str, bool]:
    pat = re.compile(rf"('{re.escape(key)}'\s*:\s*)'[^']*'", re.MULTILINE)
    new_text, n = pat.subn(rf"\1'{new_val}'", text, count=1)
    return new_text, n > 0


def _replace_double_quoted_label(text: str, key: str, new_val: str) -> tuple[str, bool]:
    pat = re.compile(rf'("{re.escape(key)}"\s*:\s*)"[^"]*"', re.MULTILINE)
    new_text, n = pat.subn(rf'\1"{new_val}"', text, count=1)
    return new_text, n > 0


def _refresh_labels_in_file(text: str, *, engineer: str, nm_grupo: str) -> tuple[str, bool]:
    t = text
    any_change = False
    for key, val in (
        ("nm_engenheiro_responsavel_pela_transformacao", engineer),
        ("nm_grupo_de_acesso", nm_grupo),
        ("fl_modernizacao_legacy", "false"),
    ):
        t2, ch = _replace_single_quoted_label(t, key, val)
        if not ch:
            t2, ch = _replace_double_quoted_label(t, key, val)
        if ch:
            any_change = True
        t = t2
    return t, any_change


def _has_labels_block(text: str) -> bool:
    if "labels={" in text:
        return True
    if re.search(r"labels\s*=\s*\{", text):
        return True
    return False


def _config_block(
    *,
    layer: str,
    egp_slug: str,
    cd_governanca: str,
    engineer: str,
    nm_grupo: str,
) -> str:
    return (
        "{{\n"
        "    config(\n"
        "        materialized='table',\n"
        f"        tags=['{layer}', '{egp_slug}', 'migracao_egp', 'migracao_sas'],\n"
        "        labels={\n"
        f"            'cd_governanca': '{cd_governanca}',\n"
        "            'ds_classificacao_de_acesso': 'interno',\n"
        f"            'nm_grupo_de_acesso': '{nm_grupo}',\n"
        f"            'nm_engenheiro_responsavel_pela_transformacao': '{engineer}',\n"
        "            'tp_selo_qualidade_dados_requerido': 'bronze',\n"
        "            'fl_contem_pii': 'false',\n"
        "            'fl_modernizacao_legacy': 'false',\n"
        "            'nm_delivery_legacy': ''\n"
        "        }\n"
        "    )\n"
        "}}\n"
    )


def _apply_to_file(
    path: Path,
    *,
    layer: str,
    egp_slug: str,
    cd_governanca: str,
    engineer: str,
    nm_grupo: str,
) -> bool:
    original = path.read_text(encoding="utf-8")
    if _has_labels_block(original):
        new_text, changed = _refresh_labels_in_file(original, engineer=engineer, nm_grupo=nm_grupo)
        if changed:
            path.write_text(new_text, encoding="utf-8")
        return changed

    block = _config_block(
        layer=layer,
        egp_slug=egp_slug,
        cd_governanca=cd_governanca,
        engineer=engineer,
        nm_grupo=nm_grupo,
    )

    replacements = (
        "{{ config(materialized='table') }}",
        "{{config(materialized='table')}}",
        "{{ config(materialized = 'table') }}",
        "{{ config(materialized=\"table\") }}",
    )

    text = original
    for candidate in replacements:
        if candidate in text:
            text = text.replace(candidate, block.rstrip("\n"), 1)
            break
    else:
        text = block + "\n" + text.lstrip()

    path.write_text(text, encoding="utf-8")
    return True


def _resolve_engineer(args: argparse.Namespace) -> str:
    engineer = (args.engineer or "").strip()
    if not engineer:
        engineer = (os.getenv("CONVERTER_ENGINEER") or "").strip()
    if not engineer:
        profile_path = SCRIPT_DIR / "registry" / "user_profile.local.yaml"
        if yaml is not None and profile_path.is_file():
            try:
                prof = yaml.safe_load(profile_path.read_text(encoding="utf-8", errors="replace")) or {}
                engineer = str(prof.get("engineer") or "").strip()
            except Exception:
                engineer = ""
    if not engineer:
        engineer = "int_unknown"
    return engineer


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Inject or refresh governance labels in sandbox intermediate/marts SQL models "
        "(engineer, grupo, fl_modernizacao_legacy=false; nm_delivery_legacy not auto-filled)."
    )
    ap.add_argument("egp_key", help="EGP key (nome do projeto)")
    ap.add_argument(
        "--target-arch",
        default="dbt",
        help="Sandbox folder under converted_egps/ (ex.: dbt). Ignored for models path if --models-root.",
    )
    ap.add_argument(
        "--spec",
        default=None,
        help="MIGRATION_SPEC.md (default: sandbox resolvido / legado / DATA_SHA_target → <egp_key>/MIGRATION_SPEC.md)",
    )
    ap.add_argument(
        "--models-root",
        default=None,
        help="Pasta com intermediate/ e marts/ (default: <sandbox>/models). Use o models/ do clone para refrescar só lá.",
    )
    ap.add_argument(
        "--engineer",
        default=None,
        help="Override. Default: CONVERTER_ENGINEER > registry/user_profile.local.yaml > int_unknown",
    )
    ap.add_argument(
        "--nm-grupo-de-acesso",
        dest="nm_grupo_de_acesso",
        default=None,
        help="Override exceção. Default: pdbd_gcp-<workspace_subdir>-dados_interno (ver docstring). "
        "Env: CONVERTER_NM_GRUPO_DE_ACESSO",
    )
    args = ap.parse_args()

    engineer = _resolve_engineer(args)

    nm_grupo_override = (args.nm_grupo_de_acesso or "").strip()
    if not nm_grupo_override:
        nm_grupo_override = (os.getenv("CONVERTER_NM_GRUPO_DE_ACESSO") or "").strip()

    _, resolved_sandbox = find_converted_sandbox(SCRIPT_DIR, args.egp_key)
    if resolved_sandbox is not None:
        sandbox_root = resolved_sandbox
    else:
        sandbox_root = SCRIPT_DIR / "converted_egps" / args.target_arch / args.egp_key
    spec_path = Path(args.spec) if args.spec else (sandbox_root / "MIGRATION_SPEC.md")
    models_root = Path(args.models_root) if args.models_root else (sandbox_root / "models")

    if not spec_path.is_file():
        raise SystemExit(f"[apply_governance_config] MIGRATION_SPEC em falta: {spec_path}")
    if not models_root.is_dir():
        raise SystemExit(f"[apply_governance_config] models-root em falta: {models_root}")

    spec_text = spec_path.read_text(encoding="utf-8", errors="replace")
    egp_slug, cd_governanca = _read_spec(spec_path)

    if nm_grupo_override:
        nm_grupo = nm_grupo_override
    else:
        ws = resolve_workspace_subdir_for_grupo(
            spec_text=spec_text,
            models_root=models_root,
            egp_key=args.egp_key,
        )
        nm_grupo = nm_grupo_from_workspace_subdir(ws)

    scanned = 0
    changed = 0
    for layer in ("intermediate", "marts"):
        layer_dir = models_root / layer
        if not layer_dir.is_dir():
            continue
        for path in sorted(layer_dir.glob("*.sql")):
            scanned += 1
            if _apply_to_file(
                path,
                layer=layer,
                egp_slug=egp_slug,
                cd_governanca=cd_governanca,
                engineer=engineer,
                nm_grupo=nm_grupo,
            ):
                changed += 1

    print(
        f"[apply_governance_config] ok scanned={scanned} changed={changed} "
        f"models_root={models_root} nm_grupo_de_acesso={nm_grupo!r} engineer={engineer!r}"
    )


if __name__ == "__main__":
    main()

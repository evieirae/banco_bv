#!/usr/bin/env python3
"""
Gera ou atualiza registry/egp_catalog.yaml (operacional) a partir de EGPs e área.

Não altera egp_catalog.example.yaml — use-o só como referência ou fonte de defaults.

Resolução da pasta do dbt: ver ``resolve_dbt_project_root(converter_dir, catalog, entry)``
(``defaults.dbt_project_path`` + ``componente_dbt``, ou ``entry.dbt_project_path`` como override).

Uso típico (a partir da raiz do repo converter/):
  python -m scripts.bootstrap_egp_catalog scan --area cobranca --componente dbt-srcg-anlt-plataforma
  python -m scripts.bootstrap_egp_catalog scan --area cobranca   # componente via registry/area_componente_dbt.yaml
  python -m scripts.bootstrap_egp_catalog scan   # EGPs em received_egps/<slug>/*.egp: area e egp_file inferidos
  python -m scripts.bootstrap_egp_catalog add "meu_job.egp" --area cobranca --componente dbt-srcg-anlt-plataforma
  python -m scripts.bootstrap_egp_catalog ensure-repo --componente dbt-srcg-anlt-plataforma
  python -m scripts.bootstrap_egp_catalog ensure-repo --area cobranca
  python -m scripts.bootstrap_egp_catalog list
  python -m scripts.bootstrap_egp_catalog resolve <egp_key>
  python -m scripts.bootstrap_egp_catalog governance-cd <egp_key>   # cd_governanca (labels dbt)
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:
    print("Instale PyYAML: pip install pyyaml", file=sys.stderr)
    raise SystemExit(1) from e

CONVERTER_DIR = Path(__file__).resolve().parents[1]
# Compat: outros módulos importam SCRIPT_DIR como raiz do repo.
SCRIPT_DIR = CONVERTER_DIR
DEFAULT_REGISTRY_PATH = CONVERTER_DIR / "registry" / "egp_catalog.yaml"
EXAMPLE_PATH = CONVERTER_DIR / "registry" / "egp_catalog.example.yaml"
DEFAULT_GOVERNANCE_MAP_PATH = CONVERTER_DIR / "registry" / "area_cd_governanca.yaml"
DEFAULT_AREA_COMPONENTE_PATH = CONVERTER_DIR / "registry" / "area_componente_dbt.yaml"
EXAMPLE_AREA_COMPONENTE_PATH = CONVERTER_DIR / "registry" / "area_componente_dbt.example.yaml"
DEFAULT_EGP_DIR = CONVERTER_DIR / "received_egps"

STAGING_MODE_CHOICES = ("reuse_existing", "generate_new", "hybrid")

HEADER_LINES = (
    "# Catálogo EGP → área + componente dbt (operacional).",
    "# Gerado ou atualizado por bootstrap_egp_catalog.py — ajuste campos finos à mão se necessário.",
    "",
)


def _load_yaml(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _defaults_from_example() -> dict:
    data = _load_yaml(EXAMPLE_PATH)
    if data and isinstance(data.get("defaults"), dict):
        return dict(data["defaults"])
    return {
        "staging_mode": "reuse_existing",
        "target_arch_override": None,
        "dbt_project_path": "converted_egps",
    }


def _empty_catalog() -> dict:
    return {
        "schema_version": 1,
        "defaults": _defaults_from_example(),
        "entries": [],
    }


def load_or_create_catalog(output_path: Path) -> dict:
    data = _load_yaml(output_path)
    if data is None:
        return _empty_catalog()
    if "schema_version" not in data:
        data["schema_version"] = 1
    if "defaults" not in data or not isinstance(data["defaults"], dict):
        data["defaults"] = _defaults_from_example()
    if "entries" not in data or not isinstance(data["entries"], list):
        data["entries"] = []
    return data


def load_area_componente_registry(path: Path) -> dict:
    """
    Lê registry/area_componente_dbt.yaml.

    Retorna dict com:
      - areas: slug -> componente_dbt (string)
      - components: nome_pasta -> dict com git_url, git_ref, ...
    """
    data = _load_yaml(path) or {}
    areas_raw = data.get("areas") or {}
    areas: dict[str, str] = {}
    for k, v in areas_raw.items():
        if v is None:
            continue
        key = str(k).strip()
        if not key:
            continue
        if isinstance(v, dict):
            comp = v.get("componente_dbt") or v.get("componente")
            if comp:
                areas[key] = str(comp).strip().strip("/\\")
        else:
            areas[key] = str(v).strip().strip("/\\")
    components_raw = data.get("components") or {}
    components: dict[str, dict] = {}
    for name, meta in components_raw.items():
        if not isinstance(meta, dict):
            continue
        nm = str(name).strip().strip("/\\")
        if nm:
            components[nm] = dict(meta)
    return {"areas": areas, "components": components, "raw": data}


def resolve_componente_for_area(area_slug: str, area_map_path: Path) -> tuple[str | None, dict | None]:
    if not area_map_path.is_file():
        return None, None
    reg = load_area_componente_registry(area_map_path)
    comp = reg["areas"].get(str(area_slug).strip())
    if not comp:
        return None, None
    meta = reg["components"].get(comp) or {}
    return comp, meta


def _resolve_componente_cli_or_map(
    area: str, component_cli: str | None, area_map_path: Path
) -> str | None:
    if component_cli is not None and str(component_cli).strip():
        return str(component_cli).strip().strip("/\\")
    comp, _ = resolve_componente_for_area(area, area_map_path)
    return comp


def component_repo_root(catalog: dict, componente_dbt: str) -> Path:
    defaults = catalog.get("defaults") or {}
    rel_base = str(defaults.get("dbt_project_path") or "converted_egps").strip().strip("/\\")
    comp = str(componente_dbt).strip().strip("/\\")
    return (CONVERTER_DIR / rel_base / comp).resolve()


def _run_git(git_args: list[str], cwd: Path | None) -> tuple[int, str]:
    r = subprocess.run(
        ["git", *git_args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def load_governance_map(path: Path) -> tuple[dict[str, str], str]:
    """
    Carrega ``area_cd_governanca.yaml`` (ou vazio se inexistente).

    Retorna (mapa area_slug -> código string, default_cd_governanca).
    """
    data = _load_yaml(path)
    if not data:
        return {}, "99"
    default_cd = data.get("default_cd_governanca")
    default_cd = str(default_cd).strip() if default_cd is not None else "99"
    raw = data.get("area_cd_governanca")
    if not isinstance(raw, dict):
        return {}, default_cd
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k is None or v is None:
            continue
        key = str(k).strip()
        if not key:
            continue
        out[key] = str(v).strip()
    return out, default_cd


def resolve_cd_governanca(area: str | None, gov_map: dict[str, str], default_cd: str) -> str:
    """Código de governança para labels dbt a partir do slug ``area`` do catálogo."""
    if not area or not str(area).strip():
        return default_cd
    key = str(area).strip()
    return gov_map.get(key, default_cd)


def resolve_dbt_project_root(converter_dir: Path | str, catalog: dict, entry: dict) -> Path:
    """
    Caminho absoluto da raiz do projeto dbt para uma entrada do catálogo.

    Padrão: ``converter_dir / defaults.dbt_project_path / entry.componente_dbt``
    (ex.: .../converter/converted_egps/dbt-srcg-anlt-plataforma).

    Override: se ``entry`` tiver ``dbt_project_path``, retorna só
    ``converter_dir / entry['dbt_project_path']`` (sem concatenar ``componente_dbt``).
    """
    base_conv = Path(converter_dir)

    override = entry.get("dbt_project_path")
    if override is not None and str(override).strip():
        return (base_conv / str(override).strip()).resolve()

    defaults = catalog.get("defaults") or {}
    rel_base = defaults.get("dbt_project_path") or "converted_egps"
    rel_base = str(rel_base).strip().strip("/\\")

    comp = entry.get("componente_dbt")
    if not comp or not str(comp).strip():
        raise ValueError(
            "entrada do catálogo sem componente_dbt e sem dbt_project_path de override"
        )
    comp = str(comp).strip().strip("/\\")
    return (base_conv / rel_base / comp).resolve()


def egp_key_from_name(name: str) -> tuple[str, str]:
    """Retorna (egp_key, egp_file) com extensão .egp garantida no arquivo."""
    name = name.strip()
    if name.lower().endswith(".egp"):
        return name[:-4], name
    return name, f"{name}.egp"


def index_entries(entries: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, row in enumerate(entries):
        if not isinstance(row, dict):
            continue
        key = row.get("egp_key")
        if key:
            out[str(key)] = row
    return out


def write_catalog(output_path: Path, data: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    with output_path.open("w", encoding="utf-8") as f:
        for line in HEADER_LINES:
            f.write(line + "\n")
        f.write(text)


def cmd_scan(args: argparse.Namespace) -> int:
    from .egps_extractor import infer_business_area_from_egp_path

    egp_dir = Path(args.egp_dir).resolve()
    if not egp_dir.is_dir():
        print(f"Diretório não encontrado: {egp_dir}", file=sys.stderr)
        return 1

    catalog = load_or_create_catalog(Path(args.output))
    if args.defaults_from_example:
        catalog["defaults"] = _defaults_from_example()
    if getattr(args, "defaults_staging_mode", None):
        catalog.setdefault("defaults", _defaults_from_example())
        catalog["defaults"]["staging_mode"] = args.defaults_staging_mode

    by_key = index_entries(catalog["entries"])
    area_map_path = Path(args.area_map)

    scan_paths = sorted(set(egp_dir.glob("*.egp")) | set(egp_dir.glob("*/*.egp")))
    if not scan_paths:
        print(f"Nenhum .egp em {egp_dir} (*.egp ou */*.egp).", file=sys.stderr)
        return 1

    flat_fallback = (args.area or "").strip() or None
    planned: list[tuple[Path, str, str, str, str]] = []
    for egp_path in scan_paths:
        egp_key, _ = egp_key_from_name(egp_path.name)
        rel = egp_path.relative_to(egp_dir)
        egp_file = rel.as_posix() if len(rel.parts) > 1 else rel.name
        area_slug = infer_business_area_from_egp_path(egp_path, received_root=egp_dir)
        if not area_slug:
            area_slug = flat_fallback
        if not area_slug:
            print(
                "scan: com EGPs directamente na raiz de --egp-dir é obrigatório --area <slug> "
                f"(ficheiro: {egp_path}).",
                file=sys.stderr,
            )
            return 1
        resolved_comp = _resolve_componente_cli_or_map(area_slug, args.componente, area_map_path)
        if not resolved_comp:
            print(
                f"scan: sem componente_dbt para area={area_slug!r} ({egp_path}); "
                f"ajuste --componente ou areas.{area_slug} em {area_map_path}.",
                file=sys.stderr,
            )
            return 1
        planned.append((egp_path, egp_key, egp_file, area_slug, resolved_comp))

    added = 0
    skipped = 0

    for egp_path, egp_key, egp_file, area_slug, resolved_comp in planned:

        if egp_key in by_key:
            if args.update_area:
                by_key[egp_key]["area"] = area_slug
                if args.componente is not None:
                    by_key[egp_key]["componente_dbt"] = resolved_comp
            skipped += 1
            continue

        entry = {
            "egp_key": egp_key,
            "egp_file": egp_file,
            "area": area_slug,
            "componente_dbt": resolved_comp,
        }
        if getattr(args, "entry_staging_mode", None):
            entry["staging_mode"] = args.entry_staging_mode
        if args.notes:
            entry["notes"] = args.notes
        catalog["entries"].append(entry)
        by_key[egp_key] = entry
        added += 1

    write_catalog(Path(args.output), catalog)
    print(f"Catálogo: {args.output}")
    print(f"Novas entradas: {added} | Já existentes (ignoradas): {skipped}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    catalog = load_or_create_catalog(Path(args.output))
    if args.defaults_from_example:
        catalog["defaults"] = _defaults_from_example()
    if getattr(args, "defaults_staging_mode", None):
        catalog.setdefault("defaults", _defaults_from_example())
        catalog["defaults"]["staging_mode"] = args.defaults_staging_mode

    egp_key, egp_file = egp_key_from_name(args.name)
    by_key = index_entries(catalog["entries"])
    area_map_path = Path(args.area_map)
    resolved_comp = _resolve_componente_cli_or_map(args.area, args.componente, area_map_path)
    if not resolved_comp:
        print(
            "É necessário --componente ou `areas.<slug>` em "
            f"{area_map_path} com o mesmo slug que --area={args.area!r}.",
            file=sys.stderr,
        )
        return 1

    entry = by_key.get(egp_key, {})
    entry.update(
        {
            "egp_key": egp_key,
            "egp_file": egp_file,
            "area": args.area,
            "componente_dbt": resolved_comp,
        }
    )
    if args.notes:
        entry["notes"] = args.notes
    if getattr(args, "entry_staging_mode", None):
        entry["staging_mode"] = args.entry_staging_mode

    if egp_key not in by_key:
        catalog["entries"].append(entry)
    else:
        # substitui no lugar
        for i, row in enumerate(catalog["entries"]):
            if isinstance(row, dict) and str(row.get("egp_key")) == egp_key:
                catalog["entries"][i] = entry
                break

    write_catalog(Path(args.output), catalog)
    print(f"Registrado: {egp_key} → {args.output}")
    return 0


def cmd_import_csv(args: argparse.Namespace) -> int:
    path = Path(args.csv_file).resolve()
    if not path.is_file():
        print(f"CSV não encontrado: {path}", file=sys.stderr)
        return 1

    catalog = load_or_create_catalog(Path(args.output))
    if args.defaults_from_example:
        catalog["defaults"] = _defaults_from_example()
    if getattr(args, "defaults_staging_mode", None):
        catalog.setdefault("defaults", _defaults_from_example())
        catalog["defaults"]["staging_mode"] = args.defaults_staging_mode

    by_key = index_entries(catalog["entries"])
    added = 0
    updated = 0

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = {n.strip().lower(): n for n in (reader.fieldnames or [])}
        if "egp_key" not in fieldnames and "egp_file" not in fieldnames:
            print("CSV precisa de coluna egp_key ou egp_file", file=sys.stderr)
            return 1
        if "area" not in fieldnames:
            print("CSV precisa de coluna area", file=sys.stderr)
            return 1

        for row in reader:
            raw = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            name = raw.get("egp_key") or raw.get("egp_file") or ""
            if not name:
                continue
            egp_key, egp_file = egp_key_from_name(name)
            area = raw.get("area") or ""
            comp = raw.get("componente_dbt") or raw.get("componente") or args.default_componente
            notes = raw.get("notes") or None

            if egp_key in by_key:
                by_key[egp_key]["area"] = area
                if comp is not None:
                    by_key[egp_key]["componente_dbt"] = comp
                if notes:
                    by_key[egp_key]["notes"] = notes
                updated += 1
            else:
                entry = {
                    "egp_key": egp_key,
                    "egp_file": egp_file,
                    "area": area,
                    "componente_dbt": comp,
                }
                if getattr(args, "entry_staging_mode", None):
                    entry["staging_mode"] = args.entry_staging_mode
                if notes:
                    entry["notes"] = notes
                catalog["entries"].append(entry)
                by_key[egp_key] = entry
                added += 1

    write_catalog(Path(args.output), catalog)
    print(f"Catálogo: {args.output} | novas: {added} | atualizadas: {updated}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = Path(args.output)
    data = _load_yaml(path)
    if not data:
        print(f"Arquivo vazio ou inexistente: {path}")
        return 0
    entries = data.get("entries") or []
    print(f"defaults: {data.get('defaults', {})}\n")
    for row in entries:
        if not isinstance(row, dict):
            continue
        print(f"  - {row.get('egp_key')} | area={row.get('area')} | componente={row.get('componente_dbt')}")
    print(f"\nTotal: {len(entries)}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    catalog = load_or_create_catalog(Path(args.output))
    by_key = index_entries(catalog["entries"])
    entry = by_key.get(args.egp_key)
    if not entry:
        print(f"egp_key não encontrado: {args.egp_key!r}", file=sys.stderr)
        return 1
    try:
        root = resolve_dbt_project_root(SCRIPT_DIR, catalog, entry)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(root)
    return 0


def cmd_governance_cd(args: argparse.Namespace) -> int:
    catalog = load_or_create_catalog(Path(args.output))
    by_key = index_entries(catalog["entries"])
    entry = by_key.get(args.egp_key)
    if not entry:
        print(f"egp_key não encontrado: {args.egp_key!r}", file=sys.stderr)
        return 1

    area = entry.get("area")
    gov_path = Path(args.governance_map)
    if not gov_path.is_file():
        print(
            f"Aviso: mapa de governança inexistente ({gov_path}); "
            f"usando apenas default_cd_governanca='99'. Copie area_cd_governanca.example.yaml.",
            file=sys.stderr,
        )
        gov_map: dict[str, str] = {}
        default_cd = "99"
    else:
        gov_map, default_cd = load_governance_map(gov_path)

    cd = resolve_cd_governanca(area, gov_map, default_cd)
    if args.verbose:
        src = "mapa" if (area and str(area).strip() in gov_map) else "default"
        print(f"area={area!r} cd_governanca={cd!r} fonte={src}")
    else:
        print(cd)
    return 0


def cmd_ensure_repo(args: argparse.Namespace) -> int:
    """Clone ou atualiza o repositório do componente (sem commit/push)."""
    catalog_path = Path(args.catalog)
    catalog = load_or_create_catalog(catalog_path)
    area_map_path = Path(args.area_map)
    componente: str | None = None
    if getattr(args, "egp_key", None):
        by_key = index_entries(catalog.get("entries") or [])
        entry = by_key.get(args.egp_key)
        if not entry:
            print(f"egp_key não encontrado: {args.egp_key!r}", file=sys.stderr)
            return 1
        c = entry.get("componente_dbt")
        if not c or not str(c).strip():
            print("entrada sem componente_dbt", file=sys.stderr)
            return 1
        componente = str(c).strip().strip("/\\")
    elif getattr(args, "area", None):
        c, _ = resolve_componente_for_area(str(args.area), area_map_path)
        if not c:
            print(
                f"Área {args.area!r} sem componente no mapa {area_map_path}; "
                "use --componente ou preencha `areas` em area_componente_dbt.yaml",
                file=sys.stderr,
            )
            return 1
        componente = c
    else:
        c = getattr(args, "componente", None)
        componente = str(c).strip().strip("/\\") if c is not None and str(c).strip() else None
    if not componente:
        print("Indique --componente, --area (com mapa), ou --egp-key", file=sys.stderr)
        return 1

    reg = load_area_componente_registry(area_map_path) if area_map_path.is_file() else {"components": {}}
    meta = dict(reg.get("components") or {}).get(componente) or {}
    git_url = str(meta.get("git_url") or "").strip()
    ref_from_meta = meta.get("git_ref")
    git_ref = getattr(args, "git_ref", None)
    if git_ref is not None and str(git_ref).strip():
        git_ref = str(git_ref).strip()
    elif ref_from_meta is not None and str(ref_from_meta).strip():
        git_ref = str(ref_from_meta).strip()
    else:
        git_ref = "main"

    root = component_repo_root(catalog, componente)
    git_dir = root / ".git"

    def ok_local_tree() -> bool:
        return root.is_dir() and (root / "dbt_project.yml").is_file()

    if not git_url:
        if ok_local_tree():
            print(f"[ensure-repo] Sem git_url; pasta dbt ok: {root}")
            return 0
        print(
            f"[ensure-repo] Sem git_url e pasta inválida ou em falta: {root}. "
            "Crie a cópia do componente ou defina components.{nome}.git_url no mapa.",
            file=sys.stderr,
        )
        return 1

    if getattr(args, "dry_run", False):
        print(f"[ensure-repo] dry-run: git sobre {root} (ref={git_ref})")
        return 0

    if git_dir.is_dir():
        code, out = _run_git(["fetch", "--all"], cwd=root)
        if code != 0:
            print(f"git fetch falhou ({code}): {out}", file=sys.stderr)
            return 1
        code, out = _run_git(["checkout", git_ref], cwd=root)
        if code != 0:
            print(f"git checkout {git_ref!r} falhou ({code}): {out}", file=sys.stderr)
            return 1
        code, out = _run_git(["pull", "--ff-only"], cwd=root)
        if code != 0:
            print(f"Aviso: git pull --ff-only ({code}): {out}", file=sys.stderr)
        print(f"[ensure-repo] Atualizado: {root} (ref {git_ref})")
        return 0

    if root.exists() and not git_dir.is_dir():
        print(f"{root} existe mas não é um repositório git", file=sys.stderr)
        return 1

    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    code, out = _run_git(["clone", git_url, root.name], cwd=parent)
    if code != 0:
        print(f"git clone falhou ({code}): {out}", file=sys.stderr)
        return 1
    code, out = _run_git(["checkout", git_ref], cwd=root)
    if code != 0:
        print(f"Aviso: git checkout {git_ref!r} após clone ({code}): {out}", file=sys.stderr)
    print(f"[ensure-repo] Clonado: {root}")
    return 0


def _add_output_arg(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--output",
        "-o",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Arquivo YAML do catálogo (default: {DEFAULT_REGISTRY_PATH})",
    )


def _add_staging_mode_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--defaults-staging-mode",
        choices=list(STAGING_MODE_CHOICES),
        default=None,
        metavar="MODE",
        help="Grava em catalog.defaults.staging_mode antes de processar entradas",
    )
    sp.add_argument(
        "--entry-staging-mode",
        choices=list(STAGING_MODE_CHOICES),
        default=None,
        metavar="MODE",
        help="Em cada entrada nova (scan/import) ou na entrada add/merge, define staging_mode",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bootstrap do registry egp_catalog.yaml",
        epilog="Ex.: python -m scripts.bootstrap_egp_catalog scan --area cobranca --componente dbt-srcg-anlt-plataforma-master "
        "[--defaults-staging-mode reuse_existing] [--entry-staging-mode reuse_existing]",
    )

    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("scan", help="Varre diretório .egp e adiciona entradas novas")
    _add_output_arg(ps)
    ps.add_argument("--egp-dir", default=str(DEFAULT_EGP_DIR), help="Pasta com arquivos .egp")
    ps.add_argument(
        "--area",
        default=None,
        help="Área (slug) para EGPs na raiz de --egp-dir; com subpastas AREA/*.egp a área infere-se e --area é opcional",
    )
    ps.add_argument(
        "--componente",
        default=None,
        help="componente_dbt (opcional se existir areas.<slug> em --area-map)",
    )
    ps.add_argument(
        "--area-map",
        default=str(DEFAULT_AREA_COMPONENTE_PATH),
        help="YAML área→componente (default: registry/area_componente_dbt.yaml)",
    )
    ps.add_argument("--notes", default=None, help="Notas comuns para entradas novas")
    ps.add_argument(
        "--update-area",
        action="store_true",
        help="Se o EGP já existe, atualiza area (e componente se passado)",
    )
    ps.add_argument(
        "--defaults-from-example",
        action="store_true",
        help="Sobrescreve defaults com os de egp_catalog.example.yaml",
    )
    _add_staging_mode_flags(ps)
    ps.set_defaults(func=cmd_scan)

    pa = sub.add_parser("add", help="Adiciona ou atualiza um EGP pelo nome")
    _add_output_arg(pa)
    pa.add_argument("name", help="Nome do EGP com ou sem .egp")
    pa.add_argument("--area", required=True)
    pa.add_argument(
        "--componente",
        default=None,
        help="componente_dbt (opcional se existir areas.<slug> em --area-map)",
    )
    pa.add_argument(
        "--area-map",
        default=str(DEFAULT_AREA_COMPONENTE_PATH),
        help="YAML área→componente (default: registry/area_componente_dbt.yaml)",
    )
    pa.add_argument("--notes", default=None)
    pa.add_argument(
        "--defaults-from-example",
        action="store_true",
    )
    _add_staging_mode_flags(pa)
    pa.set_defaults(func=cmd_add)

    pi = sub.add_parser("import-csv", help="Importa egp_key/egp_file + area (+ componente_dbt) de um CSV")
    _add_output_arg(pi)
    pi.add_argument("csv_file", help="CSV com colunas egp_key ou egp_file, area; opcional componente_dbt, notes")
    pi.add_argument(
        "--default-componente",
        default=None,
        help="componente_dbt quando a linha CSV não tiver coluna",
    )
    pi.add_argument(
        "--defaults-from-example",
        action="store_true",
    )
    _add_staging_mode_flags(pi)
    pi.set_defaults(func=cmd_import_csv)

    pl = sub.add_parser("list", help="Lista entradas do catálogo")
    _add_output_arg(pl)
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser(
        "resolve",
        help="Imprime a raiz do projeto dbt resolvida (base + componente_dbt ou override)",
    )
    _add_output_arg(pr)
    pr.add_argument("egp_key", help="Valor exato de egp_key no catálogo")
    pr.set_defaults(func=cmd_resolve)

    pg = sub.add_parser(
        "governance-cd",
        help="Imprime cd_governanca (labels dbt) a partir de area no catálogo + area_cd_governanca.yaml",
    )
    _add_output_arg(pg)
    pg.add_argument(
        "--governance-map",
        "-g",
        default=str(DEFAULT_GOVERNANCE_MAP_PATH),
        help=f"YAML com area_cd_governanca (default: {DEFAULT_GOVERNANCE_MAP_PATH})",
    )
    pg.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Imprime area, cd_governanca e se veio do mapa ou do default",
    )
    pg.add_argument("egp_key", help="Valor exato de egp_key no catálogo")
    pg.set_defaults(func=cmd_governance_cd)

    pe = sub.add_parser(
        "ensure-repo",
        help="Clone ou atualiza pasta do componente dbt (git fetch/checkout/pull; sem commit/push)",
    )
    pe.add_argument(
        "--catalog",
        "-c",
        default=str(DEFAULT_REGISTRY_PATH),
        help="egp_catalog.yaml (usa defaults.dbt_project_path)",
    )
    pe.add_argument(
        "--area-map",
        default=str(DEFAULT_AREA_COMPONENTE_PATH),
        help="YAML área→componente + git (default: registry/area_componente_dbt.yaml)",
    )
    pe.add_argument(
        "--componente",
        default=None,
        help="Pasta do projeto dbt (ex.: dbt-srcg-anlt-plataforma)",
    )
    pe.add_argument("--area", default=None, help="Slug de área (resolve componente via --area-map)")
    pe.add_argument(
        "--egp-key",
        default=None,
        help="Resolve componente_dbt a partir desta chave no catálogo",
    )
    pe.add_argument("--git-ref", default=None, help="Override do ref do mapa (branch/tag)")
    pe.add_argument(
        "--dry-run",
        action="store_true",
        help="Só mostra a operação git prevista, sem executar clone/pull",
    )
    pe.set_defaults(func=cmd_ensure_repo)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

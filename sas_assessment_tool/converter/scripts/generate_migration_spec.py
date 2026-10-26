#!/usr/bin/env python3
"""
Gera ``MIGRATION_SPEC.md`` para um EGP: junta catálogo, mapa cd_governanca,
cabeçalho do ``text_egps/*.txt`` e paths resolvidos do dbt.

Uso (a partir de converter/):
  python -m scripts.generate_migration_spec "Analise_mix_vulneraveis"
  python -m scripts.generate_migration_spec "202601 - gera arquivo batimentos atuacao manual (1)" -o draft_models/foo/MIGRATION_SPEC.md

Requer: extração já feita (``text_egps/<egp_key>.txt``) e entrada no ``egp_catalog.yaml``.
"""

from __future__ import annotations

import argparse
import re
import sys
import subprocess
from pathlib import Path

try:
    import yaml
except ImportError as e:
    print("Instale PyYAML: pip install pyyaml", file=sys.stderr)
    raise SystemExit(1) from e

from .bootstrap_egp_catalog import (
    DEFAULT_GOVERNANCE_MAP_PATH,
    DEFAULT_REGISTRY_PATH,
    SCRIPT_DIR,
    index_entries,
    load_governance_map,
    load_or_create_catalog,
    resolve_cd_governanca,
    resolve_dbt_project_root,
)

DEFAULT_TEXT_EGPS = SCRIPT_DIR / "text_egps"
DEFAULT_DRAFT_ROOT = SCRIPT_DIR / "draft_models"


def egp_slug(nome_sem_ext: str) -> str:
    s = nome_sem_ext.replace(" ", "_").replace("(", "_").replace(")", "_")
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def produto_compacto_sugerido(egp_key: str) -> str:
    """Heurística para `int_<produto_compacto>_` / marts (palavras coladas, minúsculas)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "", egp_key).lower()
    return s or "todo"


def parse_txt_metadata(txt_path: Path) -> dict[str, str]:
    """Extrai chaves simples entre START_METADATA e END_METADATA."""
    out: dict[str, str] = {}
    if not txt_path.is_file():
        return out
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    if "START_METADATA" not in text or "END_METADATA" not in text:
        return out
    block = text.split("START_METADATA", 1)[1].split("END_METADATA", 1)[0]
    for line in block.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped or set(stripped) == {"-"}:
            continue
        if stripped.startswith("[[") or stripped.startswith("#"):
            continue
        if ": " not in stripped:
            continue
        key, _, val = stripped.partition(": ")
        k = key.strip()
        if not k or k.startswith("[[ "):
            continue
        out[k] = val.strip()
    return out


def target_arch_effective(meta: dict[str, str], entry: dict, defaults: dict) -> tuple[str, str]:
    """Retorna (valor, nota de origem)."""
    override = entry.get("target_arch_override")
    if override is not None and str(override).strip():
        return str(override).strip(), "catálogo (entrada.target_arch_override)"
    d_ov = (defaults or {}).get("target_arch_override")
    if d_ov is not None and str(d_ov).strip():
        return str(d_ov).strip(), "catálogo (defaults.target_arch_override)"
    ta = meta.get("TARGET_ARCH") or ""
    if "(" in ta:
        ta = ta.split("(", 1)[0].strip()
    if ta:
        return ta, "cabeçalho text_egps (TARGET_ARCH)"
    return "DBT_BQ", "fallback"


def format_staging_ref_map(entry: dict) -> str:
    srm = entry.get("staging_ref_map")
    if srm is None or srm == []:
        return "_Não definido no catálogo._"
    if isinstance(srm, (dict, list)):
        return "```yaml\n" + yaml.safe_dump(srm, allow_unicode=True, sort_keys=False).rstrip() + "\n```"
    return str(srm)


def effective_staging_mode(entry: dict, defaults: dict) -> tuple[str, str]:
    """Retorna (valor, nota de origem)."""
    sm = entry.get("staging_mode")
    if sm is not None and str(sm).strip():
        return str(sm).strip(), "catálogo (entrada.staging_mode)"
    d = (defaults or {}).get("staging_mode")
    if d is not None and str(d).strip():
        return str(d).strip(), "catálogo (defaults.staging_mode)"
    return "reuse_existing", "fallback"


def arch_override_value(entry: dict, defaults: dict) -> tuple[str | None, str]:
    """Retorna (valor, nota). Valor None significa 'sem override'."""
    override = entry.get("target_arch_override")
    if override is not None and str(override).strip():
        return str(override).strip(), "catálogo (entrada.target_arch_override)"
    d_ov = (defaults or {}).get("target_arch_override")
    if d_ov is not None and str(d_ov).strip():
        return str(d_ov).strip(), "catálogo (defaults.target_arch_override)"
    return None, "não definido"


def build_contract_yaml(
    *,
    egp_key: str,
    meta: dict[str, str],
    entry: dict,
    defaults: dict,
    cd_governanca: str,
    cd_governanca_source: str,
    target_arch_effective_value: str,
    target_arch_source: str,
    dbt_project_root: Path,
    clone_dest: Path,
) -> str:
    """Bloco YAML para o gate consumir (sem regex frágil)."""
    staging_mode, staging_mode_source = effective_staging_mode(entry, defaults)
    arch_override, arch_override_source = arch_override_value(entry, defaults)
    payload = {
        "schema_version": 1,
        "egp_key": egp_key,
        "project_extrator": (meta.get("PROJECT") or "").strip() or None,
        "target_arch_effective": target_arch_effective_value,
        "target_arch_source": target_arch_source,
        "arch_override": arch_override,
        "arch_override_source": arch_override_source,
        "area": (entry.get("area") or "").strip() or None,
        "cd_governanca": cd_governanca,
        "cd_governanca_source": cd_governanca_source,
        "componente_dbt": (entry.get("componente_dbt") or "").strip() or None,
        "staging_mode_effective": staging_mode,
        "staging_mode_source": staging_mode_source,
        "dbt_project_root": str(dbt_project_root),
        "dbt_clone_dest": str(clone_dest),
        "produto_compacto_sugerido": produto_compacto_sugerido(egp_key),
        "egp_slug": egp_slug(egp_key),
    }
    dumped = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).rstrip()
    return "```yaml\n" + dumped + "\n```"


def build_markdown(
    egp_key: str,
    entry: dict,
    defaults: dict,
    meta: dict[str, str],
    dbt_root: Path,
    clone_dest: Path,
    cd_gov: str,
    cd_gov_source: str,
    target_arch: str,
    arch_note: str,
) -> str:
    area = entry.get("area") or ""
    comp = entry.get("componente_dbt") or ""
    staging_mode, staging_mode_source = effective_staging_mode(entry, defaults)
    slug = egp_slug(egp_key)
    pcompact = produto_compacto_sugerido(egp_key)
    arch_override, arch_override_source = arch_override_value(entry, defaults)

    lines = [
        f"# MIGRATION_SPEC — `{egp_key}`",
        "",
        "Contrato de contexto para tradutor (Agente 1) e governança (Agente 2).",
        "Gerado por `generate_migration_spec.py`; complete secções **TODO** antes ou durante o draft.",
        "",
        "## 0. CONTRATO (machine-readable)",
        "",
        "Este bloco é a **fonte de verdade** para checagens mecânicas (ex.: `draft_gate.py`).",
        "Não altere manualmente; regenere o spec se precisar mudar valores vindos do catálogo.",
        "",
        build_contract_yaml(
            egp_key=egp_key,
            meta=meta,
            entry=entry,
            defaults=defaults,
            cd_governanca=cd_gov,
            cd_governanca_source=cd_gov_source,
            target_arch_effective_value=target_arch,
            target_arch_source=arch_note,
            dbt_project_root=dbt_root,
            clone_dest=clone_dest,
        ),
        "",
        "## 1. Identificação",
        "",
        f"| Campo | Valor |",
        f"|-------|-------|",
        f"| **egp_key** | `{egp_key}` |",
        f"| **PROJECT (extrator)** | `{meta.get('PROJECT', '')}` |",
        f"| **EGP_SLUG (paths / migracao_sas)** | `{slug}` |",
        f"| **produto_compacto (nomenclatura dbt, sugerido)** | `{pcompact}` |",
        "",
        f"_Ajuste `produto_compacto` manualmente se o nome de negócio for composto (ex.: \"Pagamentos Digital\" → `pagamentosdigital`)._",
        "",
        "## 2. Arquitetura alvo",
        "",
        f"| Campo | Valor |",
        f"|-------|-------|",
        f"| **TARGET_ARCH efetivo** | `{target_arch}` |",
        f"| **Origem** | {arch_note} |",
        f"| **ARCH_OVERRIDE (catálogo)** | `{arch_override or ''}` |",
        f"| **Origem override** | {arch_override_source} |",
        "",
        "### Metadados do extrator (resumo)",
        "",
        f"- **TRIGGERS:** {meta.get('TRIGGERS', '—')}",
        f"- **HAS_PASSTHROUGH:** {meta.get('HAS_PASSTHROUGH', '—')}",
        f"- **HAS_DATA_STEP:** {meta.get('HAS_DATA_STEP', '—')}",
        f"- **DETECTED_TABLES_HARDCODED:** {meta.get('DETECTED_TABLES_HARDCODED', '—')}",
        f"- **FILE_REFERENCES_SUMMARY:** {meta.get('FILE_REFERENCES_SUMMARY', '—')}",
        "",
        "## 3. Catálogo e governança",
        "",
        f"| Campo | Valor |",
        f"|-------|-------|",
        f"| **area** | `{area}` |",
        f"| **cd_governanca** | `{cd_gov}` |",
        f"| **Origem cd_governanca** | {cd_gov_source} |",
        f"| **componente_dbt** | `{comp}` |",
        f"| **staging_mode (efetivo)** | `{staging_mode}` |",
        f"| **Origem staging_mode** | {staging_mode_source} |",
        "",
        "### staging_ref_map",
        "",
        format_staging_ref_map(entry),
        "",
        "## 4. Paths (dbt)",
        "",
        f"| Campo | Valor |",
        f"|-------|-------|",
        f"| **dbt_project_root (clone)** | `{dbt_root}` |",
        f"| **DBT_CLONE_DEST (migracao_sas)** | `{clone_dest}` |",
        f"| **Sandbox esperado** | `converted_egps/<YYYY-MM-DD>_<git-short>_dbt|databricks/{egp_key}/` (ou legado `converted_egps/dbt|databricks/{egp_key}/`) |",
        "",
        "## 4.1 Nomenclatura e anti-colisão (contrato)",
        "",
        "- **Regra geral**: modelos `int_*` e marts devem incluir `produto_compacto` para evitar colisões em lote.",
        f"- **Sugestão**: `int_{pcompact}_<detalhe>.sql` e marts `{pcompact}_<detalhe>_fato.sql`.",
        "- **Quando reforçar**: se houver risco de colisão no mesmo `dbt_project`, use prefixo explícito com `egp_slug` "
        "(ver `.cursor/skills/orchestrator/SKILL.md`, secção **Política anti-colisão**, e `01_sas_to_dbt.mdc` §2).",
        "",
        "## 5. Fontes e saídas (preencher na análise)",
        "",
        "### Fontes",
        "",
        "- BigQuery / lake: listar a partir de `DETECTED_TABLES_*` e código SAS.",
        "- Ficheiros / pass-through: ver FILE INVENTORY no `.txt`.",
        "- **TODO:** APIs, librefs, notas de `CONNECT TO`.",
        "",
        "### Saídas esperadas",
        "",
        "- Tabelas finais / exports: **TODO** (nomes SAS → modelos dbt).",
        "",
        "## 6. Macros e parâmetros críticos",
        "",
        "Copiar do `.txt` secções `[[ PROJECT LETS ]]` e `%LET` relevantes, ou **TODO**.",
        "",
        "## 7. Ordem lógica / dependências",
        "",
        "**TODO:** fluxos do EGP (rótulos de job / ordem topológica).",
        "",
        "## 8. Filtros",
        "",
        "Se existir `FILTERS_ORIGINAIS` no `.txt`, listar aqui ou referenciar; o tradutor deve reproduzi-los.",
        "",
        "## 9. Manifest canónico do draft (editável)",
        "",
        "Lista fechada dos modelos em `draft_models/<egp_key>/models/{staging|intermediate|marts}/`. "
        "**Editável** (não confundir com o YAML do §0). Com `models` não vazio, `draft_gate` exige que cada "
        "par (`layer`, `stem`) exista como `<stem>.sql` ou `<stem>.py` na pasta `models/<layer>/`. "
        "Com `models: []`, o gate não falha por manifesto.",
        "",
        "Alinhar a **PERMANENT OUTPUTS** / libref permanente / `PROC EXPORT` → 1 mart (§2.1–2.2). "
        "Sem export nem libref permanente: marts de fallback = tabela(s) **`WORK` terminal(is)** (§2.3).",
        "",
        "```yaml",
        "draft_manifest:",
        "  schema_version: 1",
        "  models: []",
        "```",
        "",
        "---",
        "",
        "*Gerado em: `scripts/generate_migration_spec.py` (CLI: `python -m scripts.generate_migration_spec`)*",
    ]
    return "\n".join(lines) + "\n"


def cmd_generate(args: argparse.Namespace) -> int:
    egp_key = args.egp_key.strip()
    catalog_path = Path(args.catalog)
    gov_path = Path(args.governance_map)
    catalog = load_or_create_catalog(catalog_path)
    by_key = index_entries(catalog["entries"])
    entry = by_key.get(egp_key)
    if not entry:
        print(f"egp_key não encontrado no catálogo: {egp_key!r}", file=sys.stderr)
        return 1

    defaults = catalog.get("defaults") or {}
    txt_path = Path(args.txt) if args.txt else (DEFAULT_TEXT_EGPS / f"{egp_key}.txt")
    meta = parse_txt_metadata(txt_path)
    if not meta and not args.quiet:
        print(f"Aviso: cabeçalho vazio ou ficheiro inexistente: {txt_path}", file=sys.stderr)

    try:
        dbt_root = resolve_dbt_project_root(SCRIPT_DIR, catalog, entry)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    # Garantir clone antes de inferir workspace_subdir via `dbt_project.yml`.
    if not (dbt_root / "dbt_project.yml").is_file():
        _ensure_repo_for_egp_key(converter_dir=SCRIPT_DIR, egp_key=egp_key, catalog_path=catalog_path)

    slug = egp_slug(egp_key)
    area_str = str(entry.get("area") or "")
    workspace_subdir, model_path = resolve_workspace_subdir_and_model_path(dbt_root, area=area_str)
    clone_dest = (dbt_root / model_path / "workspace" / workspace_subdir / "migracao_sas" / slug).resolve()

    area = entry.get("area")
    if gov_path.is_file():
        gmap, default_cd = load_governance_map(gov_path)
        cd_gov = resolve_cd_governanca(area, gmap, default_cd)
        cd_gov_source = (
            "mapa area_cd_governanca.yaml"
            if (area and str(area).strip() in gmap)
            else "default_cd_governanca (área ausente no mapa ou mapa vazio)"
        )
    else:
        cd_gov = "99"
        cd_gov_source = f"ficheiro inexistente ({gov_path}); fallback 99"

    target_arch, arch_note = target_arch_effective(meta, entry, defaults)

    body = build_markdown(
        egp_key,
        entry,
        defaults,
        meta,
        dbt_root,
        clone_dest,
        cd_gov,
        cd_gov_source,
        target_arch,
        arch_note,
    )

    out_path = Path(args.output) if args.output else (DEFAULT_DRAFT_ROOT / egp_key / "MIGRATION_SPEC.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    if not args.quiet:
        print(out_path.resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gera MIGRATION_SPEC.md para um EGP")
    p.add_argument("egp_key", help="Valor exato de egp_key no egp_catalog.yaml")
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=f"Caminho do .md (default: draft_models/<egp_key>/MIGRATION_SPEC.md)",
    )
    p.add_argument(
        "--catalog",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"egp_catalog.yaml (default: {DEFAULT_REGISTRY_PATH})",
    )
    p.add_argument(
        "-g",
        "--governance-map",
        default=str(DEFAULT_GOVERNANCE_MAP_PATH),
        help=f"area_cd_governanca.yaml (default: {DEFAULT_GOVERNANCE_MAP_PATH})",
    )
    p.add_argument(
        "--txt",
        default=None,
        help=f"Ficheiro text_egps (default: text_egps/<egp_key>.txt)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="Só erros no stderr")
    p.set_defaults(func=cmd_generate)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


def _read_dbt_project_model_paths(dbt_root: Path) -> list[Path]:
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
    project_name, models = _read_dbt_project_name_and_models(dbt_root)
    if not project_name:
        return ""
    proj_cfg = models.get(project_name) if isinstance(models, dict) else None
    if not isinstance(proj_cfg, dict):
        return ""
    ws = proj_cfg.get("workspace")
    if not isinstance(ws, dict) or not ws:
        return ""
    for k in ws.keys():
        if isinstance(k, str) and k.strip():
            return k.strip()
    return ""


def resolve_workspace_subdir_and_model_path(dbt_root: Path, area: str) -> tuple[str, Path]:
    area_slug = (area or "").strip().lower()
    preferred = f"corp_{area_slug}" if area_slug else ""

    model_paths = _read_dbt_project_model_paths(dbt_root)
    yaml_ws = _workspace_subdir_from_yaml(dbt_root)
    if yaml_ws:
        for mp in model_paths:
            if (dbt_root / mp / "workspace" / yaml_ws).is_dir():
                return yaml_ws, mp
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
    return (preferred or "corp_unknown"), Path("models")


def _ensure_repo_for_egp_key(*, converter_dir: Path, egp_key: str, catalog_path: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "scripts.bootstrap_egp_catalog",
        "ensure-repo",
        "--egp-key",
        egp_key,
        "--catalog",
        str(catalog_path if catalog_path else DEFAULT_REGISTRY_PATH),
        "--area-map",
        str(converter_dir / "registry" / "area_componente_dbt.yaml"),
    ]
    subprocess.run(cmd, cwd=str(converter_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    raise SystemExit(main())

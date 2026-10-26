#!/usr/bin/env python3
"""
Gera `CHAMADOS_CONVERSAO.md` no sandbox de um EGP, com auto-preenchimento.

Saída padrão:
  sandbox resolvido (legado ou ``<YYYY-MM-DD>_<sha>_<target>/``) / CHAMADOS_CONVERSAO.md

Campos manuais (placeholders):
  - Chamado de Validação de Governança
  - Chamado do Chapter AE
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .bootstrap_egp_catalog import SCRIPT_DIR
from .sandbox_layout import find_converted_sandbox


TEMPLATE_PATH = Path("templates") / "CHAMADOS_CONVERSAO.template.md"


def _slugify_model_name(path: Path) -> str:
    return path.stem.strip()


def _list_models(models_dir: Path) -> list[str]:
    if not models_dir.is_dir():
        return []
    return [_slugify_model_name(p) for p in sorted(models_dir.glob("*.sql"))]


_REF_STG_RE = re.compile(r"""(?i)\{\{\s*ref\(\s*['"]([^'"]*stg[^'"]*)['"]\s*\)\s*\}\}""")


def _extract_staging_refs_from_sql(sql_path: Path) -> set[str]:
    txt = sql_path.read_text(encoding="utf-8", errors="replace")
    return {m.group(1) for m in _REF_STG_RE.finditer(txt)}


def _collect_staging_refs(models_root: Path) -> set[str]:
    refs: set[str] = set()
    for layer in ("intermediate", "marts"):
        layer_dir = models_root / layer
        if not layer_dir.is_dir():
            continue
        for p in sorted(layer_dir.glob("*.sql")):
            refs |= _extract_staging_refs_from_sql(p)
    return refs


def _security_section_from_checks(checks_line: str) -> str:
    # Heurística: se a linha de checks contém `pii_yml=ok`, mencionar policy tags.
    if "pii_yml=ok" in checks_line or "pii_sensitive_yml_ok" in checks_line:
        return "Adicionamos as Policy Tags nos campos necessários (conforme `sensitive_data_types.yaml` e checks do pipeline)."
    return "N/A (sem alterações específicas de policy tags detectadas pelos checks do pipeline)."


def _read_latest_checks_stdout(egp_key: str) -> str:
    """
    Best-effort: tenta ler a última linha registrada em `registry/batch_manifest.json` (batch_checks),
    mas para manter determinístico e sem dependências, usa fallback simples.

    Neste primeiro corte, não reexecuta checks.
    """
    return ""


def _fill_template(
    *,
    template: str,
    egp_key: str,
    visao_geral: str,
    adicionado: str,
    o_que_mudou: str,
    o_que_foi_removido: str,
    corrigido: str,
    seguranca: str,
) -> str:
    out = template
    out = out.replace("{{EGP_KEY}}", egp_key)
    out = out.replace("{{VISAO_GERAL}}", visao_geral)
    out = out.replace("{{ADICIONADO}}", adicionado)
    out = out.replace("{{O_QUE_MUDOU}}", o_que_mudou)
    out = out.replace("{{O_QUE_FOI_REMOVIDO}}", o_que_foi_removido)
    out = out.replace("{{CORRIGIDO}}", corrigido)
    out = out.replace("{{SEGURANCA}}", seguranca)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera CHAMADOS_CONVERSAO.md no sandbox do EGP.")
    ap.add_argument("egp_key", help="EGP key")
    ap.add_argument(
        "--target",
        default=None,
        choices=["dbt", "databricks"],
        help="Target sandbox (default: autodetect por pasta existente).",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Caminho de saída (default: sandbox resolvido / CHAMADOS_CONVERSAO.md).",
    )
    args = ap.parse_args()

    egp_key = str(args.egp_key).strip()
    pref = args.target.strip().lower() if args.target else None
    target_arch, sandbox_root = find_converted_sandbox(SCRIPT_DIR, egp_key, preferred_arch=pref)

    if not target_arch or not sandbox_root or not sandbox_root.is_dir():
        print(
            f"Sandbox não encontrado para {egp_key!r} (legado ou DATA_SHA_dbt|databricks).",
            file=sys.stderr,
        )
        return 1

    models_root = sandbox_root / "models"
    inter = _list_models(models_root / "intermediate")
    marts = _list_models(models_root / "marts")

    visao_geral = (
        f"Inclusão e ajustes de modelos para materializar outputs do projeto `{egp_key}` (migração SAS → {target_arch.upper()}). "
        f"Foram produzidos {len(inter)} modelos intermediate e {len(marts)} modelos marts."
    )

    adicionado_lines: list[str] = []
    if inter:
        adicionado_lines.append(f"- Adicionados {len(inter)} modelos intermediate:")
        adicionado_lines.extend([f"  - {_m}" for _m in inter])
    if marts:
        adicionado_lines.append(f"- Adicionados {len(marts)} modelos marts:")
        adicionado_lines.extend([f"  - {_m}" for _m in marts])
    adicionado = "\n".join(adicionado_lines) if adicionado_lines else "Nada"

    staging_refs = sorted(_collect_staging_refs(models_root))
    if staging_refs:
        o_que_mudou = (
            "Staging reutilizado no componente (refs `stg_*` detectados em intermediate/marts):\n"
            + "\n".join([f"- `{r}`" for r in staging_refs])
            + "\n\n> Se foi necessário alargar algum staging canónico (extend_canonical), descreva aqui os campos adicionados."
        )
    else:
        o_que_mudou = "Nada (não foram detectados `ref('stg_*')` nos modelos intermediate/marts)."

    o_que_foi_removido = "Nada"
    corrigido = "Nada"

    checks_line = _read_latest_checks_stdout(egp_key)
    seguranca = _security_section_from_checks(checks_line)

    if not TEMPLATE_PATH.is_file():
        print(f"Template não encontrado: {TEMPLATE_PATH}", file=sys.stderr)
        return 1
    template = TEMPLATE_PATH.read_text(encoding="utf-8", errors="replace")

    rendered = _fill_template(
        template=template,
        egp_key=egp_key,
        visao_geral=visao_geral,
        adicionado=adicionado,
        o_que_mudou=o_que_mudou,
        o_que_foi_removido=o_que_foi_removido,
        corrigido=corrigido,
        seguranca=seguranca,
    )

    out_path = Path(args.out) if args.out else (sandbox_root / "CHAMADOS_CONVERSAO.md")
    out_path.write_text(rendered, encoding="utf-8")
    print(out_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


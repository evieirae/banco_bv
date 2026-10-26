#!/usr/bin/env python3
"""
Carimbo determinístico para metadados de auditoria em modo lote.

Imprime na stdout (Markdown) o bloco **Metadados de execução** alinhado a
`.cursor/rules/03_migration_auditor.mdc`, com `data_utc_auditoria` em ISO 8601 (UTC).
Opcionalmente inclui a tabela **Pontos de alto risco** (esqueleto Pendente/N/A).

Uso (a partir da pasta converter/):

  python -m scripts.audit_batch_stamp --batch-file registry/egp_keys_batch.txt
  python -m scripts.audit_batch_stamp --batch-file registry/egp_keys_batch.txt --egp-key "MeuProj"
  python -m scripts.audit_batch_stamp --batch-file registry/egp_keys_batch.txt --notas "ticket JIRA-123"
  python -m scripts.audit_batch_stamp --modo-lote não --no-high-risk

Colar a saída imediatamente após a linha de título `# AUDITORIA — ...` no relatório.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

CONVERTER_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = CONVERTER_DIR


def normalize_batch_path(batch_path: Path, base: Path) -> str:
    """Tenta devolver caminho relativo a `base` (pasta converter/); senão devolve string estável."""
    try:
        resolved = batch_path.expanduser().resolve()
        base_r = base.resolve()
        return str(resolved.relative_to(base_r))
    except (ValueError, OSError):
        return str(batch_path).replace("\\", "/")


def build_high_risk_table() -> str:
    """Tabela canónica (estado inicial sugerido: Pendente / N/A)."""
    rows = [
        ("Filtros / `WHERE` e impacto em volume de linhas vs SAS", "Pendente", ""),
        ("Chaves, joins e cardinalidade (PK/FK, duplicações)", "Pendente", ""),
        ("`PROC EXPORT` / marts de exportação vs SAS", "Pendente", ""),
        ("`PERMANENT OUTPUTS` / libref permanente vs `models/marts/`", "Pendente", ""),
        (
            "PII / `registry/sensitive_data_types.yaml` vs YAML e `fl_contem_pii`",
            "Pendente",
            "",
        ),
        ("Tabelas de negócio / `ref`+`source` vs fluxo SAS", "Pendente", ""),
        ("Amostragem ou validação no motor alvo (ex. BigQuery)", "N/A", ""),
    ]
    lines = [
        "## Pontos de alto risco (revisão humana)",
        "",
        "| Tema | Estado | Notas |",
        "|------|--------|--------|",
    ]
    for tema, estado, notas in rows:
        lines.append(f"| {tema} | {estado} | {notas} |")
    lines.append("")
    lines.append(
        "<!-- Estado: Revisado | Pendente | N/A. "
        "Qualquer Pendente impede Resumo OK em todas as áreas (regra 03_migration_auditor). -->"
    )
    return "\n".join(lines)


def build_stamp(
    *,
    modo_lote: str,
    batch_file: Path | None,
    notas: str | None,
    include_high_risk: bool,
    egp_key: str | None,
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    parts: list[str] = []
    if egp_key:
        parts.append(f"<!-- stamp: egp_key={egp_key} -->")
        parts.append("")
    parts.extend(
        [
            "## Metadados de execução (stamp automático)",
            "",
            f"- **modo_lote:** {modo_lote}",
        ]
    )
    if modo_lote.strip().lower() == "sim":
        if batch_file is None:
            raise ValueError("Com modo_lote=sim é obrigatório indicar --batch-file")
        rel = normalize_batch_path(batch_file, SCRIPT_DIR)
        parts.append(f"- **ficheiro_lote:** `{rel}`")
    else:
        parts.append("- **ficheiro_lote:** _N/A (auditoria fora de lote)_")
    parts.append(f"- **data_utc_auditoria:** {now}")
    if notas and notas.strip():
        parts.append(f"- **notas_lote:** {notas.strip()}")
    else:
        parts.append("- **notas_lote:** _opcional_")
    parts.append("")
    out = "\n".join(parts)
    if include_high_risk:
        out += "\n" + build_high_risk_table() + "\n"
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="Imprime bloco Markdown de metadados (e opcionalmente tabela de alto risco) para AUDITORIA em lote."
    )
    p.add_argument(
        "--batch-file",
        "-b",
        type=Path,
        default=None,
        metavar="PATH",
        help="Ficheiro de lista de egp_key usado no lote (obrigatório se --modo-lote sim)",
    )
    p.add_argument(
        "--modo-lote",
        choices=("sim", "não", "nao"),
        default="sim",
        help="Valor do campo modo_lote (defeito: sim)",
    )
    p.add_argument(
        "--egp-key",
        default=None,
        metavar="KEY",
        help="Opcional: inclui comentário HTML com a chave (rastreio humano)",
    )
    p.add_argument("--notas", default=None, help="Texto livre para notas_lote")
    p.add_argument(
        "--no-high-risk",
        action="store_true",
        help="Não incluir a secção ## Pontos de alto risco (só metadados)",
    )
    args = p.parse_args()
    modo = "não" if args.modo_lote in ("não", "nao") else "sim"
    try:
        text = build_stamp(
            modo_lote=modo,
            batch_file=args.batch_file,
            notas=args.notas,
            include_high_risk=not args.no_high_risk,
            egp_key=args.egp_key,
        )
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Auto-fix determinístico: remove `alias=...` de blocos `config()` em modelos dbt.

Escopo:
- <root>/intermediate/*.sql
- <root>/marts/*.sql

Uso:
  python -m scripts.remove_dbt_config_alias --root converted_egps/<DATA>_<sha>_dbt/<egp_key>/models
  python -m scripts.remove_dbt_config_alias --root <DBT_CLONE_DEST>
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_CONFIG_BLOCK_RE = re.compile(r"(?s)\{\{.*?config\s*\(.*?\)\s*\}\}")

# Remove alias='...' or alias="..." with optional leading/trailing commas/spaces/newlines.
_ALIAS_PARAM_RE = re.compile(r"""(?sx)
    (?:,\s*)?                 # optional leading comma
    alias\s*=\s*
    (?:'[^']*'|"[^"]*")       # quoted string
    (?:\s*,)?                 # optional trailing comma
""")

# Cleanup: trailing comma before closing paren
_TRAILING_COMMA_RE = re.compile(r",\s*\)")
# Cleanup: comma right after opening paren
_LEADING_COMMA_RE = re.compile(r"\(\s*,")


def _remove_alias_from_config_block(block: str) -> tuple[str, bool]:
    if "alias" not in block:
        return block, False
    new = _ALIAS_PARAM_RE.sub("", block, count=1)
    # normalize commas around parentheses
    new = _TRAILING_COMMA_RE.sub(")", new)
    new = _LEADING_COMMA_RE.sub("(", new)
    changed = new != block
    return new, changed


def _process_file(path: Path, *, dry_run: bool) -> bool:
    original = path.read_text(encoding="utf-8", errors="replace")
    m = _CONFIG_BLOCK_RE.search(original)
    if not m:
        return False
    block = m.group(0)
    new_block, changed = _remove_alias_from_config_block(block)
    if not changed:
        return False
    new_text = original[: m.start()] + new_block + original[m.end() :]
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove alias=... de config() em intermediate/marts.")
    ap.add_argument("--root", required=True, help="Pasta raiz de models/ (contém intermediate/ e marts/).")
    ap.add_argument("--dry-run", action="store_true", help="Não escreve; apenas imprime resumo.")
    args = ap.parse_args()

    root = Path(args.root)
    changed_files: list[str] = []
    scanned = 0
    for layer in ("intermediate", "marts"):
        layer_dir = root / layer
        if not layer_dir.is_dir():
            continue
        for path in sorted(layer_dir.glob("*.sql")):
            scanned += 1
            if _process_file(path, dry_run=args.dry_run):
                changed_files.append(str(path))

    print(
        f"[remove_dbt_config_alias] ok scanned={scanned} changed={len(changed_files)} dry_run={bool(args.dry_run)} root={root}"
    )
    if changed_files:
        for p in changed_files[:200]:
            print(f"  - {p}")
        if len(changed_files) > 200:
            print(f"  - ... e mais {len(changed_files) - 200}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


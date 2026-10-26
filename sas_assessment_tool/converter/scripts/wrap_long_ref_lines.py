"""
Fix SQLFluff LT05 long lines caused by long `{{ ref('...') }}` calls.

This script rewrites lines like:
  from {{ ref('very_long_name') }}
into:
  from {{
      ref('very_long_name')
  }}

It only changes lines longer than --max-len.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_RE_REF_CALL = re.compile(r"^(\s*)\{\{\s*ref\('([^']+)'\)\s*\}\}\s*$")


def rewrite_file(path: Path, *, max_len: int) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=False)
    out: list[str] = []
    changed = False

    for line in lines:
        if len(line) > max_len:
            m = _RE_REF_CALL.match(line)
            if m:
                indent = m.group(1)
                ref_name = m.group(2)
                out.extend(
                    [
                        f"{indent}{{{{",
                        f"{indent}    ref('{ref_name}')",
                        f"{indent}}}}}",
                    ]
                )
                changed = True
                continue
        out.append(line)

    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description="Wrap long dbt ref lines to satisfy SQLFluff LT05.")
    ap.add_argument(
        "root",
        help="Directory to scan (e.g. converted_egps/<DATA>_<sha>_dbt/<egp>/models or legado converted_egps/dbt/<egp>/models)",
    )
    ap.add_argument("--max-len", type=int, default=120)
    args = ap.parse_args()

    root = Path(args.root)
    changed = 0
    scanned = 0
    for path in sorted(root.rglob("*.sql")):
        scanned += 1
        if rewrite_file(path, max_len=args.max_len):
            changed += 1

    print(f"[wrap_long_ref_lines] ok scanned={scanned} changed={changed} root={root}")


if __name__ == "__main__":
    main()


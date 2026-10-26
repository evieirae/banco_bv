from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _normalize_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if line.startswith("#"):
        return ""
    return line


def _read_keys_from_stdin() -> list[str]:
    keys: list[str] = []
    for raw in sys.stdin.read().splitlines():
        k = _normalize_line(raw)
        if k:
            keys.append(k)
    return keys


def _dedup_preserve_order(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write registry/egp_keys_batch.txt from a list of EGP keys. "
            "Trims whitespace, ignores blank/comment lines, and de-dups."
        )
    )
    parser.add_argument(
        "-o",
        "--out",
        default="registry/egp_keys_batch.txt",
        help="Output batch file path (default: registry/egp_keys_batch.txt).",
    )
    parser.add_argument(
        "keys",
        nargs="*",
        help=(
            "EGP keys to write. If omitted, reads keys from stdin "
            "(one per line; blanks and #comments ignored)."
        ),
    )

    args = parser.parse_args(argv)

    keys = [_normalize_line(k) for k in args.keys]
    keys = [k for k in keys if k]
    if not keys:
        keys = _read_keys_from_stdin()

    keys = _dedup_preserve_order(keys)
    if not keys:
        print("No EGP keys provided (args or stdin).", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(keys) + "\n", encoding="utf-8")

    print(f"Wrote {len(keys)} EGP key(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate registry/egp_keys_batch.txt from all *.egp under received_egps/ "
            "(or another received dir). Uses filename stem as egp_key."
        )
    )
    parser.add_argument(
        "--received-dir",
        default="received_egps",
        help="Directory to scan recursively for *.egp (default: received_egps).",
    )
    parser.add_argument(
        "--out",
        default="registry/egp_keys_batch.txt",
        help="Output batch file path (default: registry/egp_keys_batch.txt).",
    )
    parser.add_argument(
        "--allow-collisions",
        action="store_true",
        help=(
            "Allow duplicate stems (same egp_key) across subfolders; "
            "will de-dup by stem and warn to stderr. Default is to fail."
        ),
    )

    args = parser.parse_args(argv)

    received_dir = Path(args.received_dir)
    if not received_dir.exists() or not received_dir.is_dir():
        print(f"received_dir not found or not a directory: {received_dir}", file=sys.stderr)
        return 2

    egps = sorted(received_dir.rglob("*.egp"))
    if not egps:
        print(f"No .egp files found under: {received_dir}", file=sys.stderr)
        return 2

    by_stem: dict[str, list[Path]] = defaultdict(list)
    for p in egps:
        by_stem[p.stem].append(p)

    collisions = {k: v for k, v in by_stem.items() if len(v) > 1}
    if collisions and not args.allow_collisions:
        print(
            "Collision detected: multiple .egp files share the same stem (egp_key).",
            file=sys.stderr,
        )
        for stem, paths in sorted(collisions.items()):
            print(f"- {stem}:", file=sys.stderr)
            for p in sorted(paths):
                print(f"  - {p.as_posix()}", file=sys.stderr)
        print(
            "Fix: rename the files to be unique, or re-run with --allow-collisions.",
            file=sys.stderr,
        )
        return 2

    keys = sorted(by_stem.keys())
    if collisions and args.allow_collisions:
        print(
            f"Warning: {len(collisions)} egp_key collision(s) detected; de-duping by stem.",
            file=sys.stderr,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(keys) + "\n", encoding="utf-8")
    print(f"Wrote {len(keys)} EGP key(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


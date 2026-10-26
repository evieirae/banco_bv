from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CleanupSpec:
    delete_paths: tuple[Path, ...]
    preserve_globs: tuple[str, ...]


def _default_spec(mode: str) -> CleanupSpec:
    registry = Path("registry")

    # Things we never want to delete via a broad cleanup.
    preserve_globs = (
        "*.example.*",
        "area_cd_governanca.yaml",
        "area_componente_dbt.yaml",
        "sensitive_data_types.yaml",
        "sensitive_data_types.example.yaml",
    )

    delete = [
        registry / "egp_keys_batch.txt",
        registry / "batch_manifest.json",
        registry / "batch_manifest.csv",
        registry / "BATCH_AUDIT.md",
    ]

    if mode == "include-catalog":
        delete.append(registry / "egp_catalog.yaml")
    elif mode != "keep-catalog":
        raise ValueError(f"Unknown mode: {mode}")

    return CleanupSpec(delete_paths=tuple(delete), preserve_globs=preserve_globs)


def _is_preserved(path: Path, preserve_globs: tuple[str, ...]) -> bool:
    name = path.name
    for g in preserve_globs:
        if Path(name).match(g):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clean up registry artifacts from previous runs. "
            "Requires --yes to actually delete; use --dry-run to preview."
        )
    )
    parser.add_argument(
        "--mode",
        default="include-catalog",
        choices=("include-catalog", "keep-catalog"),
        help=(
            "Cleanup mode. include-catalog also removes registry/egp_catalog.yaml. "
            "Default: include-catalog."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted, but do not delete anything.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform deletions. Without this flag, the command aborts.",
    )

    args = parser.parse_args(argv)

    try:
        spec = _default_spec(args.mode)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    registry_dir = Path("registry")
    if not registry_dir.exists():
        print("registry/ directory not found; nothing to do.", file=sys.stderr)
        return 0

    # Filter to existing files only, and never delete preserved targets.
    candidates: list[Path] = []
    for p in spec.delete_paths:
        if _is_preserved(p, spec.preserve_globs):
            continue
        if p.exists():
            candidates.append(p)

    print(f"Mode   : {args.mode}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print(f"Delete : {len(candidates)} path(s)")
    for p in candidates:
        print(f"- {p.as_posix()}")

    if args.dry_run:
        return 0

    if not args.yes:
        print(
            "Refusing to delete without --yes. Re-run with --dry-run to preview, "
            "then with --yes to execute.",
            file=sys.stderr,
        )
        return 2

    errors = 0
    for p in candidates:
        try:
            p.unlink()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup tool
            errors += 1
            print(f"Failed to delete {p}: {e}", file=sys.stderr)

    if errors:
        print(f"Completed with {errors} deletion error(s).", file=sys.stderr)
        return 1

    print("Cleanup completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


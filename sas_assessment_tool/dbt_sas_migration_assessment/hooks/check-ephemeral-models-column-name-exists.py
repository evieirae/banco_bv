#!/usr/bin/env python
import sys
import time
import re
import argparse
from pathlib import Path
from typing import Any, Dict, Sequence

from utils import (
    JsonOpenError,
    add_default_args,
    get_dbt_manifest,
    get_missing_file_paths,
    get_model_sqls,
    get_models,
)


def check_sql_columns(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    exclude_pattern: str,
    include_disabled: bool,
    include_ephemeral: bool,
    required_columns: Sequence[str],
) -> int:
    # 1) Expand paths (now honoring ephemeral)
    candidate_paths = get_missing_file_paths(
        paths,
        manifest=manifest,
        include_ephemeral=include_ephemeral,  # ← new
        extensions=[".sql"],
        exclude_pattern=exclude_pattern,
    )

    # 2) Load SQL files and matching models (including ephemerals if flagged)
    sqls = get_model_sqls(
        candidate_paths,
        manifest,
        include_disabled=include_disabled,
        include_ephemeral=include_ephemeral,  # ← new
    )
    filenames = set(sqls.keys())

    models = get_models(
        manifest,
        filenames,
        include_disabled=include_disabled,
        include_ephemeral=include_ephemeral,  # ← new
    )

    status = 0
    for model in models:
        sql_path = sqls[model.filename]
        text = Path(sql_path).read_text()

        missing_in_sql = [
            col for col in required_columns
            if not re.search(rf"\b{re.escape(col)}\b", text, re.IGNORECASE)
        ]
        if missing_in_sql:
            status = 1
            print(
                f"{model.model_name} ({sql_path}): "
                f"never even referenced {missing_in_sql}"
            )

    return status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ensure each SQL model references a given set of columns"
    )
    add_default_args(parser)

    parser.add_argument(
        "--meta-columns",
        nargs="+",
        required=True,
        help="List of column names that SQL must reference",
    )
    parser.add_argument(
        "--include-ephemeral",
        action="store_true",
        help="Also check ephemeral models",
    )

    args = parser.parse_args(argv)

    try:
        manifest = get_dbt_manifest(args)
    except JsonOpenError as e:
        print(f"ERROR: could not load manifest: {e}", file=sys.stderr)
        return 1

    start = time.time()
    exit_code = check_sql_columns(
        paths=args.filenames,
        manifest=manifest,
        exclude_pattern=args.exclude,
        include_disabled=args.include_disabled,
        include_ephemeral=args.include_ephemeral,  # ← new
        required_columns=args.meta_columns,
    )
    print(f"hook ran in {time.time() - start:.2f}s")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

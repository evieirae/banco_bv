#!/usr/bin/env python
import sys
import time
import re
import argparse
from pathlib import Path
from typing import Any, Dict, Sequence

from utils import (
    add_default_args,
    add_catalog_args,
    get_dbt_manifest,
    get_dbt_catalog,
    get_missing_file_paths,
    get_model_sqls,
    get_models,
    JsonOpenError,
)

def check_sql_columns(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    catalog: Dict[str, Any],
    exclude_pattern: str,
    include_disabled: bool,
    required_columns: Sequence[str],
) -> int:
    # 1) find the SQL files we need to check
    candidate_paths = get_missing_file_paths(
        paths,
        manifest=manifest,
        include_ephemeral=False,
        extensions=[".sql"],
        exclude_pattern=exclude_pattern,
    )

    # 2) load only real, non-ephemeral, non-disabled models
    sqls = get_model_sqls(candidate_paths, manifest, include_disabled)
    filenames = set(sqls.keys())
    models = get_models(
        manifest,
        filenames,
        include_ephemeral=False,
        include_disabled=include_disabled,
    )

    status = 0
    for model in models:
        sql_path = sqls[model.filename]
        text = sql_path.read_text()

        # A) Does the SQL text even reference the required columns?
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

        # B) Did dbt actually build them? Compare against catalog.json
        node = catalog.get("nodes", {}).get(model.model_id)
        if not node:
            status = 1
            print(
                f"{model.model_name}: no entry in catalog.json—"
                f"did you run `dbt docs generate`?"
            )
        else:
            built_cols = {c.lower() for c in node.get("columns", {}).keys()}
            missing_in_catalog = [
                col for col in required_columns
                if col.lower() not in built_cols
            ]
            if missing_in_catalog:
                status = 1
                print(
                    f"{model.model_name} ({sql_path}): "
                    f"declared {missing_in_catalog} but they "
                    f"didn’t make it into the final model!"
                )

    return status

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ensure each SQL model references and builds a given set of columns"
    )
    add_default_args(parser)
    add_catalog_args(parser)

    parser.add_argument(
        "--meta-columns",
        nargs="+",
        required=True,
        help="List of column names that SQL must reference and build",
    )

    args = parser.parse_args(argv)

    try:
        manifest = get_dbt_manifest(args)
        catalog  = get_dbt_catalog(args)
    except JsonOpenError as e:
        print(f"ERROR: could not load manifest/catalog: {e}", file=sys.stderr)
        return 1

    start = time.time()
    exit_code = check_sql_columns(
        paths=args.filenames,
        manifest=manifest,
        catalog=catalog,
        exclude_pattern=args.exclude,
        include_disabled=args.include_disabled,
        required_columns=args.meta_columns,
    )
    print(f"hook ran in {time.time() - start:.2f}s")
    return exit_code

if __name__ == "__main__":
    sys.exit(main())

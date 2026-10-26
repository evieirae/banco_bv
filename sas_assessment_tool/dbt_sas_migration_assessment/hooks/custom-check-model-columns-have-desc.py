#!/usr/bin/env python

import argparse
import itertools
import os
import time
from typing import Any, Dict, Optional, Sequence, Set, Tuple

from utils import (
    JsonOpenError,
    Model,
    ModelSchema,
    add_default_args,
    get_dbt_manifest,
    get_filenames,
    get_model_schemas,
    get_model_sqls,
    get_models,
    red,
    yellow,
)


def check_column_desc(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    include_disabled: bool = False,
    include_ephemeral: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    status_code = 0
    ymls = get_filenames(paths, [".yml", ".yaml"])
    # now honor include_ephemeral
    sqls = get_model_sqls(paths, manifest, include_disabled, include_ephemeral)
    filenames = set(sqls.keys())

    # pass include_ephemeral into get_models
    models = get_models(
        manifest,
        filenames,
        include_ephemeral=include_ephemeral,
        include_disabled=include_disabled,
    )
    schemas = get_model_schemas(list(ymls.values()), filenames)

    missing: Dict[str, Set[str]] = {}
    for item in itertools.chain(models, schemas):
        if isinstance(item, ModelSchema):
            model_name = item.model_name
            missing_cols = {
                col.get("name")
                for col in item.schema.get("columns", [])
                if not col.get("description")
            }
        elif isinstance(item, Model):
            model_name = item.filename
            missing_cols = {
                key
                for key, val in item.node.get("columns", {}).items()
                if isinstance(val, dict) and not val.get("description")
            }
        else:
            continue

        if missing_cols:
            missing.setdefault(model_name, set()).update(missing_cols)

    for model_name, cols in missing.items():
        status_code = 1
        formatted = "\n- ".join(cols)
        print(
            f"{red(sqls.get(model_name))}: "
            f"following columns are missing description:\n- {yellow(formatted)}"
        )

    return status_code, missing


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    add_default_args(parser)
    # <-- new flag!
    parser.add_argument(
        "--include-ephemeral",
        action="store_true",
        help="Include ephemeral models in the description check",
    )

    args = parser.parse_args(argv)

    try:
        manifest = get_dbt_manifest(args)
    except JsonOpenError as e:
        print(f"Unable to load manifest file ({e})")
        return 1

    start = time.time()
    status_code, _ = check_column_desc(
        paths=args.filenames,
        manifest=manifest,
        include_disabled=args.include_disabled,
        include_ephemeral=args.include_ephemeral,
    )
    print(f"hook ran in {time.time() - start:.2f}s")

    return status_code

if __name__ == "__main__":
    exit(main())

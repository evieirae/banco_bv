#!/usr/bin/env python
import argparse
import os
import time
from typing import Any, Dict, Optional, Sequence

from utils import (
    JsonOpenError,
    add_default_args,
    get_dbt_manifest,
    get_filenames,
    get_missing_file_paths,
    get_model_schemas,
    get_model_sqls,
    get_models,
    red,
)


def has_description(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    exclude_pattern: str,
    include_disabled: bool = False,
    include_ephemeral: bool = False,
) -> Dict[str, Any]:
    # now pass include_ephemeral
    paths = get_missing_file_paths(
        paths, manifest, include_ephemeral=include_ephemeral, exclude_pattern=exclude_pattern  # type: ignore
    )

    status_code = 0
    ymls = get_filenames(paths, [".yml", ".yaml"])
    sqls = get_model_sqls(
        paths, manifest, include_disabled=include_disabled, include_ephemeral=include_ephemeral
    )
    filenames = set(sqls.keys())

    # include_ephemeral here as well
    models = get_models(
        manifest,
        filenames,
        include_disabled=include_disabled,
        include_ephemeral=include_ephemeral,
    )

    schemas = get_model_schemas(list(ymls.values()), filenames)

    in_models = {m.filename for m in models if m.node.get("description")}
    in_schemas = {
        s.model_name for s in schemas if s.schema.get("description")
    }
    missing = filenames.difference(in_models, in_schemas)

    for model in missing:
        status_code = 1
        print(
            f"{red(sqls.get(model))}: "
            f"does not have defined description or properties file is missing."
        )
    return {"status_code": status_code}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    add_default_args(parser)
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

    start_time = time.time()
    hook_props = has_description(
        paths=args.filenames,
        manifest=manifest,
        exclude_pattern=args.exclude,
        include_disabled=args.include_disabled,
        include_ephemeral=args.include_ephemeral,
    )

    print(f"hook ran in {time.time() - start_time:.2f}s")

    return hook_props.get("status_code")  # type: ignore


if __name__ == "__main__":
    exit(main())

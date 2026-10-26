#!/usr/bin/env python
import argparse
import os
import time
from typing import Any, Dict, Optional, Sequence

from utils import (
    JsonOpenError,
    Test,
    add_default_args,
    get_dbt_manifest,
    get_missing_file_paths,
    get_model_sqls,
    get_models,
    get_parent_childs,
)


def check_test_cnt(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    test_cnt: int,
    exclude_pattern: str,
    include_disabled: bool = False,
    include_ephemeral: bool = False,
) -> int:
    # honor include_ephemeral here
    paths = get_missing_file_paths(
        paths,
        manifest,
        include_ephemeral=include_ephemeral,
        extensions=[".sql"],
        exclude_pattern=exclude_pattern
    )

    status_code = 0
    sqls = get_model_sqls(
        paths,
        manifest,
        include_disabled=include_disabled,
        include_ephemeral=include_ephemeral,
    )
    filenames = set(sqls.keys())

    models = get_models(
        manifest,
        filenames,
        include_disabled=include_disabled,
        include_ephemeral=include_ephemeral,
    )

    for model in models:
        childs = list(
            get_parent_childs(
                manifest=manifest,
                obj=model,
                manifest_node="child_map",
                node_types=["test"],
            )
        )
        tests = [t for t in childs if isinstance(t, Test)]
        if len(tests) < test_cnt:
            status_code = 1
            print(
                f"{model.filename}: "
                f"has only {len(tests)} tests, but {test_cnt} are required."
            )

    return status_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    add_default_args(parser)

    parser.add_argument(
        "--test-cnt",
        type=int,
        default=1,
        help="Minimum number of tests required.",
    )
    parser.add_argument(
        "--include-ephemeral",
        action="store_true",
        help="Include ephemeral models when counting tests",
    )

    args = parser.parse_args(argv)

    try:
        manifest = get_dbt_manifest(args)
    except JsonOpenError as e:
        print(f"Unable to load manifest file ({e})")
        return 1

    start_time = time.time()
    status_code = check_test_cnt(
        paths=args.filenames,
        manifest=manifest,
        test_cnt=args.test_cnt,
        exclude_pattern=args.exclude,
        include_disabled=args.include_disabled,
        include_ephemeral=args.include_ephemeral,
    )
    print(f"hook ran in {time.time() - start_time:.2f}s")

    return status_code


if __name__ == "__main__":
    exit(main())

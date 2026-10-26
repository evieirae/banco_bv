# utils.py
# Minimal utilities for custom dbt-checkpoint hooks

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Set, Text, Union

from yaml import safe_load

# Defaults
DEFAULT_MANIFEST_PATH = "target/manifest.json"
DEFAULT_CATALOG_PATH = "target/catalog.json"

# --- Errors ---
class JsonOpenError(RuntimeError):
    """Raised when a JSON file cannot be loaded"""
    pass

# --- Argument helpers ---
def add_filenames_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "filenames",
        nargs="*",
        help="Filenames pre-commit believes are changed.",
    )

def add_manifest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=str,
        default=DEFAULT_MANIFEST_PATH,
        help="Location of manifest.json file.",
    )

def add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=str,
        default=".dbt-checkpoint.yaml",
        help="Path to dbt-checkpoint config file.",
    )

def add_tracking_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--is_test",
        action="store_true",
        help="Flag indicating this is a test run.",
    )

def add_exclude_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exclude",
        type=str,
        default="",
        help="Regex pattern for files to exclude.",
    )

def add_disabled_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled models in scanning.",
    )

def add_default_args(parser: argparse.ArgumentParser) -> None:
    """Add common pre-commit hook args to parser."""
    add_filenames_args(parser)
    add_manifest_args(parser)
    add_config_args(parser)
    add_tracking_args(parser)
    add_exclude_args(parser)
    add_disabled_args(parser)

# --- Manifest loading ---
def checkpoint_safe_load(stream) -> Dict[str, Any]:
    """Load YAML safely, return empty dict on empty file."""
    return safe_load(stream) or {}


def get_config_file(config_file_path: str) -> Dict[str, Any]:
    """Load .dbt-checkpoint.yaml or its .yml/.yaml alternative."""
    try:
        path = Path(config_file_path)
        if not path.exists():
            alt = path.with_suffix(".yml" if path.suffix == ".yaml" else ".yaml")
            if alt.exists():
                path = alt
        return checkpoint_safe_load(path.open())
    except FileNotFoundError:
        return {}


def get_json(json_filename: str) -> Dict[str, Any]:
    """Read and parse JSON, raising JsonOpenError on failure."""
    try:
        text = Path(json_filename).read_text(encoding="utf-8")
        return json.loads(text)
    except Exception as e:
        raise JsonOpenError(e)


def get_dbt_manifest(args) -> Dict[str, Any]:
    """
    Resolve and load the dbt manifest.json according to args and config.
    """
    manifest_path = args.manifest
    cfg = get_config_file(args.config)
    project_dir = cfg.get("dbt-project-dir")

    if manifest_path != DEFAULT_MANIFEST_PATH:
        return get_json(manifest_path)
    elif project_dir:
        return get_json(f"{project_dir}/target/manifest.json")
    else:
        return get_json(manifest_path)

# --- File path expansion (stub) ---
def get_missing_file_paths(
    paths: Sequence[str],
    manifest: Optional[Dict[str, Any]] = None,
    include_ephemeral: bool = False,
    extensions: Sequence[str] = [".sql", ".yml", ".yaml"],
    exclude_pattern: str = "",
) -> List[str]:
    """
    Return only real files from the input list (stub for related-patch expansion).
    """
    return [p for p in paths if os.path.isfile(p)]

# --- Model SQL resolution ---
def get_filenames(
    paths: Sequence[str],
    extensions: Optional[Sequence[str]] = None,
) -> Dict[str, Path]:
    """Map filename (stem) to Path for the given extensions."""
    result: Dict[str, Path] = {}
    for p in paths:
        f = Path(p)
        if extensions and f.suffix not in extensions:
            continue
        result[f.stem] = f
    return result


def get_ephemeral(manifest: Dict[str, Any]) -> List[str]:
    """List names of ephemeral models."""
    out: List[str] = []
    for key, node in manifest.get("nodes", {}).items():
        if node.get("config", {}).get("materialized") == "ephemeral":
            parts = key.split('.')
            if parts[0] == 'model':
                out.append(parts[-1])
    return out


def get_macro_sqls(
    paths: Sequence[str], manifest: Dict[str, Any]
) -> Dict[str, Path]:
    """Identify which SQL files are actually macros."""
    sqls = get_filenames(paths, [".sql"])
    macro_paths = [m["path"] for m in manifest.get("macros", {}).values()]
    macro_sqls = get_filenames(macro_paths, [".sql"])
    return {k: v for k, v in sqls.items() if k in macro_sqls}


def get_disabled(
    manifest: Dict[str, Any], include_disabled: bool = False
) -> List[str]:
    """List disabled model filenames (stem)."""
    out: List[str] = []
    for key, node in manifest.get("disabled", {}).items():
        parts = key.split('.')
        if parts[0] == "model" and not include_disabled:
            out.append(parts[-1])
    return out


def get_model_sqls(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    include_disabled: bool = False,
) -> Dict[str, Path]:
    """Return non-ephemeral, non-macro, non-disabled model SQL files."""
    ephemeral = get_ephemeral(manifest)
    sqls = get_filenames(paths, [".sql"])
    macro_sqls = get_macro_sqls(paths, manifest)
    disabled = get_disabled(manifest, include_disabled)

    return {
        k: v
        for k, v in sqls.items()
        if k not in macro_sqls and k not in ephemeral and k not in disabled
    }

# --- Model discovery ---
@dataclass
class Model:
    model_id: str
    model_name: str
    filename: str
    node: Dict[str, Any]


def get_models(
    manifest: Dict[str, Any],
    filenames: Set[str],
    include_ephemeral: bool = False,
    include_disabled: bool = False,
) -> Generator[Model, None, None]:
    """Yield Model for each changed filename in the manifest."""
    for key, node in manifest.get("nodes", {}).items():
        # skip ephemeral
        if not include_ephemeral and node.get("config", {}).get("materialized") == "ephemeral":
            continue
        # skip disabled
        if not include_disabled and not node.get("config", {}).get("enabled", True):
            continue

        parts = key.split('.')
        version = node.get("version")
        if version and parts[-1] == f"v{version}":
            candidates = [parts[-2], f"{parts[-2]}_v{version}"]
        else:
            candidates = [parts[-1]]

        if parts[0] == "model":
            for fn in candidates:
                if fn in filenames:
                    yield Model(key, node.get("name"), fn, node)

def add_catalog_args(parser: argparse.ArgumentParser) -> None:
    """Add --catalog flag (defaults to target/catalog.json)."""
    parser.add_argument(
        "--catalog",
        type=str,
        default=DEFAULT_CATALOG_PATH,
        help="Location of dbt's catalog.json file.",
    )

def get_dbt_catalog(args) -> Dict[str, Any]:
    """Load and return the compiled catalog.json."""
    try:
        return get_json(args.catalog)
    except Exception as e:
        raise JsonOpenError(e)

def get_model_sqls(
    paths: Sequence[str],
    manifest: Dict[str, Any],
    include_disabled: bool = False,
    include_ephemeral: bool = False,
) -> Dict[str, Any]:
    """
    Return all changed .sql models, optionally including disabled or ephemeral.
    """
    # collect ephemeral model filenames
    ephemeral = [] if include_ephemeral else get_ephemeral(manifest)
    sqls = get_filenames(paths, [".sql"])
    macro_sqls = get_macro_sqls(paths, manifest)
    disabled = get_disabled(manifest, include_disabled)

    return {
        name: path
        for name, path in sqls.items()
        if name not in macro_sqls
        and name not in ephemeral
        and name not in disabled
    }

@dataclass
class ModelSchema:
    model_name: str
    filename: str
    schema: Dict[str, any]
    file: Path

def get_model_schemas(
    yml_files: Sequence[Path],
    filenames: Set[str],
) -> Generator[ModelSchema, None, None]:
    """
    Yield ModelSchema for any model in the given YAML files whose name
    appears in filenames.
    """
    for yml_file in yml_files:
        raw = safe_load(yml_file.open()) or {}
        for model in raw.get("models", []):
            name = model.get("name")
            if name and name in filenames:
                yield ModelSchema(
                    model_name=name,
                    filename=yml_file.stem,
                    schema=model,
                    file=yml_file,
                )

def red(text: any) -> str:
    """Wrap text in ANSI red."""
    return f"\033[91m{text}\033[0m"

def yellow(text: any) -> str:
    """Wrap text in ANSI yellow."""
    return f"\033[93m{text}\033[0m"

@dataclass
class Test:
    test_id: str
    test_type: str
    test_name: str
    node: Dict[str, Any]

def get_parent_childs(
    manifest: Dict[str, Any],
    obj: Any,
    manifest_node: str,
    node_types: List[str],
) -> Generator[Union[Test, Any], None, None]:
    """
    For a given obj (Model), yields its downstream children of the given node_types
    (e.g. ["test"]) by looking in manifest[manifest_node] (e.g. "child_map").
    """
    # e.g. manifest_node == "child_map"
    child_map = manifest.get(manifest_node, {})
    for parent_id, child_ids in child_map.items():
        # match this model
        if parent_id != obj.model_id:
            continue

        for node_id in child_ids:
            kind = node_id.split(".")[0]
            if kind not in node_types:
                continue

            node = manifest.get("nodes", {}).get(node_id)
            if not node:
                continue

            if kind == "test":
                # determine test type by tag or metadata
                ttype = "data" if "data" in node.get("tags", []) else "schema"
                tname = node.get("test_metadata", {}).get("name") or node.get("name") or ""
                yield Test(
                    test_id=node_id,
                    test_type=ttype,
                    test_name=tname,
                    node=node,
                )
            else:
                # you can add support for other kinds here if needed
                yield node

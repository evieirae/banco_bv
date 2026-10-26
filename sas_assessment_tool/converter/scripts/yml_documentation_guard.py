#!/usr/bin/env python3
"""
Guardrail: qualidade mínima dos ``stem.yml`` de intermediate/marts (DBT_BQ).

Complementa ``model_yml_guard`` (paridade ficheiro) — evita YAMLs stub com
``columns: []`` ou descrições placeholder.

Alinhado a ``.cursor/rules/01_sas_to_dbt.mdc`` §5 (documentação rica).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .model_yml_guard import iter_int_mart_model_files

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[misc, assignment]

# Descrição mínima por coluna e por modelo (caracteres).
MIN_COLUMN_DESCRIPTION_LEN = 20
MIN_MODEL_DESCRIPTION_LEN = 40

# Substrings na ``description`` do modelo (nível bloco) que indicam stub / incompleto.
MODEL_DESCRIPTION_PLACEHOLDER_SUBSTRINGS: tuple[str, ...] = (
    "refinar na curadoria",
    "lista de colunas a completar",
    "granularidade e colunas devem ser refinadas",
    "a completar",
    "documentação de colunas a enriquecer",
    "placeholder",
    "todo:",
)


def _load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML é necessário para yml_documentation_guard")
    raw = path.read_text(encoding="utf-8", errors="replace")
    return yaml.safe_load(raw)


def _model_blocks(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    models = doc.get("models")
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict)]


def _normalize_description(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def _validate_model_block(
    block: dict[str, Any],
    *,
    expected_name: str,
    yml_rel: str,
) -> list[str]:
    errs: list[str] = []
    name = block.get("name")
    if not isinstance(name, str) or name.strip() != expected_name:
        return [f"`name` do bloco deve ser `{expected_name}` (ficheiro `{yml_rel}`)"]

    desc = block.get("description")
    desc_s = desc if isinstance(desc, str) else (str(desc) if desc is not None else "")
    desc_norm = _normalize_description(desc_s)
    if len(desc_s.strip()) < MIN_MODEL_DESCRIPTION_LEN:
        errs.append(
            f"description do modelo muito curta (<{MIN_MODEL_DESCRIPTION_LEN} caracteres)"
        )
    for sub in MODEL_DESCRIPTION_PLACEHOLDER_SUBSTRINGS:
        if sub.lower() in desc_norm:
            errs.append(f"description do modelo contém texto placeholder proibido ({sub!r})")
            break

    meta = block.get("meta")
    if not isinstance(meta, dict):
        errs.append("falta bloco `meta:` no modelo")
    else:
        cron = meta.get("cron")
        if not isinstance(cron, str) or not cron.strip():
            errs.append("`meta.cron` ausente ou vazio")

    cols = block.get("columns")
    if cols is None:
        errs.append("falta chave `columns` (obrigatória lista não vazia)")
    elif not isinstance(cols, list):
        errs.append("`columns` deve ser uma lista")
    elif len(cols) == 0:
        errs.append("`columns` não pode ser lista vazia")
    else:
        for i, col in enumerate(cols):
            if not isinstance(col, dict):
                errs.append(f"columns[{i}] deve ser um objeto com name e description")
                continue
            cname = col.get("name")
            if not isinstance(cname, str) or not cname.strip():
                errs.append(f"columns[{i}]: name em falta ou inválido")
            cdesc = col.get("description")
            cdesc_s = cdesc if isinstance(cdesc, str) else (str(cdesc) if cdesc is not None else "")
            if len(cdesc_s.strip()) < MIN_COLUMN_DESCRIPTION_LEN:
                label = cname if isinstance(cname, str) and cname.strip() else str(i)
                errs.append(
                    f"coluna `{label}`: description muito curta (<{MIN_COLUMN_DESCRIPTION_LEN} caracteres)"
                )
    return errs


def check_int_mart_yml_documentation(models_dir: Path) -> list[str]:
    """
    Valida cada ``stem.yml`` irmão de modelos ``intermediate``/``marts``.

    Returns:
        Lista de mensagens de erro (prefixadas com path relativo a ``models_dir``).
    """
    errors: list[str] = []
    if yaml is None:
        return ["PyYAML não instalado — não é possível validar documentação YAML"]
    if not models_dir.is_dir():
        return errors

    for model_path in iter_int_mart_model_files(models_dir):
        yml = model_path.with_suffix(".yml")
        if not yml.is_file():
            continue
        rel = yml.relative_to(models_dir).as_posix()
        stem = model_path.stem
        try:
            doc = _load_yaml(yml)
        except Exception as ex:
            errors.append(f"{rel}: YAML inválido ou ilegível ({ex})")
            continue
        blocks = _model_blocks(doc)
        target = next((b for b in blocks if isinstance(b.get("name"), str) and b["name"].strip() == stem), None)
        if target is None:
            errors.append(f"{rel}: nenhum bloco `models:` com `name: {stem}`")
            continue
        for msg in _validate_model_block(target, expected_name=stem, yml_rel=rel):
            errors.append(f"{rel}: {msg}")
    return errors


def yml_documentation_ok(errors: list[str]) -> bool:
    return len(errors) == 0

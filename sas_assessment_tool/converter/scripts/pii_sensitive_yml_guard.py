#!/usr/bin/env python3
"""
Guardrail: colunas catalogadas como sensíveis em ``registry/sensitive_data_types.yaml``
devem declarar ``policy_tags`` nos YAMLs irmãos (intermediate/marts), alinhado ao Agente 2.

Usado por ``batch_pipeline.compute_batch_checks`` e ``draft_gate``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .model_yml_guard import iter_int_mart_model_files
from .pii_reference import extract_pii_interno_var_names

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[misc, assignment]

PII_DADOS_CONFIDENCIAIS_RE = re.compile(r"\bPII_DADOS_CONFIDENCIAIS\b")

# Tipos lógicos (id em sensitive_data_types.yaml) para os quais, em modo estrito,
# exige-se pelo menos uma var PII_INTERNO_* do conjunto inferido do componente
# (não basta só PII_DADOS_CONFIDENCIAIS) quando ``allowed_pii_interno`` não é vazio.
STRICT_REFERENCE_ENTRY_IDS: frozenset[str] = frozenset(
    {
        "cpf",
        "cnpj",
        "numero_contrato",
        "nome_titular",
        "email",
        "telefone",
        "documento_identificacao",
        "matricula_colaborador",
    }
)


def _load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML é necessário para pii_sensitive_yml_guard")
    raw = path.read_text(encoding="utf-8", errors="replace")
    return yaml.safe_load(raw)


def load_sensitive_matchers(sensitive_path: Path) -> list[tuple[str, list[tuple[str, re.Pattern[str] | None]]]]:
    """
    Carrega entradas com ``requires_pii: true`` e devolve lista de
    (entry_id, [(pattern_raw, compiled_regex_ou_None)]).
    Regex: padrão em ``match`` que começa por ``re:`` (resto compilado com IGNORECASE).
    Caso contrário: correspondência por substring case-insensitive no nome da coluna.
    """
    data = _load_yaml(sensitive_path)
    entries = (data or {}).get("entries") or []
    out: list[tuple[str, list[tuple[str, re.Pattern[str] | None]]]] = []
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        if not ent.get("requires_pii", True):
            continue
        eid = str(ent.get("id") or "unknown").strip()
        patterns: list[tuple[str, re.Pattern[str] | None]] = []
        for m in ent.get("match") or []:
            s = str(m).strip()
            if not s:
                continue
            if s.lower().startswith("re:"):
                rest = s[3:].strip()
                try:
                    patterns.append((s, re.compile(rest, re.IGNORECASE)))
                except re.error:
                    patterns.append((s, None))
            else:
                patterns.append((s, None))
        if patterns:
            out.append((eid, patterns))
    return out


def column_matches_sensitive(
    col_name: str, matchers: list[tuple[str, list[tuple[str, re.Pattern[str] | None]]]]
) -> list[str]:
    """Devolve lista de ``entry_id`` que casam com o nome da coluna (sem duplicar o mesmo id)."""
    col_lower = col_name.lower()
    hit_ids: list[str] = []
    for eid, plist in matchers:
        for _raw, rx in plist:
            if rx is not None:
                if rx.search(col_name):
                    hit_ids.append(eid)
                    break
            elif _raw.lower() in col_lower:
                hit_ids.append(eid)
                break
    return hit_ids


def _policy_tags_block_ok(
    policy_text: str,
    allowed_pii_interno: frozenset[str],
    *,
    allow_confidenciais_without_interno: bool = False,
) -> bool:
    """
    True se ``policy_tags`` cumpre o contrato de PII.

    Por defeito (``allow_confidenciais_without_interno=False``): não basta
    ``PII_DADOS_CONFIDENCIAIS`` — exige pelo menos um ``PII_INTERNO_*`` presente
    em ``allowed_pii_interno`` quando este conjunto não é vazio; com conjunto
    vazio, aceita qualquer ``PII_INTERNO_*`` encontrado no texto.
    """
    if not policy_text or not policy_text.strip():
        return False
    found = extract_pii_interno_var_names(policy_text)
    has_conf = bool(PII_DADOS_CONFIDENCIAIS_RE.search(policy_text))

    if allowed_pii_interno:
        if any(v in allowed_pii_interno for v in found):
            return True
        if allow_confidenciais_without_interno and has_conf:
            return True
        return False

    if found:
        return True
    if allow_confidenciais_without_interno and has_conf:
        return True
    return False


def _column_policy_tags_text(col: dict[str, Any]) -> str:
    pt = col.get("policy_tags")
    if pt is None:
        return ""
    if isinstance(pt, str):
        return pt
    if isinstance(pt, list):
        parts: list[str] = []
        for x in pt:
            if isinstance(x, str):
                parts.append(x)
            else:
                parts.append(str(x))
        return "\n".join(parts)
    return str(pt)


def _iter_model_blocks(yml_path: Path) -> list[dict[str, Any]]:
    try:
        doc = _load_yaml(yml_path)
    except Exception:
        return []
    if not isinstance(doc, dict):
        return []
    models = doc.get("models")
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict)]


def check_sensitive_column_policy_tags(
    models_dir: Path,
    sensitive_path: Path,
    allowed_pii_interno: frozenset[str] | None,
    *,
    reference_interno_strict: bool = False,
    reference_pii_var_suggestion: str = "",
    allow_confidenciais_without_interno: bool = False,
) -> tuple[list[str], int, int]:
    """
    Para cada ``stem.yml`` irmão de ``.sql``/``.py`` em intermediate/marts, verifica colunas
    cujo ``name`` casa com ``sensitive_data_types.yaml`` (``requires_pii: true``).

    Com ``reference_interno_strict=True`` e ``allowed_pii_interno`` não vazio, colunas cujo
    match inclui um ``id`` em ``STRICT_REFERENCE_ENTRY_IDS`` devem declarar em ``policy_tags``
    pelo menos uma das variáveis ``PII_INTERNO_*`` presentes em ``allowed_pii_interno``
    (inferidas dos YAML em ``models/**/04_marts/``, com fallback documentado em ``pii_reference``);
    só ``PII_DADOS_CONFIDENCIAIS`` não chega para esses tipos.

    ``allow_confidenciais_without_interno=True`` restaura o comportamento legado em que só
    ``PII_DADOS_CONFIDENCIAIS`` satisfaz o bloco quando há conjunto ``allowed`` não vazio.

    Returns:
        (mensagens_erro, total_colunas_sensiveis_encontradas, total_em_falta)
    """
    errors: list[str] = []
    if not models_dir.is_dir():
        return errors, 0, 0
    if not sensitive_path.is_file():
        return [f"Catálogo sensível em falta: {sensitive_path}"], 0, 0

    matchers = load_sensitive_matchers(sensitive_path)
    sensitive_hits = 0
    missing = 0
    allowed_eff = allowed_pii_interno or frozenset()
    permit_msg = (
        ", ".join(sorted(allowed_eff))
        if allowed_eff
        else "(nenhuma variável inferida — use `PII_INTERNO_*` explícita nos YAML de `04_marts`)"
    )

    for model_path in iter_int_mart_model_files(models_dir):
        yml = model_path.with_suffix(".yml")
        if not yml.is_file():
            continue
        rel = yml.relative_to(models_dir)
        for block in _iter_model_blocks(yml):
            cols = block.get("columns")
            if not isinstance(cols, list):
                continue
            for col in cols:
                if not isinstance(col, dict):
                    continue
                name = col.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                matched_ids = column_matches_sensitive(name, matchers)
                if not matched_ids:
                    continue
                sensitive_hits += 1
                pt_text = _column_policy_tags_text(col)
                if not pt_text.strip():
                    missing += 1
                    errors.append(
                        f"{rel}: coluna `{name}` (sensível: {', '.join(matched_ids)}) sem `policy_tags`"
                    )
                    continue
                if not _policy_tags_block_ok(
                    pt_text,
                    allowed_eff,
                    allow_confidenciais_without_interno=allow_confidenciais_without_interno,
                ):
                    missing += 1
                    errors.append(
                        f"{rel}: coluna `{name}` — `policy_tags` deve incluir pelo menos uma variável "
                        f"`PII_INTERNO_*` entre as inferidas do projeto (referência: `models/**/04_marts/**/*.yml`; "
                        f"permitido neste repo: {permit_msg}). `PII_DADOS_CONFIDENCIAIS` sozinho não cumpre."
                    )
                    continue
                strict_hit = [mid for mid in matched_ids if mid in STRICT_REFERENCE_ENTRY_IDS]
                if (
                    reference_interno_strict
                    and allowed_eff
                    and strict_hit
                    and not any(v in allowed_eff for v in extract_pii_interno_var_names(pt_text))
                ):
                    missing += 1
                    hint = (
                        (reference_pii_var_suggestion or "").strip()
                        or "PII_INTERNO_* mais frequente nos YAMLs em `04_marts`"
                    )
                    errors.append(
                        f"{rel}: coluna `{name}` (tipos sensíveis: {', '.join(strict_hit)}) — modo "
                        "`reference_interno_strict`: inclua em `policy_tags` pelo menos uma variável "
                        f"`PII_INTERNO_*` permitida pelo projeto ({', '.join(sorted(allowed_eff))}); "
                        f"sugestão de referência: `{hint}`. Só `PII_DADOS_CONFIDENCIAIS` não cumpre para estes tipos."
                    )

    return errors, sensitive_hits, missing

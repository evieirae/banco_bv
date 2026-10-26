"""
Resolução de pastas sandbox (`converted_egps/.../<egp_key>/`).

- Legado: `converted_egps/dbt|databricks/<egp_key>/`
- Por run: `converted_egps/<YYYY-MM-DD>_<git-short>_dbt|databricks/<egp_key>/`
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

_RUN_PARENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_[A-Za-z0-9]+_(dbt|databricks)$",
)


def _git_short_head(repo_root: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip()[:40]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def sandbox_run_dir_name(*, repo_root: Path, target: str) -> str:
    """Nome da pasta-mãe de um run: `<DATA>_<sha>_<dbt|databricks>`."""
    t = str(target).strip().lower()
    if t not in ("dbt", "databricks"):
        raise ValueError(f"target must be 'dbt' or 'databricks', got {target!r}")
    d = date.today().isoformat()
    sha = _git_short_head(repo_root)
    return f"{d}_{sha}_{t}"


def expected_sandbox_run_parent(converter_dir: Path, arch: str) -> Path:
    """
    Pai directo das pastas `<egp_key>` para um novo run (PASSO 3A).

    Ex.: `.../converted_egps/2026-05-12_abcd123_dbt/`
    """
    name = sandbox_run_dir_name(repo_root=converter_dir, target=arch)
    return (Path(converter_dir) / "converted_egps" / name).resolve()


def _dir_mtime(p: Path) -> float:
    try:
        return float(p.stat().st_mtime)
    except OSError:
        return 0.0


def _arch_from_run_parent(name: str) -> str | None:
    m = _RUN_PARENT_RE.match(name)
    if not m:
        return None
    return m.group(1)


def find_converted_sandbox(
    converter_dir: Path | str,
    egp_key: str,
    *,
    preferred_arch: str | None = None,
) -> tuple[str | None, Path | None]:
    """
    Localiza o sandbox do EGP.

    Prioridade:
    1) Legado `converted_egps/dbt/<egp_key>` ou `.../databricks/<egp_key>` (se existir)
    2) Layout por run: `converted_egps/<DATA>_<sha>_dbt|databricks/<egp_key>/`
       — escolhe o pai com maior mtime (empate: nome lexicográfico maior).
    """
    root = Path(converter_dir).resolve()
    ce = root / "converted_egps"
    key = str(egp_key).strip()
    if not key:
        return None, None

    pref = (preferred_arch or "").strip().lower()
    if pref and pref not in ("dbt", "databricks"):
        pref = ""

    def consider_legacy(arch: str) -> tuple[str, Path] | None:
        p = ce / arch / key
        if p.is_dir():
            return arch, p.resolve()
        return None

    candidates: list[tuple[str, Path]] = []

    if not pref or pref == "dbt":
        hit = consider_legacy("dbt")
        if hit:
            candidates.append(hit)
    if not pref or pref == "databricks":
        hit = consider_legacy("databricks")
        if hit:
            candidates.append(hit)

    # Legado tem prioridade sobre layout novo (README).
    if candidates:
        if len(candidates) == 1:
            a, p = candidates[0]
            return a, p
        # Ambos existem: preferir o pedido em preferred_arch; senão dbt.
        if pref:
            for a, p in candidates:
                if a == pref:
                    return a, p
        for a, p in candidates:
            if a == "dbt":
                return a, p
        return candidates[0]

    # Layout por run sob converted_egps/
    run_hits: list[tuple[float, str, str, Path]] = []
    if ce.is_dir():
        for parent in ce.iterdir():
            if not parent.is_dir():
                continue
            arch = _arch_from_run_parent(parent.name)
            if arch is None:
                continue
            if pref and arch != pref:
                continue
            child = parent / key
            if child.is_dir():
                run_hits.append((_dir_mtime(parent), parent.name, arch, child.resolve()))

    if not run_hits:
        return None, None

    run_hits.sort(key=lambda t: (t[0], t[1]))
    _mt, _nm, arch, path = run_hits[-1]
    return arch, path


def resolve_sandbox_project_dir(
    converter_dir: Path | str,
    egp_key: str,
    *,
    converted_root: str = "auto",
) -> Path:
    """
    Pasta do projecto sandbox (`.../<egp_key>` com `models/` típico).

    `converted_root='auto'`: legado ou layout por run (mesma regra que `find_converted_sandbox`).
    Caso contrário: `converter_dir / converted_root / egp_key`.
    """
    root = Path(converter_dir).resolve()
    key = str(egp_key).strip()
    cr = str(converted_root).strip()

    if cr == "auto" or not cr:
        _a, p = find_converted_sandbox(root, key)
        if p is not None:
            return p
        return (root / "converted_egps" / "dbt" / key).resolve()

    return (root / cr / key).resolve()

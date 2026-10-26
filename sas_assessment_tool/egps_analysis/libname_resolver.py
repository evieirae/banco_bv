#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resolução libname -> path físico para um .txt do egps_extractor.

Usado pela linhagem por PATH (não por nome de alias, que é mutável por EGP).
Lê os LIBNAME do corpo do .txt (após END_METADATA), resolve &macro via %let do
mesmo arquivo, normaliza o path e descarta engines não-disco e libs temp/work.
Validado por workflow adversarial (42/42 merges de alias corretos).
"""
import re

_NON_DISK_ENGINES = {
    "ORACLE", "SYBASE", "SYBASEIQ", "SQLSVR", "ODBC", "TERADATA", "POSTGRES", "POSTGRESQL",
    "BIGQUERY", "HADOOP", "META", "OLEDB", "DB2", "SPDE", "SASIOLA", "JDBC", "NETEZZA",
    "GREENPLM", "XML", "XMLV2", "EXCEL", "EXCELCS", "XLSX", "PCFILES",
}
_LIBNAME_RE = re.compile(r"\blibname\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.*?);", re.IGNORECASE | re.DOTALL)
_LET_RE = re.compile(r"%let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]*);", re.IGNORECASE)
_QUOTED_RE = re.compile(r"""(['"])(.*?)\1""")
_MACRO_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_]*)\.?")
_TEMP_SEG_RE = re.compile(r"(^|/)(saswork|sastmp|tmp|temp|work|_work)(/|$)")


def _strip_sas_comments(s):
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"(?m)^\s*\*[^;]*;", " ", s)
    s = re.sub(r"%\*[^;]*;", " ", s)
    return s


def _norm_path(p):
    p = p.strip().strip("'\"").strip().replace("\\", "/")
    return re.sub(r"/+", "/", p).rstrip("/").lower()


def _resolve_macros(val, lets):
    for _ in range(4):
        if "&" not in val:
            break
        nv = _MACRO_RE.sub(lambda m: lets.get(m.group(1).upper(), m.group(0)), val)
        if nv == val:
            break
        val = nv
    return val


def parse_libmap_from_txt(filepath):
    """Devolve {LIBREF_UPPER: set(paths físicos)} dos LIBNAME de disco no corpo do .txt."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except OSError:
        return {}
    i = txt.find("END_METADATA")
    code = _strip_sas_comments(txt[i:] if i >= 0 else txt)
    lets = {}
    for m in _LET_RE.finditer(code):
        lets[m.group(1).upper()] = m.group(2).strip().strip("'\"").strip()
    out = {}
    for m in _LIBNAME_RE.finditer(code):
        name = m.group(1).upper()
        rest = m.group(2).strip()
        toks = rest.split()
        first = toks[0].upper() if toks else ""
        if first in ("CLEAR", "LIST", "_ALL_") or first in _NON_DISK_ENGINES:
            continue
        for q in _QUOTED_RE.finditer(rest):
            raw = q.group(2)
            if "/" not in raw and "\\" not in raw:
                continue
            p = _norm_path(_resolve_macros(raw, lets))
            if "&" in p or _TEMP_SEG_RE.search(p):
                continue
            out.setdefault(name, set()).add(p)
    return out

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análise de tabelas SAS/Local agrupadas pelo PATH FÍSICO do libname (não pelo nome
do alias, que é mutável por EGP).

v2 (pós-verificação adversarial):
  - join projeto↔stem robusto: stem exato + filhos de folder-project (area__proj__*)
    + stem sem prefixo de área (SAS_UC4) → recupera ~750 ocorrências antes perdidas.
  - higiene do denominador: exclui não-tabelas (placeholders {macro}, membro templado
    por &/{}, DICTIONARY, source_type 'macro no membro') e libs TEMP/WORK (transientes).
  - exclui engines não-disco (DB + XML/EXCEL).
  - remove comentários SAS antes de parsear LIBNAME.
  - segmenta o "mesmo nome em >1 path": literal-estável vs snapshot-datado vs macro.
Caveat: paths normalizados em minúsculas (merge validado em 42/42 pares; Linux é
case-sensitive, mas o mesmo diretório é escrito de forma consistente na prática).
"""
import csv, glob, os, re, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TXT_DIR = os.path.join(ROOT, "text_egps")
REP06 = os.path.join(ROOT, "06_prontidao_tabela.csv")
OUTDIR = os.path.join(ROOT, "docs/analises")

NON_DISK_ENGINES = {"ORACLE","SYBASE","SYBASEIQ","SQLSVR","ODBC","TERADATA","POSTGRES","POSTGRESQL",
    "BIGQUERY","HADOOP","META","OLEDB","DB2","SPDE","SASIOLA","JDBC","NETEZZA","GREENPLM",
    "XML","XMLV2","EXCEL","EXCELCS","XLSX","PCFILES"}
LIBNAME_RE = re.compile(r'\blibname\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.*?);', re.IGNORECASE | re.DOTALL)
LET_RE = re.compile(r'%let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]*);', re.IGNORECASE)
QUOTED_RE = re.compile(r"""(['"])(.*?)\1""")
MACRO_RE = re.compile(r'&([A-Za-z_][A-Za-z0-9_]*)\.?')
TEMP_SEG_RE = re.compile(r'(^|/)(saswork|sastmp|tmp|temp|work|_work)(/|$)')
DATED_RE = re.compile(r'(_|\b)(19|20)\d{2}(0[1-9]|1[0-2])(\d{2})?$|_\d{6,8}$')


def strip_sas_comments(s):
    s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL)        # /* ... */
    s = re.sub(r'(?m)^\s*\*[^;]*;', ' ', s)                  # * ...;  (linha)
    s = re.sub(r'%\*[^;]*;', ' ', s)                          # %* ...;
    return s


def body_text(txt):
    i = txt.find("END_METADATA")
    return strip_sas_comments(txt[i:] if i >= 0 else txt)


def let_dict(code):
    d = {}
    for m in LET_RE.finditer(code):           # last-wins (dict sobrescreve)
        d[m.group(1).upper()] = m.group(2).strip().strip('\'"').strip()
    return d


def resolve_macros(s, lets, passes=4):
    for _ in range(passes):
        if "&" not in s:
            break
        new = MACRO_RE.sub(lambda m: lets.get(m.group(1).upper(), m.group(0)), s)
        if new == s:
            break
        s = new
    return s


def norm_path(p):
    p = p.strip().strip('\'"').strip().replace("\\", "/")
    p = re.sub(r'/+', '/', p).rstrip('/')
    return p.lower()


def is_temp_path(p):
    return bool(TEMP_SEG_RE.search(p))


def parse_libnames(code, lets):
    out = collections.defaultdict(set)
    for m in LIBNAME_RE.finditer(code):
        name = m.group(1).upper()
        rest = m.group(2).strip()
        toks = rest.split()
        first = toks[0].upper() if toks else ""
        if first in ("CLEAR", "LIST", "_ALL_") or first in NON_DISK_ENGINES:
            continue
        for q in QUOTED_RE.finditer(rest):
            raw = q.group(2)
            if "/" not in raw and "\\" not in raw:
                continue
            p = norm_path(resolve_macros(raw, lets))
            if "&" in p or is_temp_path(p):     # macro não resolvido / transiente
                continue
            out[name].add(p)
    return out


def is_not_real_table(lib, member, source_type):
    art = f"{lib}.{member}"
    if any(c in art for c in "{}&"):
        return True
    if lib == "DICTIONARY":
        return True
    if "macro no membro" in (source_type or "").lower():
        return True
    return False


def main():
    # 1) libnames por stem do .txt
    stem_lib = {}
    for fp in glob.glob(os.path.join(TXT_DIR, "*.txt")):
        stem = os.path.basename(fp)[:-4]
        code = body_text(open(fp, encoding="utf-8", errors="replace").read())
        stem_lib[stem] = parse_libnames(code, let_dict(code))
    all_stems = list(stem_lib)

    # 1b) índice para join projeto↔stem: por prefixo (folder) e por tail (sem área)
    children = collections.defaultdict(list)   # "area__proj" -> [stems filhos]
    tail_index = collections.defaultdict(list)  # tail (sem 1º segmento) -> [stems]
    for s in all_stems:
        if "__" in s:
            children[s.rsplit("__", 1)[0]].append(s)  # pai imediato
        tail_index[s.split("__", 1)[-1]].append(s)

    cache = {}
    def libs_for_project(P):
        if P in cache:
            return cache[P]
        merged = collections.defaultdict(set)
        cands = set()
        if P in stem_lib:
            cands.add(P)
        cands.update(children.get(P, []))             # folder-project: filhos
        if "__" in P:
            cands.update(tail_index.get(P.split("__", 1)[1], []))  # SAS_UC4: stem sem área
        for s in cands:
            for lib, paths in stem_lib.get(s, {}).items():
                merged[lib].update(paths)
        cache[P] = merged
        return merged

    # 2) table_in SAS/Local do 06
    recs = []                       # (path, member, lib, proj)
    unresolved = collections.Counter()
    n_saslocal = excl_nottable = 0
    for r in csv.DictReader(open(REP06, encoding="utf-8")):
        if r["category"] != "table_in" or "SAS/LOCAL" not in (r["source_type"] or "").upper():
            continue
        art = (r["artifact"] or "").strip().upper()
        if "." not in art:
            continue
        lib, member = art.split(".", 1)
        if is_not_real_table(lib, member, r["source_type"]):
            excl_nottable += 1
            continue
        n_saslocal += 1
        paths = libs_for_project(r["project"]).get(lib, set())
        if not paths:
            unresolved[lib] += 1
            continue
        for p in paths:
            recs.append((p, member, lib, r["project"]))

    # ---- B) tabelas por path ----
    by_path_members = collections.defaultdict(set)
    by_path_aliases = collections.defaultdict(set)
    for p, member, lib, proj in recs:
        by_path_members[p].add(member)
        by_path_aliases[p].add(lib)

    # ---- A) mesmo membro em paths diferentes (segmentado) ----
    member_paths = collections.defaultdict(set)
    for p, member, lib, proj in recs:
        member_paths[member].add(p)
    def seg(m):
        if "{" in m or "&" in m:
            return "macro"
        return "snapshot_datado" if DATED_RE.search(m) else "literal_estavel"
    same_multi = {m: ps for m, ps in member_paths.items() if len(ps) > 1}
    seg_counts = collections.Counter(seg(m) for m in same_multi)

    # ---- CSVs ----
    with open(os.path.join(OUTDIR, "saslocal_tabelas_por_path.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path_fisico", "n_tabelas", "n_libname_aliases", "libname_aliases", "amostra_tabelas"])
        for p in sorted(by_path_members, key=lambda x: -len(by_path_members[x])):
            mem = sorted(by_path_members[p])
            w.writerow([p, len(mem), len(by_path_aliases[p]),
                        " | ".join(sorted(by_path_aliases[p])), " | ".join(mem[:15])])
    with open(os.path.join(OUTDIR, "saslocal_mesmo_nome_paths_distintos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["membro", "segmento", "n_paths_distintos", "paths"])
        for m in sorted(same_multi, key=lambda x: -len(same_multi[x])):
            w.writerow([m, seg(m), len(same_multi[m]), " | ".join(sorted(same_multi[m]))])

    multi_alias = {p: a for p, a in by_path_aliases.items() if len(a) > 1}
    print(f"table_in SAS/Local (após excluir não-tabelas: {excl_nottable}): {n_saslocal}")
    print(f"  resolvidos a path: {len(recs)} registros | NÃO resolvidos: {sum(unresolved.values())} ocorr. ({len(unresolved)} librefs)")
    print(f"\nB) PATHS FÍSICOS distintos: {len(by_path_members)}")
    for p in sorted(by_path_members, key=lambda x: -len(by_path_members[x]))[:12]:
        print(f"   {len(by_path_members[p]):4} tab  {p}  [aliases: {','.join(sorted(by_path_aliases[p]))[:50]}]")
    print(f"\n   paths com >1 libname-alias (nome != mas path igual): {len(multi_alias)}")
    for p in sorted(multi_alias, key=lambda x: -len(multi_alias[x]))[:6]:
        print(f"     {len(multi_alias[p])} aliases -> {p}")
    print(f"\nA) membros (mesmo nome) em >1 path: {len(same_multi)}  -> segmentos: {dict(seg_counts)}")
    print(f"   LITERAL-ESTÁVEL (duplicação lógica real), top:")
    for m in sorted((m for m in same_multi if seg(m) == "literal_estavel"), key=lambda x: -len(same_multi[x]))[:12]:
        print(f"     {len(same_multi[m])}x  {m}")
    print(f"\n-> {OUTDIR}/saslocal_tabelas_por_path.csv\n-> {OUTDIR}/saslocal_mesmo_nome_paths_distintos.csv")


if __name__ == "__main__":
    main()

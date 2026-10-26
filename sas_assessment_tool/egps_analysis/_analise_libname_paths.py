#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Análise de tabelas SAS/Local agrupadas pelo PATH FÍSICO do libname (não pelo nome
do alias, que é mutável por EGP). Resolve %LET nos paths. Produz:
  - libname_paths_por_egp_<d>.csv      (egp, libname, path_resolvido, path_bruto)
  - tabelas_por_path_libname_<d>.csv    (path, n_tabelas, n_egps, areas)  [Análise B]
  - tabelas_mesmo_nome_paths_<d>.csv    (membro, n_paths, paths)          [Análise A]
"""
import csv, re, glob, os, collections, sys
D = "2026-06-20"; A = "docs/analises"

DB_ENGINES = {"ORACLE","SYBASE","SYBASEIQ","SQLSVR","SQLSERVR","ODBC","TERADATA","POSTGRES",
 "POSTGRESQL","BIGQUERY","BIGQUER","HADOOP","SPDE","SPDES","META","DB2","MYSQL","SAPHANA",
 "HANA","NETEZZA","GREENPLM","OLEDB","JDBC","ACCESS","EXCEL","XLSX","XLS"}
LIBNAME_RE = re.compile(r'\blibname\s+([a-z_][a-z0-9_]*)\s+(.*?);', re.IGNORECASE | re.DOTALL)
PATH_RE = re.compile(r'["\']([^"\']+)["\']')
LET_RE = re.compile(r'%let\s+([a-z0-9_]+)\s*=\s*([^;]*);', re.IGNORECASE)

def body_of(text):
    i = text.find("END_METADATA"); return text[i:] if i >= 0 else text
def build_lets(body):
    d = {}
    for m in LET_RE.finditer(body):
        d[m.group(1).upper()] = m.group(2).strip().strip('"\'').strip()
    return d
def resolve(path, lets, depth=0):
    if depth > 5 or "&" not in path: return path
    out = re.sub(r'&([a-z0-9_]+)\.?', lambda m: lets.get(m.group(1).upper(), m.group(0)), path, flags=re.I)
    return resolve(out, lets, depth+1) if out != path else out
def norm(p):
    p = resolve(p, {}, 0)  # no-op se já resolvido
    p = p.strip().replace("\\", "/")
    p = re.sub(r"/+", "/", p).rstrip("/")
    return p.casefold()

# 1) parse LIBNAME -> path por EGP
egp_lib = {}            # egp -> {LIBNAME: [paths_norm]}
raw_rows = []           # (egp, libname, path_norm, path_bruto)
n_db_skip = 0
for f in glob.glob("text_egps/*.txt"):
    egp = os.path.basename(f)[:-4]
    body = body_of(open(f, encoding="utf-8", errors="replace").read())
    lets = build_lets(body)
    libmap = {}
    for m in LIBNAME_RE.finditer(body):
        name = m.group(1).upper(); rest = m.group(2)
        toks = rest.strip().split()
        if toks and re.match(r"(clear|list|_all_)$", toks[0], re.I): continue
        if toks and toks[0].upper() in DB_ENGINES:
            globals()['n_db_skip'] = globals().get('n_db_skip',0)+1; continue
        raws = [p for p in PATH_RE.findall(rest) if ("/" in p or "\\" in p)]
        if not raws: continue
        paths = []
        for rp in raws:
            np = norm(resolve(rp, lets))
            if np and np not in paths:
                paths.append(np); raw_rows.append((egp, name, np, rp.strip()))
        if paths: libmap[name] = paths
    egp_lib[egp] = libmap

# 2) resolve table_in SAS/Local -> (path, membro)
path_members = collections.defaultdict(set)   # path -> {membro}
path_egps    = collections.defaultdict(set)
path_areas   = collections.defaultdict(set)
member_paths = collections.defaultdict(set)    # membro -> {path}
n_sas=0; n_res=0; unresolved=collections.Counter()
for row in csv.DictReader(open("06_prontidao_tabela.csv", encoding="utf-8")):
    if row["category"] != "table_in": continue
    if "SAS/LOCAL" not in (row["source_type"] or "").upper(): continue
    art = row["artifact"].strip().upper()
    if "." not in art or "&" in art: continue
    n_sas += 1
    lib, member = art.split(".", 1)
    proj = row["project"]; area = row.get("area","")
    paths = egp_lib.get(proj, {}).get(lib)
    if not paths:
        unresolved[lib] += 1; continue
    n_res += 1
    for p in paths:
        path_members[p].add(member); path_egps[p].add(proj); path_areas[p].add(area)
        member_paths[member].add(p)

# 3) saídas
with open(f"{A}/libname_paths_por_egp_{D}.csv","w",newline="",encoding="utf-8") as fh:
    w=csv.writer(fh); w.writerow(["egp","libname","path_resolvido","path_bruto"])
    for r in sorted(set(raw_rows)): w.writerow(r)

with open(f"{A}/tabelas_por_path_libname_{D}.csv","w",newline="",encoding="utf-8") as fh:
    w=csv.writer(fh); w.writerow(["path","n_tabelas","n_egps","areas"])
    for p,mem in sorted(path_members.items(), key=lambda x:-len(x[1])):
        w.writerow([p,len(mem),len(path_egps[p]),";".join(sorted(path_areas[p]))])

dups={m:ps for m,ps in member_paths.items() if len(ps)>1}
with open(f"{A}/tabelas_mesmo_nome_paths_{D}.csv","w",newline="",encoding="utf-8") as fh:
    w=csv.writer(fh); w.writerow(["membro","n_paths_distintos","paths"])
    for m,ps in sorted(dups.items(), key=lambda x:-len(x[1])):
        w.writerow([m,len(ps),";".join(sorted(ps))])

# near-equal: mesmo stem normalizado (tira sufixo de versao/data/numero) em paths distintos
def stem(m): return re.sub(r'[_]?(v?\d{1,8}|final|new|copia|bkp|old|temp|aux)$','',m,flags=re.I).rstrip("_")
stem_map=collections.defaultdict(lambda:collections.defaultdict(set))  # stem -> {membro: paths}
for m,ps in member_paths.items():
    stem_map[stem(m)][m]|=ps
near=[(s,d) for s,d in stem_map.items() if len(d)>1 and len({p for ps in d.values() for p in ps})>1]

print("== PARSE ==")
print(f"  EGPs com libname-path: {sum(1 for v in egp_lib.values() if v)}/{len(egp_lib)}")
print(f"  libname-path statements (linhas): {len(set(raw_rows))} | engines BD pulados: {globals().get('n_db_skip',0)}")
print(f"  paths físicos distintos: {len(path_members)}")
print("== RESOLUÇÃO table_in SAS/Local ==")
print(f"  table_in SAS/Local: {n_sas} | resolvidos a path: {n_res} ({100*n_res//max(n_sas,1)}%) | libnames não resolvidos (distintos): {len(unresolved)}")
print(f"  top libnames não resolvidos: {unresolved.most_common(8)}")
print("== [B] tabelas por path (top 15) ==")
for p,mem in sorted(path_members.items(), key=lambda x:-len(x[1]))[:15]:
    print(f"  {len(mem):4}  {p}")
print(f"== [A] membros (mesmo nome) em >1 path distinto: {len(dups)} ==")
for m,ps in sorted(dups.items(), key=lambda x:-len(x[1]))[:12]:
    print(f"  {len(ps)} paths · {m}")
print(f"== [A-near] stems quase-iguais em paths distintos: {len(near)} ==")

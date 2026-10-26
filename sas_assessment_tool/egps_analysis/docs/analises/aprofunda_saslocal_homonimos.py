#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aprofundamento dos membros SAS/Local homônimos (mesmo nome em >1 path físico).

Distingue REPLICAÇÃO (consolidar) de HOMÔNIMO DISTINTO (não mesclar) usando o sinal
produtor↔consumidor: resolve table_in E table_out a paths físicos e cruza.

Classificação por membro (literal-estável, em >1 path):
  - fonte_unica_replicada : produzido em 1 path, lido/presente em outros  -> CONSOLIDAR (fonte única)
  - externa_replicada     : produzido em 0 paths do corpus, presente em N -> CONSOLIDAR (ingerir 1x)
  - multi_produtor        : produzido em >=2 paths (cada EGP gera a sua)  -> DISTINTAS (não mesclar)
Mais sinal: nº de "domain roots" (2 primeiros segmentos do path) — mesma raiz reforça
mesma-tabela; raízes diferentes reforçam distintas.
"""
import csv, glob, os, collections
import analise_libname_paths as alp

ROOT, TXT_DIR, REP06, OUTDIR = alp.ROOT, alp.TXT_DIR, alp.REP06, alp.OUTDIR


def build_stem_lib():
    stem_lib = {}
    for fp in glob.glob(os.path.join(TXT_DIR, "*.txt")):
        stem = os.path.basename(fp)[:-4]
        code = alp.body_text(open(fp, encoding="utf-8", errors="replace").read())
        stem_lib[stem] = alp.parse_libnames(code, alp.let_dict(code))
    children = collections.defaultdict(list)
    tail_index = collections.defaultdict(list)
    for s in stem_lib:
        if "__" in s:
            children[s.rsplit("__", 1)[0]].append(s)
        tail_index[s.split("__", 1)[-1]].append(s)
    cache = {}
    def libs_for_project(P):
        if P in cache:
            return cache[P]
        merged = collections.defaultdict(set)
        cands = set([P]) if P in stem_lib else set()
        cands.update(children.get(P, []))
        if "__" in P:
            cands.update(tail_index.get(P.split("__", 1)[1], []))
        for s in cands:
            for lib, paths in stem_lib.get(s, {}).items():
                merged[lib].update(paths)
        cache[P] = merged
        return merged
    return libs_for_project


def domain_root(p):
    segs = [s for s in p.split("/") if s]
    return "/" + "/".join(segs[:2]) if segs else p


def main():
    libs_for_project = build_stem_lib()
    # (path, member) -> conjuntos de io
    prod = collections.defaultdict(set)   # member -> set(paths) onde é table_out
    cons = collections.defaultdict(set)   # member -> set(paths) onde é table_in
    member_all_paths = collections.defaultdict(set)
    for r in csv.DictReader(open(REP06, encoding="utf-8")):
        cat = r["category"]
        if cat not in ("table_in", "table_out"):
            continue
        if cat == "table_in" and "SAS/LOCAL" not in (r["source_type"] or "").upper():
            continue
        art = (r["artifact"] or "").strip().upper()
        if "." not in art:
            continue
        lib, member = art.split(".", 1)
        if alp.is_not_real_table(lib, member, r["source_type"]):
            continue
        paths = libs_for_project(r["project"]).get(lib, set())
        for p in paths:
            member_all_paths[member].add(p)
            (prod if cat == "table_out" else cons)[member].add(p)

    def is_literal_stable(m):
        return "{" not in m and "&" not in m and not alp.DATED_RE.search(m)

    targets = {m for m, ps in member_all_paths.items() if len(ps) > 1 and is_literal_stable(m)}

    rows = []
    cls_count = collections.Counter()
    for m in targets:
        pp, cp = prod.get(m, set()), cons.get(m, set())
        allp = member_all_paths[m]
        roots = {domain_root(p) for p in allp}
        if len(pp) >= 2:
            cls = "multi_produtor (DISTINTAS)"
        elif len(pp) == 1:
            cls = "fonte_unica_replicada (CONSOLIDAR)"
        else:
            cls = "externa_replicada (CONSOLIDAR)"
        # raízes distintas reforçam "distintas"
        if len(roots) > 1 and len(pp) >= 2:
            cls += " · cross-root"
        cls_count[cls.split(" ")[0]] += 1
        rows.append((m, len(allp), len(pp), len(cp), len(roots), cls, " | ".join(sorted(allp))))

    rows.sort(key=lambda x: (x[5], -x[1]))
    out = os.path.join(OUTDIR, "saslocal_homonimos_classificados.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["membro", "n_paths", "n_paths_produtor", "n_paths_consumidor", "n_domain_roots", "classificacao", "paths"])
        w.writerows(rows)

    print(f"membros literal-estável em >1 path analisados: {len(targets)}")
    print(f"classificação: {dict(cls_count)}")
    for cls in ("fonte_unica_replicada", "externa_replicada", "multi_produtor"):
        sub = [r for r in rows if r[5].startswith(cls)]
        print(f"\n== {cls} ({len(sub)}) — top por nº de paths ==")
        for r in sorted(sub, key=lambda x: -x[1])[:10]:
            print(f"   {r[0]:34} paths={r[1]} prod={r[2]} cons={r[3]} roots={r[4]}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()

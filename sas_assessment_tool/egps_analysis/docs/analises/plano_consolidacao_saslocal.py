#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plano de consolidação dos membros SAS/Local replicados (externa_replicada +
fonte_unica_replicada). Para cada grupo: fonte canônica (path produtor, quando há),
nº de cópias/paths a aposentar e raio de impacto (EGPs consumidores distintos).
"""
import csv, os, collections
import analise_libname_paths as alp
from aprofunda_saslocal_homonimos import build_stem_lib

REP06, OUTDIR = alp.REP06, alp.OUTDIR


def main():
    libs_for_project = build_stem_lib()
    prod_paths = collections.defaultdict(set)
    cons_paths = collections.defaultdict(set)
    cons_egps = collections.defaultdict(set)
    all_paths = collections.defaultdict(set)
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
        for p in libs_for_project(r["project"]).get(lib, set()):
            all_paths[member].add(p)
            if cat == "table_out":
                prod_paths[member].add(p)
            else:
                cons_paths[member].add(p)
                cons_egps[member].add(r["project"])

    def literal_stable(m):
        return "{" not in m and "&" not in m and not alp.DATED_RE.search(m)

    rows = []
    for m, paths in all_paths.items():
        if len(paths) < 2 or not literal_stable(m):
            continue
        pp = prod_paths.get(m, set())
        if len(pp) >= 2:
            continue  # multi_produtor = distintas, fora do plano
        classe = "fonte_unica_replicada" if len(pp) == 1 else "externa_replicada"
        fonte = sorted(pp)[0] if pp else "(externa — ingerir 1x)"
        rows.append({
            "membro": m, "classe": classe,
            "fonte_canonica": fonte,
            "n_paths": len(paths),
            "copias_a_aposentar": len(paths) - 1,
            "egps_consumidores": len(cons_egps.get(m, set())),
            "paths": " | ".join(sorted(paths)),
        })

    rows.sort(key=lambda r: (-r["egps_consumidores"], -r["n_paths"]))
    out = os.path.join(OUTDIR, "plano_consolidacao_saslocal.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["membro", "classe", "fonte_canonica", "n_paths",
                                          "copias_a_aposentar", "egps_consumidores", "paths"])
        w.writeheader(); w.writerows(rows)

    tot_copias = sum(r["copias_a_aposentar"] for r in rows)
    tot_egps = sum(r["egps_consumidores"] for r in rows)
    print(f"grupos a consolidar: {len(rows)}  ({sum(1 for r in rows if r['classe']=='externa_replicada')} externa + {sum(1 for r in rows if r['classe']=='fonte_unica_replicada')} fonte_unica)")
    print(f"cópias/paths redundantes a aposentar (sum n_paths-1): {tot_copias}")
    print(f"raio de impacto (sum EGPs consumidores): {tot_egps}")
    print("\ntop 15 por raio de impacto (EGPs consumidores):")
    print(f"  {'membro':32} {'classe':22} {'paths':>5} {'EGPs':>5}  fonte")
    for r in rows[:15]:
        print(f"  {r['membro'][:32]:32} {r['classe']:22} {r['n_paths']:>5} {r['egps_consumidores']:>5}  {r['fonte_canonica'][:42]}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()

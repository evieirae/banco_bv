#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refaz a linhagem usando (PATH FISICO, MEMBRO) para SAS/Local. v2 (pós-verificação
adversarial — corrige os P0):

  1. NÃO remove aresta por fallback assimétrico. Uma aresta de nome só é "false-merge"
     quando o libref resolve a path nos DOIS lados (produtor e consumidor) E os paths
     são disjuntos. Lado não-resolvido => 'desconhecido' => preserva a aresta.
  2. Arestas RECUPERADAS por path marcam o fan-out (n_produtores do par (path,membro)):
     limpa (1 produtor) vs ambígua (hub multi-produtor).
  3. Expõe os HUBS compartilhados: (path,membro) escritos por >1 EGP — o achado
     estrutural (ex.: TBPRODUCAO @ /projetos/misv/data/bases, 8 writers).
"""
import csv, os, collections
import analise_libname_paths as alp
from aprofunda_saslocal_homonimos import build_stem_lib

REP06, OUTDIR = alp.REP06, alp.OUTDIR


def main():
    libs_for_project = build_stem_lib()
    outs = collections.defaultdict(list)
    ins = collections.defaultdict(list)
    for r in csv.DictReader(open(REP06, encoding="utf-8")):
        cat = r["category"]
        if cat not in ("table_in", "table_out"):
            continue
        art = (r["artifact"] or "").strip().upper()
        if "." not in art:
            continue
        lib, member = art.split(".", 1)
        if alp.is_not_real_table(lib, member, r["source_type"]):
            continue
        (outs if cat == "table_out" else ins)[r["project"]].append((lib, member))

    def paths_of(proj, lib):
        return libs_for_project(proj).get(lib, set())

    # ---- baseline: arestas por NOME (lib.member) ----
    name_gen = collections.defaultdict(set)
    name_out = collections.defaultdict(set)
    for proj, lst in outs.items():
        for lib, member in lst:
            k = f"{lib}.{member}"
            name_gen[k].add(proj); name_out[proj].add(k)
    E_name = set()
    name_edge_libs = collections.defaultdict(set)   # (cons,prod) -> {(lib,member)}
    for proj, lst in ins.items():
        for lib, member in lst:
            k = f"{lib}.{member}"
            if k in name_out.get(proj, ()):
                continue
            for prod in name_gen.get(k, ()):
                if prod != proj:
                    E_name.add((proj, prod)); name_edge_libs[(proj, prod)].add((lib, member))

    # ---- arestas por PATH (apenas outputs/inputs RESOLVIDOS) ----
    path_gen = collections.defaultdict(set)         # (path,member) -> {produtores}
    path_out = collections.defaultdict(set)
    for proj, lst in outs.items():
        for lib, member in lst:
            for p in paths_of(proj, lib):
                path_gen[(p, member)].add(proj); path_out[proj].add((p, member))
    E_path = set()
    path_edge_keys = collections.defaultdict(set)
    for proj, lst in ins.items():
        for lib, member in lst:
            for p in paths_of(proj, lib):
                key = (p, member)
                if key in path_out.get(proj, ()):
                    continue
                for prod in path_gen.get(key, ()):
                    if prod != proj:
                        E_path.add((proj, prod)); path_edge_keys[(proj, prod)].add(key)

    # ---- RECUPERADAS: em path, não em nome ----
    recuperadas = E_path - E_name
    rec_clean = rec_amb = 0
    rec_rows = []
    for (c, p) in recuperadas:
        keys = path_edge_keys[(c, p)]
        nprod = max(len(path_gen[k]) for k in keys)
        clean = nprod == 1
        rec_clean += clean; rec_amb += (not clean)
        rec_rows.append((c, p, " | ".join(sorted({m for _, m in keys})[:5]), nprod, "limpa" if clean else "hub_multiprodutor"))

    # ---- FALSAS GENUINAS: aresta de nome onde TODOS os libs-via resolvem nos 2 lados a paths DISJUNTOS ----
    genuine_false = []
    for (c, p) in E_name:
        libs = name_edge_libs[(c, p)]
        verdicts = []
        for lib, member in libs:
            pc, pp = paths_of(c, lib), paths_of(p, lib)
            if pc and pp:
                verdicts.append("disjoint" if pc.isdisjoint(pp) else "same")
            else:
                verdicts.append("unknown")
        # só falsa se há prova (algum disjoint) e NENHUM 'same' nem 'unknown' que sustente
        if verdicts and all(v == "disjoint" for v in verdicts):
            genuine_false.append((c, p, " | ".join(f"{l}.{m}" for l, m in sorted(libs))[:80]))

    # ---- HUBS compartilhados (path,membro) com >1 produtor ----
    hubs = sorted(((k, len(v)) for k, v in path_gen.items() if len(v) > 1), key=lambda x: -x[1])

    # CSVs
    with open(os.path.join(OUTDIR, "linhagem_arestas_recuperadas.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["projeto_alvo", "depende_do", "via_membros", "n_produtores_no_path", "tipo"])
        for row in sorted(rec_rows, key=lambda x: -x[3]):
            w.writerow(row)
    with open(os.path.join(OUTDIR, "linhagem_falsas_genuinas.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["projeto_alvo", "depende_do", "via"]); w.writerows(sorted(genuine_false))
    with open(os.path.join(OUTDIR, "linhagem_hubs_multiprodutor.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["path_fisico", "membro", "n_produtores"])
        for (path, member), n in hubs:
            w.writerow([path, member, n])

    print("LINHAGEM PATH-AWARE (v2, corrigida)")
    print(f"  RECUPERADAS (path acha, nome não): {len(recuperadas)}")
    print(f"     - LIMPAS (1 produtor no path)  : {rec_clean}   <- dependências reais antes perdidas por aliasing")
    print(f"     - via HUB multi-produtor       : {rec_amb}   <- ligações plausíveis mas produtor ambíguo")
    print(f"  FALSAS GENUÍNAS (ambos resolvem, paths disjuntos): {len(genuine_false)}  (o '490' anterior era bug de fallback)")
    print(f"\n  HUBS compartilhados (path,membro) escritos por >1 EGP: {len(hubs)}")
    for (path, member), n in hubs[:10]:
        print(f"     {n:2} produtores  {member:24} @ {path}")
    print(f"\n  Correção líquida da linhagem: +{rec_clean} limpas, +{rec_amb} ambíguas(marcar), -{len(genuine_false)} falsas")
    print(f"\n-> {OUTDIR}/linhagem_arestas_recuperadas.csv (com n_produtores)")
    print(f"-> {OUTDIR}/linhagem_falsas_genuinas.csv")
    print(f"-> {OUTDIR}/linhagem_hubs_multiprodutor.csv")


if __name__ == "__main__":
    main()

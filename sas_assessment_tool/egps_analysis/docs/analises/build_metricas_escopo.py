#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recomputa TODAS as métricas de escopo do doc metricas_*.md a partir dos CSVs
locais ATUAIS, reutilizando o `build()` do publish (mesmo grão do app) e a
mesma lógica de dependência transitiva do build_inputs_indicium_csv.

Imprime os itens 1–7, os totais disjoint, e as duas variantes
(a: deps diretas 1-hop · b: grão Resumo c/ libname_in). É a fonte única de
verdade para reconciliar o doc quando os relatórios 01–06 são atualizados.

Uso: python egps_analysis/docs/analises/build_metricas_escopo.py
"""
import collections
import os
import sys

ANALISES = os.path.dirname(os.path.abspath(__file__))
EGPS_ROOT = os.path.dirname(os.path.dirname(ANALISES))
sys.path.insert(0, EGPS_ROOT)
import publish_to_databricks as pub  # noqa: E402
from build_inputs_indicium_csv import transitive_dep_egps  # noqa: E402

ANALISADO = {"exato", "variante", "confirmado_area", "ingerido_extraido"}


def direct_dep_egps(edges_rows, indi):
    dep_of = collections.defaultdict(set)
    for e in edges_rows:
        a, d = e["projeto_alvo"], e["depende_do"]
        if a and d and a != d:
            dep_of[a].add(d)
    direct = set()
    for a in indi:
        direct |= dep_of.get(a, set())
    return direct - indi


def scope_counts(rows, chave_to_projs, indi, deps):
    """(inputs Indicium, a_ingerir; inputs deps disjoint, a_ingerir)."""
    indi_n = indi_ing = dep_n = dep_ing = 0
    for r in rows:
        aing = r["modernizada_auto"] == "A ingerir"
        if r["escopo_indi"]:
            indi_n += 1
            indi_ing += aing
        else:
            if chave_to_projs.get(r["chave_canonica"], set()) & deps:
                dep_n += 1
                dep_ing += aing
    return indi_n, indi_ing, dep_n, dep_ing


def main():
    data = pub.build()
    indi = pub.load_indi_projects()

    # funil de EGPs (do indi_231): total / enviados / analisados
    full = data["indicium"]
    total_dor1 = len(full)
    enviados = sum(1 for r in full if r["status_extracao"] != "faltante")
    analisados = sum(1 for r in full if r["status_extracao"] in ANALISADO)

    dep_trans = transitive_dep_egps(data["edges"], indi)
    dep_direct = direct_dep_egps(data["edges"], indi)

    # grão monitor (IN_CATS)
    mon_c2p = collections.defaultdict(set)
    for er in data["egp_inputs"]:
        mon_c2p[er["chave_canonica"]].add(er["projeto"])
    # grão resumo (RES_CATS, inclui libname_in)
    res_c2p = collections.defaultdict(set)
    for rp in data["resumo_proj"]:
        res_c2p[rp["chave_canonica"]].add(rp["projeto"])

    i3, i4, i6_t, i7_t = scope_counts(data["inputs"], mon_c2p, indi, dep_trans)
    _, _, i6_d, i7_d = scope_counts(data["inputs"], mon_c2p, indi, dep_direct)
    r3, r4, r6_t, r7_t = scope_counts(data["resumo"], res_c2p, indi, dep_trans)

    print(f"== EGPs == total DOR1={total_dor1} · enviados={enviados} · analisados={analisados}")
    print(f"== deps == transitivo(não-Indi)={len(dep_trans)} · diretas 1-hop={len(dep_direct)}")
    print("\n== MONITOR (table_in+file_in+script_in, .sas deduped) — transitivo ==")
    print(f"  3 inputs Indicium .............. {i3}")
    print(f"  4 inputs Indicium a ingerir .... {i4}")
    print(f"  5 deps (transitivo) ............ {len(dep_trans)}")
    print(f"  6 inputs deps (disjoint) ....... {i6_t}")
    print(f"  7 inputs deps a ingerir ........ {i7_t}")
    print(f"  TOT EGPs={enviados + len(dep_trans)} · Inputs={i3 + i6_t} · "
          f"não-mod={i4 + i7_t}")
    print("\n== Variante a: deps DIRETAS (1-hop) ==")
    print(f"  5 deps diretas ................. {len(dep_direct)}")
    print(f"  6 inputs deps (disjoint) ....... {i6_d}")
    print(f"  7 inputs deps a ingerir ........ {i7_d}")
    print(f"  TOT EGPs={enviados + len(dep_direct)} · Inputs={i3 + i6_d} · "
          f"não-mod={i4 + i7_d}")
    print("\n== Variante b: grão RESUMO (inclui libname_in) — transitivo ==")
    print(f"  3 inputs Indicium .............. {r3}")
    print(f"  4 inputs Indicium a ingerir .... {r4}")
    print(f"  5 deps (transitivo) ............ {len(dep_trans)}")
    print(f"  6 inputs deps (disjoint) ....... {r6_t}")
    print(f"  7 inputs deps a ingerir ........ {r7_t}")
    print(f"  TOT EGPs={enviados + len(dep_trans)} · Inputs={r3 + r6_t} · "
          f"não-mod={r4 + r7_t}")


if __name__ == "__main__":
    main()

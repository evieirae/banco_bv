#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera o CSV com TODOS os inputs necessários para o escopo Indicium.

Dois escopos numa única tabela (coluna `escopo`):
  - "Indicium"    — input lido por algum EGP do escopo Indicium (DOR1).
  - "Dependência" — input lido APENAS por EGP não-Indicium que é dependência
                    (transitiva) de algum EGP Indicium. Disjoint com "Indicium":
                    se um input é lido por um Indicium E por uma dependência,
                    ele aparece uma única vez como "Indicium" (sem dupla contagem).

Reutiliza a MESMA lógica de agregação do app (grão `sas_inputs_monitor`):
importa `publish_to_databricks.build()` — inputs distintos com dedup `.sas`,
`is_noise_table`, `MODERN_MARKERS` — sobre os CSVs locais. As dependências
transitivas saem das arestas `03_matriz_dependencias.csv` (via `build()["edges"]`).

Contagens atuais (cruzam com docs/analises/metricas_2026-06-16.md, reconciliado):
  Indicium = 3354 · Dependência (disjoint) = 965 · Total = 4319.

Uso (de qualquer cwd):
  python egps_analysis/docs/analises/build_inputs_indicium_csv.py
  python egps_analysis/docs/analises/build_inputs_indicium_csv.py --scope indicium
"""
import argparse
import collections
import csv
import os
import sys

# importa publish_to_databricks (raiz do egps_analysis/)
ANALISES = os.path.dirname(os.path.abspath(__file__))
EGPS_ROOT = os.path.dirname(os.path.dirname(ANALISES))
sys.path.insert(0, EGPS_ROOT)
import publish_to_databricks as pub  # noqa: E402

OUT_DEFAULT = os.path.join(ANALISES, "inputs_indicium_2026-06-18.csv")
# Contagens da base local ATUAL (dados do commit 5906104). O doc
# metricas_2026-06-16.md reporta 3353/882/71 — está defasado: suas métricas de
# dependência saíram da linhagem do Databricks (stale), não do 03 local atual.
EXPECTED_INDI = 3354
EXPECTED_DEP = 965


def transitive_dep_egps(edges_rows, indi):
    """EGPs não-Indicium alcançáveis (transitivamente) a partir do escopo Indicium,
    seguindo as arestas alvo -> depende_do."""
    dep_of = collections.defaultdict(set)
    for e in edges_rows:
        a, d = e["projeto_alvo"], e["depende_do"]
        if a and d and a != d:
            dep_of[a].add(d)
    trans, stack = set(), [d for a in indi for d in dep_of.get(a, ())]
    while stack:
        p = stack.pop()
        if p in trans:
            continue
        trans.add(p)
        stack.extend(dep_of.get(p, ()))
    return trans - indi  # só as dependências fora do escopo Indicium


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=("both", "indicium"), default="both",
                    help="'both' (default): Indicium + dependências. 'indicium': só Indicium.")
    ap.add_argument("-o", "--out", default=OUT_DEFAULT)
    args = ap.parse_args()

    data = pub.build()
    indi = pub.load_indi_projects()
    inputs_rows = data["inputs"]

    # chave_canonica -> set(projetos que leem o input) — do grão projeto×input.
    chave_to_projs = collections.defaultdict(set)
    for er in data["egp_inputs"]:
        chave_to_projs[er["chave_canonica"]].add(er["projeto"])

    dep_egps = transitive_dep_egps(data["edges"], indi)

    rows = []
    for r in inputs_rows:
        projs = chave_to_projs.get(r["chave_canonica"], set())
        if r["escopo_indi"]:
            escopo = "Indicium"
            qtd_no_escopo = len(projs & indi)
        else:
            dep_projs = projs & dep_egps
            if not dep_projs:
                continue  # nem Indicium, nem dependência do escopo
            escopo = "Dependência"
            qtd_no_escopo = len(dep_projs)
        rows.append({
            "escopo": escopo,
            "categoria": r["categoria"],
            # origem do dado: BigQuery / Transacional (banco transacional:
            # Postgres/Sybase/SQLServer/IQ/...) / SAS/Local (libname ou dataset
            # SAS) / Arquivo. Mesma função origem_bucket do app (aba Resumo).
            "origem": pub.origem_bucket(set(r["source_types"].split(" | ")), r["categoria"]),
            "artifact": r["artifact"],
            "chave_canonica": r["chave_canonica"],
            "qtd_projetos_no_escopo": qtd_no_escopo,
            "areas": r["areas"],
            "source_types": r["source_types"],
            "modernizada_auto": r["modernizada_auto"],
        })

    n_indi = sum(1 for r in rows if r["escopo"] == "Indicium")
    n_dep = sum(1 for r in rows if r["escopo"] == "Dependência")
    print(f"escopo Indicium : {n_indi}  (esperado {EXPECTED_INDI}) "
          f"{'OK' if n_indi == EXPECTED_INDI else 'DIVERGE'}")
    print(f"escopo Dependência: {n_dep}  (esperado {EXPECTED_DEP}) "
          f"{'OK' if n_dep == EXPECTED_DEP else 'DIVERGE'}")
    print(f"EGPs dependência (transitivo, não-Indicium): {len(dep_egps)}  (esperado 71)")
    print(f"total (both): {len(rows)}  (esperado {EXPECTED_INDI + EXPECTED_DEP})")

    if args.scope == "indicium":
        rows = [r for r in rows if r["escopo"] == "Indicium"]

    # ordenação: A ingerir primeiro -> Indicium primeiro -> categoria -> artifact
    rows.sort(key=lambda r: (
        0 if r["modernizada_auto"] == "A ingerir" else 1,
        0 if r["escopo"] == "Indicium" else 1,
        r["categoria"],
        r["artifact"].upper(),
    ))

    cols = ["escopo", "categoria", "origem", "artifact", "chave_canonica",
            "qtd_projetos_no_escopo", "areas", "source_types", "modernizada_auto"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        wri = csv.DictWriter(f, fieldnames=cols)
        wri.writeheader()
        wri.writerows(rows)
    print(f"\nescrito: {args.out}  ({len(rows)} linhas, escopo={args.scope})")


if __name__ == "__main__":
    main()

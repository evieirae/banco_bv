#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera a visão CONSOLIDADA deduplicada por área dos inputs *a ingerir* do escopo
Indicium + dependentes transitivos, lendo o estado AO VIVO do Databricks (tabela
`bv_dev_db.monitoramento_sas.sas_inputs_monitor`, status EFETIVO que respeita
`status_humano`) — diferente dos demais build_*.py, que computam da base local.

Cada input distinto (chave_canonica) é atribuído a UMA única área (voto pelos EGPs
leitores, priorizando leitores do escopo; tie-break alfabético), de modo que a soma
das áreas == total dedup, sem dupla contagem.

Saídas (em docs/analises/):
  - inputs_a_ingerir_por_area_<data>.csv      (detalhe por input, com lista de projetos)
  - inputs_a_ingerir_matriz_area_origem_<data>.csv (matriz área × origem)

Conexão: databricks-sdk, perfil/warehouse do app de monitoramento.
  egps_analysis/venv/bin/python docs/analises/build_inputs_a_ingerir_por_area.py [AAAA-MM-DD]
"""
import collections
import csv
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format

WID = os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID", "5922c26f81f1bbdd")
PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "bv")
FQ = "bv_dev_db.monitoramento_sas"
T_IN, T_ED, T_ND = f"{FQ}.sas_inputs_monitor", f"{FQ}.sas_lineage_edges", f"{FQ}.sas_lineage_nodes"
T_EGP, T_RESP = f"{FQ}.sas_egp_inputs", f"{FQ}.sas_resumo_proj"
OUTDIR = os.path.dirname(os.path.abspath(__file__))
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-06-19"
W = WorkspaceClient(profile=PROFILE)


def q(sql):
    r = W.statement_execution.execute_statement(
        statement=sql, warehouse_id=WID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = W.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "?")
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


# status EFETIVO == app/backend/main.py:_eff_status/_modern/_aingerir
SH, AUTO = "status_humano", "modernizada_auto"
NORM = (f"CASE {SH} WHEN 'Disponível' THEN 'Modernizado' WHEN 'Sanitizada' THEN 'Sanitizado' "
        f"WHEN 'Descartada' THEN 'Sanitizado' WHEN 'Descartado' THEN 'Sanitizado' "
        f"WHEN 'Em análise' THEN 'Recebido' WHEN 'A ingerir' THEN 'A receber' "
        f"WHEN 'Não recebido' THEN 'A receber' WHEN 'Priorizado' THEN 'Recebido' ELSE {SH} END")
AUTO_DEF = f"CASE {AUTO} WHEN 'Disponível' THEN 'Modernizado' WHEN 'A ingerir' THEN 'A receber' ELSE 'Recebido' END"
EFF = f"coalesce(nullif({NORM}, ''), {AUTO_DEF})"
AING = f"(NOT ({EFF} IN ('Modernizado','Sanitizado')))"


def b(v):
    return str(v).lower() == "true"


# ---- carrega 1x ----
nodes = q(f"SELECT projeto, area, escopo_indi FROM {T_ND}")
edges = q(f"SELECT projeto_alvo, depende_do FROM {T_ED}")
egp = q(f"SELECT DISTINCT projeto, chave_canonica FROM {T_EGP}")
resp = q(f"SELECT DISTINCT projeto, chave_canonica FROM {T_RESP}")
mon = q(f"SELECT chave_canonica, origem, categoria, areas, escopo_indi, {AING} AS aing FROM {T_IN}")

node_area = {n["projeto"]: (n["area"] or "(sem área)") for n in nodes}
scope = {n["projeto"] for n in nodes if b(n["escopo_indi"])}
scope_areas = {node_area[p] for p in scope}

dep_of = collections.defaultdict(set)
for e in edges:
    a, d = e["projeto_alvo"], e["depende_do"]
    if a and d and a != d:
        dep_of[a].add(d)
trans, stack = set(), [d for a in scope for d in dep_of.get(a, set())]
while stack:
    p = stack.pop()
    if p in trans:
        continue
    trans.add(p)
    stack.extend(dep_of.get(p, set()))
deps = trans - scope
universe = scope | deps

# chave -> EGPs do universo que leem (egp_inputs define a contagem; resumo_proj completa a lista)
readers_egp = collections.defaultdict(set)
for r in egp:
    if r["projeto"] in universe:
        readers_egp[r["chave_canonica"]].add(r["projeto"])
readers_full = collections.defaultdict(set)
for r in resp:
    if r["projeto"] in universe:
        readers_full[r["chave_canonica"]].add(r["projeto"])

mon_by_ch = {r["chave_canonica"]: r for r in mon}
ORIG = ["SAS/Local (externo)", "SAS/Local (dependência)", "Arquivo", "Transacional", "Script", "BigQuery", "(sem origem)"]


def vote_area(readers):
    sc = [p for p in readers if p in scope]
    cnt = collections.Counter(node_area.get(p, "(sem área)") for p in (sc or list(readers)))
    top = max(cnt.values())
    return sorted(a for a, c in cnt.items() if c == top)[0]


def fallback_area(areas_field):
    aset = [a.strip() for a in (areas_field or "").split("|") if a.strip()]
    insc = sorted(a for a in aset if a in scope_areas)
    return insc[0] if insc else (sorted(aset)[0] if aset else "(sem área)")


matrix = collections.defaultdict(collections.Counter)
matrix_tab = collections.defaultdict(collections.Counter)
detail, seen = [], set()


def add(ch, rec, area, readers):
    seen.add(ch)
    o = rec["origem"] or "(sem origem)"
    matrix[area][o] += 1
    if rec["categoria"] == "tabela":
        matrix_tab[area][o] += 1
    projs = sorted(readers or readers_full.get(ch, set()))
    detail.append({
        "area_principal": area, "origem": o, "categoria": rec["categoria"],
        "chave_canonica": ch, "qtd_projetos": len(projs),
        "escopo_indi": bool(set(projs) & scope) or b(rec["escopo_indi"]),
        "projetos": " | ".join(projs),
    })


# 1) inputs a ingerir com leitor no grão egp_inputs (define os 3.5k)
for ch, readers in readers_egp.items():
    rec = mon_by_ch.get(ch)
    if rec and b(rec["aing"]):
        add(ch, rec, vote_area(readers), readers)
# 2) fallback: chaves do escopo a ingerir sem leitor em egp_inputs (ex.: libname)
for rec in mon:
    ch = rec["chave_canonica"]
    if ch not in seen and b(rec["aing"]) and b(rec["escopo_indi"]):
        add(ch, rec, fallback_area(rec["areas"]), readers_full.get(ch, set()))

areas = sorted(matrix, key=lambda a: -sum(matrix[a].values()))
origens = [o for o in ORIG if any(matrix[a].get(o) for a in areas)]
grand = sum(sum(matrix[a].values()) for a in areas)

# ---- CSV detalhe (com projetos) ----
detail.sort(key=lambda d: (d["area_principal"], d["origem"], d["chave_canonica"]))
p1 = os.path.join(OUTDIR, f"inputs_a_ingerir_por_area_{DATE}.csv")
with open(p1, "w", newline="", encoding="utf-8") as f:
    wri = csv.DictWriter(f, fieldnames=["area_principal", "origem", "categoria", "chave_canonica",
                                        "qtd_projetos", "escopo_indi", "projetos"])
    wri.writeheader()
    wri.writerows(detail)

# ---- CSV matriz ----
p2 = os.path.join(OUTDIR, f"inputs_a_ingerir_matriz_area_origem_{DATE}.csv")
with open(p2, "w", newline="", encoding="utf-8") as f:
    wri = csv.writer(f)
    wri.writerow(["area_principal"] + origens + ["total", "dos_quais_tabelas"])
    for a in areas:
        wri.writerow([a] + [matrix[a].get(o, 0) for o in origens]
                     + [sum(matrix[a].values()), sum(matrix_tab[a].values())])
    wri.writerow(["TOTAL"] + [sum(matrix[a].get(o, 0) for a in areas) for o in origens]
                 + [grand, sum(sum(matrix_tab[a].values()) for a in areas)])

# ---- números globais (para o doc) ----
esc = [r for r in mon if b(r["escopo_indi"])]
esc_aing = sum(1 for r in esc if b(r["aing"]))
esc_ch = {r["chave_canonica"] for r in esc}
all_aing = {r["chave_canonica"] for r in mon if b(r["aing"])}
deps_ch = {ch for ch, rd in readers_egp.items()} & {r["chave_canonica"] for r in resp if r["projeto"] in deps}
deps_only = {ch for ch in readers_egp if (readers_egp[ch] & deps)} - esc_ch
deps_only_aing = len(deps_only & all_aing)
print(f"EGPs: escopo={len(scope)} + deps={len(deps)} = {len(universe)}")
print(f"escopo: {len(esc)} distintos | {esc_aing} a ingerir")
print(f"deps (disjunto): {len(deps_only)} distintos | {deps_only_aing} a ingerir")
print(f"TOTAL a ingerir (dedup) = {grand}  (escopo {esc_aing} + deps {deps_only_aing})")
print(f"\n{'Área':40}" + "".join(f"{o[:18]:>20}" for o in origens) + f"{'TOTAL':>8}")
for a in areas:
    print(f"{a:40}" + "".join(f"{matrix[a].get(o,0):>20}" for o in origens) + f"{sum(matrix[a].values()):>8}")
print(f"{'TOTAL':40}" + "".join(f"{sum(matrix[a].get(o,0) for a in areas):>20}" for o in origens) + f"{grand:>8}")
print(f"\nescrito: {p1} ({len(detail)} linhas) e {p2}")

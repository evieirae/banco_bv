#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ad-hoc: mede o impacto do fix .sas7bdat (commits 9040ddfa/0ff139fe/24c62c6d/7b385cb4,
branch fix/exporttask-files-not-outputs) sobre ESCOPO (indi / indi_deps / base) e
DEPENDÊNCIAS (grafo de linhagem).

Identifica a população afetada DIRETO no 06_prontidao_tabela.csv (fonte primária, já
regenerada pós-fix pelo commit 7b385cb4) — convertidos = source_type ==
'SAS/Local (.sas7bdat sob LIBNAME)'; remanescentes = category=='file_in' + artifact
.sas7bdat + source_type vazio (guards conservadores). Depois cruza por artifact com
data['inputs'] do build() LOCAL de publish_to_databricks.py (pós-fix, não publicado)
para pegar escopo_indi/modernizada_auto, e reconstrói o frontier indi_deps do mesmo
jeito que recompute_area_principal() faz de verdade (leitura read-only do banco só
para no_expand/resolvidas, que não mudam com este fix).
"""
import collections
import csv
import sys
import time

sys.path.insert(0, ".")
import publish_to_databricks as pub  # noqa: E402

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format

PROFILE = "bv"
WAREHOUSE = "5922c26f81f1bbdd"
CATALOG, SCHEMA = "bv_dev_db", "monitoramento_sas_dev"


def q(sql):
    w = WorkspaceClient(profile=PROFILE)
    resp = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
        catalog=CATALOG, schema=SCHEMA)
    sid = resp.statement_id
    while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        resp = w.statement_execution.get_statement(statement_id=sid)
    cols = [c.name for c in resp.manifest.schema.columns]
    out = []
    if resp.result and resp.result.data_array:
        for row in resp.result.data_array:
            out.append(dict(zip(cols, row)))
    return out


def main():
    rows06 = list(csv.DictReader(open("06_prontidao_tabela.csv", encoding="utf-8")))
    conv_art = {r["artifact"].upper() for r in rows06
                if r["source_type"] == "SAS/Local (.sas7bdat sob LIBNAME)"}
    rem_art = {r["artifact"].upper() for r in rows06
               if r["category"] == "file_in" and r["artifact"].lower().endswith(".sas7bdat")
               and r["source_type"] == ""}
    print(f"06_prontidao_tabela.csv: {len(conv_art)} chaves convertidas p/ table_in, "
          f"{len(rem_art)} chaves ainda file_in (guards)")

    print("\n== build() local (pós-fix, não publicado) ==")
    data = pub.build(choices={})
    print(f"  inputs (grão distinto): {len(data['inputs'])}")

    convertidos = [r for r in data["inputs"]
                   if r.get("categoria") == "tabela" and (r.get("artifact") or "").upper() in conv_art]
    remanesc = [r for r in data["inputs"]
                if r.get("categoria") == "arquivo" and (r.get("artifact") or "").upper() in rem_art]
    print(f"  achados no inputs_monitor final -> convertidos: {len(convertidos)}/{len(conv_art)}"
          f"  remanescentes: {len(remanesc)}/{len(rem_art)}")

    disp_conv = [r for r in convertidos if r.get("modernizada_auto") == "Disponível"]
    ating_conv = [r for r in convertidos if r.get("modernizada_auto") != "Disponível"]
    print(f"\n  dos convertidos: {len(disp_conv)} já 'Disponível' | {len(ating_conv)} ainda pendentes"
          f" (mesmo depois de virar table_in — não bateram Chameleon/RepMap/Inventário/override)")

    def indi_count(rows):
        return sum(1 for r in rows if r.get("escopo_indi"))

    print(f"\n  escopo indi (direto) — convertidos: {indi_count(convertidos)}/{len(convertidos)}"
          f" | remanescentes: {indi_count(remanesc)}/{len(remanesc)}")

    print("\n== reconstruindo frontier indi_deps (leitura read-only dev) ==")
    base = {n["projeto"] for n in data["nodes"] if n.get("escopo_indi")}
    no_expand = {r["projeto"] for r in q(
        "SELECT projeto FROM sas_egp_pipeline WHERE status_migracao = 'Despriorizado e Contabilizado'")}
    resolvidas = {str(r["artifact"]).strip().upper() for r in q(
        f"SELECT artifact FROM sas_inputs_monitor WHERE categoria = 'tabela' AND ({pub._modern_sql()})")
        if r.get("artifact")}
    frontier = pub.frontier_egps(data["edges"], base, no_expand, resolvidas)
    print(f"  base indi: {len(base)}  no_expand: {len(no_expand)}  frontier indi_deps: {len(frontier)}")

    chave_proj = collections.defaultdict(set)
    for r in data["egp_inputs"]:
        chave_proj[r["chave_canonica"]].add(r["projeto"])

    def deps_only_count(rows):
        # no frontier mas NÃO no escopo indi direto (o "+X só" da memória)
        return sum(1 for r in rows
                   if not r.get("escopo_indi") and (chave_proj.get(r["chave_canonica"], set()) & frontier))

    def indi_deps_count(rows):
        return sum(1 for r in rows if chave_proj.get(r["chave_canonica"], set()) & frontier)

    print(f"\n  escopo indi_deps (indi + deps transitivas) — convertidos: "
          f"{indi_deps_count(convertidos)}/{len(convertidos)} (+{deps_only_count(convertidos)} só via deps)"
          f" | remanescentes: {indi_deps_count(remanesc)}/{len(remanesc)} "
          f"(+{deps_only_count(remanesc)} só via deps)")

    print("\n== dependências (linhagem) ==")
    alvo_upper = conv_art | rem_art
    edges_touch = [e for e in data["edges"]
                   if any(t.strip().upper() in alvo_upper
                          for t in (e.get("via_tabelas") or "").split(" | "))]
    print(f"  arestas do grafo que citam algum artifact .sas7bdat (convertido ou remanescente) "
          f"como via: {len(edges_touch)}")
    print("  -> confirma o que 7b385cb4 já media: 03_matriz_dependencias.csv byte-idêntico — "
          "nenhuma dessas tabelas é output de EGP do corpus, o fix não move nenhuma aresta.")


if __name__ == "__main__":
    main()

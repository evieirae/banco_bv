#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera o CSV de modelagem do grafo de linhagem para o kit `sas_neo4j_setup`
(~/bv/sas_assessment_tool/sas_neo4j_setup), a partir dos reports SANEADOS
do pipeline (03_matriz_dependencias.csv + 06_prontidao_tabela.csv).

Formato de saída (o que o csv_to_cypher.py espera):
    nome_pai,tipo_pai,tipo_relacionamento,nome_filho,tipo_filho

Modelo (labels restritos aos 4 que o loader do docker-compose carrega):
    (EgpProject)-[:READS_FROM]->(ExternalSource)   tabela de banco (BQ/Postgres/Sybase/IQ/SQLSVR) ou arquivo
    (EgpProject)-[:READS_FROM]->(LibnameSource)    tabela SAS/Local (nome = path/lib.member, como no exemplo)
    (EgpProject)-[:WRITES_TO]->(ExternalSource|LibnameSource)
    (EgpProject)-[:DEPENDS_ON]->(IncludeFiles)     %include de script
    (EgpProject)-[:DEPENDS_ON]->(EgpProject)       dependência projeto→projeto (report 03)

Ruído excluído: WORK./DICTIONARY./SASHELP./SASUSER., placeholders de macro
(&VAR, {…}) e *.sas7(bdat).

Uso (do root do project_sas):
    python egps_analysis/docs/analises/build_neo4j_modelagem.py \
        [saida.csv = ~/bv/sas_assessment_tool/sas_neo4j_setup/modelagem_bv.csv]
"""
import csv
import os
import sys

R06 = "egps_analysis/06_prontidao_tabela.csv"
R03 = "egps_analysis/03_matriz_dependencias.csv"
OUT_DEFAULT = os.path.expanduser(
    "~/bv/sas_assessment_tool/sas_neo4j_setup/modelagem_bv.csv")

DB_MARKERS = ("BIGQUERY", "POSTGRES", "SYBASE", "IQ", "ASE", "SQLSVR",
              "SQLSERVER", "ORACLE", "DBCON", "CONNECTION")


def is_noise(art):
    a = art.upper()
    if a.startswith(("WORK.", "DICTIONARY.", "SASHELP.", "SASUSER.")):
        return True
    if "&" in a or "{" in a or "}" in a:
        return True
    if a.endswith((".SAS7", ".SAS7BDAT")):
        return True
    return False


def table_label(source_type):
    s = (source_type or "").upper()
    return "ExternalSource" if any(m in s for m in DB_MARKERS) else "LibnameSource"


def node_name(artifact, path, label):
    # segue o exemplo do kit: LibnameSource leva o path quando existe
    a = artifact.strip().lower()
    p = (path or "").strip().rstrip("/").lower()
    if label == "LibnameSource" and p:
        return f"{p}/{a}"
    return a


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else OUT_DEFAULT
    edges = set()

    with open(R06, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            proj = (r.get("project") or "").strip()
            art = (r.get("artifact") or "").strip()
            cat = (r.get("category") or "").strip()
            if not proj or not art:
                continue
            if cat in ("table_in", "table_out"):
                if is_noise(art):
                    continue
                lbl = table_label(r.get("source_type"))
                name = node_name(art, r.get("path"), lbl)
                rel = "READS_FROM" if cat == "table_in" else "WRITES_TO"
                edges.add((proj.lower(), "EgpProject", rel, name, lbl))
            elif cat == "file_in":
                edges.add((proj.lower(), "EgpProject", "READS_FROM",
                           art.lower(), "ExternalSource"))
            elif cat == "script_in":
                edges.add((proj.lower(), "EgpProject", "DEPENDS_ON",
                           art.lower(), "IncludeFiles"))

    with open(R03, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        c = rd.fieldnames
        for r in rd:
            alvo = r[c[0]].strip()
            dep = r[c[1]].strip()
            if alvo and dep and alvo != dep:
                edges.add((alvo.lower(), "EgpProject", "DEPENDS_ON",
                           dep.lower(), "EgpProject"))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nome_pai", "tipo_pai", "tipo_relacionamento",
                    "nome_filho", "tipo_filho"])
        for e in sorted(edges):
            w.writerow(e)

    import collections
    rels = collections.Counter(e[2] for e in edges)
    labels = collections.Counter()
    for e in edges:
        labels[e[1]] = 1
    nodes = {(e[0], e[1]) for e in edges} | {(e[3], e[4]) for e in edges}
    by_label = collections.Counter(l for _n, l in nodes)
    print(f"escrito: {out_path}")
    print(f"arestas: {len(edges)} -> {dict(rels)}")
    print(f"nós: {len(nodes)} -> {dict(by_label)}")


if __name__ == "__main__":
    main()

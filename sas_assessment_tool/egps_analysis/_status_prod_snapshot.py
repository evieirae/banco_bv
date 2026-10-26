#!/usr/bin/env python3
"""TEMP/throwaway: backup READ-ONLY das edições humanas em prod antes do republish.
Exporta sas_inputs_monitor (colunas humanas), sas_egp_pipeline e sas_escopo para
JSON local, e imprime contagens. Só SELECT — não escreve nada.
Uso: egps_analysis/venv/bin/python egps_analysis/_status_prod_snapshot.py [tag]
"""
import json
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format

WID = "5922c26f81f1bbdd"
FQ = "bv_dev_db.monitoramento_sas"
TAG = sys.argv[1] if len(sys.argv) > 1 else "pre"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_status_prod_backup")
os.makedirs(OUT, exist_ok=True)
W = WorkspaceClient(profile="bv")


def q(sql):
    r = W.statement_execution.execute_statement(
        statement=sql, warehouse_id=WID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = W.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "estado desconhecido")
    cols = [c.name for c in r.manifest.schema.columns]
    rows = r.result.data_array or []
    return [dict(zip(cols, row)) for row in rows]


def dump(name, rows):
    path = os.path.join(OUT, f"{name}.{TAG}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    return path


# coluna origem já existe em prod? (informativo)
try:
    q(f"SELECT origem FROM {FQ}.sas_inputs_monitor LIMIT 0")
    origem_existe = True
except Exception:
    origem_existe = False

# 1. inputs com edição humana (qualquer sinal humano)
inputs_h = q(
    f"SELECT chave_canonica, status_humano, responsavel, observacao, updated_by, updated_at, orfao "
    f"FROM {FQ}.sas_inputs_monitor "
    f"WHERE updated_by IS NOT NULL OR (responsavel IS NOT NULL AND responsavel <> '') "
    f"OR (observacao IS NOT NULL AND observacao <> '') "
    f"OR status_humano NOT IN ('A receber', 'Modernizado')")
total_monitor = q(f"SELECT count(*) AS n FROM {FQ}.sas_inputs_monitor")[0]["n"]

# 2. egp pipeline (só existe linha quando alguém editou status do EGP)
egp = q(f"SELECT projeto, etapa_migracao, status_migracao, etapa_progresso, status_progresso, "
        f"updated_by, updated_at FROM {FQ}.sas_egp_pipeline")

# 3. escopo (editável)
esc_n = q(f"SELECT count(*) AS n FROM {FQ}.sas_escopo")[0]["n"]

p1 = dump("inputs_humanos", inputs_h)
p2 = dump("egp_pipeline", egp)

print(f"=== SNAPSHOT prod ({TAG}) — {FQ} ===")
print(f"coluna 'origem' já existe em prod : {origem_existe}")
print(f"sas_inputs_monitor total          : {total_monitor}")
print(f"  └ com edição humana (backup)    : {len(inputs_h)}  -> {p1}")
print(f"sas_egp_pipeline (status de EGP)  : {len(egp)}  -> {p2}")
print(f"sas_escopo (linhas)               : {esc_n}")
# resumo dos status humanos dos inputs
from collections import Counter
cs = Counter((r.get("status_humano") or "∅") for r in inputs_h)
print("  distribuição status_humano (editados):", dict(cs))
cse = Counter((r.get("status_migracao") or "∅") for r in egp)
print("  distribuição status_migracao (egp)   :", dict(cse))

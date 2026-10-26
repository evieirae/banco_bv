#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Snapshot READ-ONLY de sas_egp_pipeline -> src/pipeline_status_snapshot.csv.

Alimenta o eixo de veto do compare_egp_versions.py: sem este snapshot o script não
sabe se o EGP antigo já foi convertido e os quadrantes saem provisórios.

Só SELECT. Não escreve nada em prod.

Uso (da pasta egps_analysis/):
    venv/bin/python pipeline_status_snapshot.py
    venv/bin/python pipeline_status_snapshot.py --out src/pipeline_status_snapshot.csv

O compare_egp_versions.py recusa snapshot com mais de 7 dias (SNAPSHOT_VALIDADE_DIAS).
"""
import argparse
import csv
import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

WAREHOUSE_ID = "5922c26f81f1bbdd"
SCHEMA = "bv_dev_db.monitoramento_sas"
COLUNAS = ["projeto", "area", "etapa_migracao", "status_migracao",
           "etapa_progresso", "status_progresso", "ativo"]
# Colunas sem as quais o VETO de etapa do compare não pode ser avaliado. Omiti-las
# (como o filtro por `disponiveis` fazia em silêncio) deixa todas as linhas com
# etapa/status vazios -> idx = -1 em ETAPAS_MIGRACAO -> nenhum veto e nenhum alerta,
# para TODO EGP já convertido do lote. Ausência aqui é drift de schema, não dado
# faltando — e este repo já teve prod quebrada por isso (ALTER de 2026-08-29).
COLUNAS_CRITICAS = ["projeto", "etapa_migracao", "status_migracao"]


def query(w, sql, warehouse_id=WAREHOUSE_ID):
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "estado desconhecido")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest else []
    # Segue next_chunk_index: lendo só `r.result.data_array` ficava o PRIMEIRO chunk
    # inline, e o resto sumia sem erro. Aqui isso é grave de um jeito específico: as
    # linhas perdidas fazem um EGP já convertido parecer ausente do pipeline, ele não
    # recebe veto e o compare libera como "pode trocar". Mesmo laço já provado em
    # docs/analises/backup_overlays_prod.py.
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = chunk.next_chunk_index
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    return [dict(zip(cols, row)) for row in linhas]


def busca_linhas(profile="bv", schema=SCHEMA):
    """Busca ao vivo (READ-ONLY) as linhas de sas_egp_pipeline, restritas às COLUNAS
    presentes na tabela. Devolve (cols, rows) com rows como lista de dicts — o formato
    que compare_egp_versions.carrega_snapshot aceita direto, sem CSV intermediário."""
    w = WorkspaceClient(profile=profile)
    disponiveis = {r["col_name"] for r in
                   query(w, f"DESCRIBE TABLE {schema}.sas_egp_pipeline")
                   if r.get("col_name")}
    cols = [c for c in COLUNAS if c in disponiveis]
    faltando = [c for c in COLUNAS if c not in disponiveis]
    criticas_faltando = [c for c in COLUNAS_CRITICAS if c not in disponiveis]
    if criticas_faltando:
        raise RuntimeError(
            f"{schema}.sas_egp_pipeline não tem a(s) coluna(s) {criticas_faltando}, "
            f"sem a(s) qual(is) o veto de etapa do compare não pode ser avaliado — "
            f"todo EGP já convertido passaria como 'pode trocar'. "
            f"Colunas encontradas: {sorted(disponiveis)}")
    if faltando:
        print(f"aviso: colunas ausentes na tabela e omitidas do snapshot: {faltando}")
    rows = query(w, f"SELECT {', '.join(cols)} FROM {schema}.sas_egp_pipeline")
    return cols, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="src/pipeline_status_snapshot.csv")
    ap.add_argument("--profile", default="bv")
    ap.add_argument("--schema", default=SCHEMA)
    args = ap.parse_args()

    cols, rows = busca_linhas(profile=args.profile, schema=args.schema)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)

    com_etapa = sum(1 for r in rows if (r.get("etapa_migracao") or "").strip())
    print(f"snapshot: {len(rows)} EGPs ({com_etapa} com etapa definida) -> {args.out}")


if __name__ == "__main__":
    main()

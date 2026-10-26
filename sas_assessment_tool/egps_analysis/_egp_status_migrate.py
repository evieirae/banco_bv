#!/usr/bin/env python3
"""TEMP/gate-humano: recapitaliza status_migracao em sas_egp_pipeline
(Em andamento->Em Andamento, A iniciar->A Iniciar). NÃO toca
Concluído/Block/Removido/NULL. Idempotente. SÓ grava com --apply.
Uso: egps_analysis/venv/bin/python egps_analysis/_egp_status_migrate.py [--apply]
"""
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format

W = WorkspaceClient(profile="bv")
WID = "5922c26f81f1bbdd"
FQ = "bv_dev_db.monitoramento_sas"
RENAMES = [("Em andamento", "Em Andamento"), ("A iniciar", "A Iniciar")]


def q(sql):
    r = W.statement_execution.execute_statement(
        statement=sql, warehouse_id=WID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = W.statement_execution.get_statement(statement_id=r.statement_id)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "estado desconhecido")
    return r.result.data_array or []


def lit(s):
    # Aspa escapada com \' e NÃO com '' : no Spark SQL `'O''Brien'` é lido como DOIS
    # literais adjacentes concatenados ("O" + "Brien"), então o apóstrofo some em
    # silêncio — não dá erro, grava o texto errado. Verificado no warehouse:
    #   SELECT 'O''Brien'  -> OBrien      (errado)
    #   SELECT 'O\'Brien'  -> O'Brien     (certo)
    # A contrabarra é escapada ANTES da aspa, senão a barra introduzida por \' seria
    # duplicada. Não confundir com sas_quote() em egps_extractor.py: aquilo gera código
    # SAS, onde '' É o escape correto.
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def main():
    apply = "--apply" in sys.argv
    for old, new in RENAMES:
        n = int(q(f"SELECT count(*) FROM {FQ}.sas_egp_pipeline WHERE status_migracao = {lit(old)}")[0][0])
        print(f"{old!r} -> {new!r}: {n} linha(s)")
        if apply and n > 0:
            q(f"UPDATE {FQ}.sas_egp_pipeline SET status_migracao = {lit(new)} WHERE status_migracao = {lit(old)}")
            print("  aplicado.")
    print("\n[dry-run] use --apply para gravar" if not apply else "\nok")


if __name__ == "__main__":
    main()

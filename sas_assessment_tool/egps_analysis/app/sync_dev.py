#!/usr/bin/env python3
"""sync_dev.py — espelha o schema de PROD (bv_dev_db.monitoramento_sas) no schema DEV
(bv_dev_db.monitoramento_sas_dev). READ-only em prod, WRITE-only em dev.

Motivação: dev tende a divergir de prod (ingestões locais, ambiente compartilhado);
para validar o plano da Priorização com números reais, dev precisa refletir prod.
Este script é a única forma sancionada de trazer dev de volta ao alinhamento — todas
as leituras têm prefixo `monitoramento_sas.`, todas as escritas têm prefixo
`monitoramento_sas_dev.`, e há guard anti-prod (recusa se o destino não é `_dev`).

Uso:
  python3 sync_dev.py                    # sincroniza tudo (confirmação interativa)
  python3 sync_dev.py --dry-run          # só lista as tabelas e as SQLs
  python3 sync_dev.py --only sas_egp_pipeline sas_inputs_monitor
  python3 sync_dev.py --yes              # pula confirmação (uso não-interativo)

Exclusões (estado próprio de dev, NÃO sincronizado):
  sas_pipeline_audit          — trilha de auditoria própria de dev
  sas_inputs_audit, sas_escopo_audit — idem
  (o snapshot da priorização VEM DE PROD — é a fonte da verdade do plano.)

Auditoria: cada SQL executado sai no stdout com wallclock. Redirecione para arquivo
se quiser trilha persistente:  python3 sync_dev.py --yes 2>&1 | tee /tmp/sync-$(date +%s).log
"""
import argparse
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

PROD_CATALOG = os.environ.get("PROD_CATALOG", "bv_dev_db")
PROD_SCHEMA = os.environ.get("PROD_SCHEMA", "monitoramento_sas")
DEV_CATALOG = os.environ.get("DEV_CATALOG", "bv_dev_db")
DEV_SCHEMA = os.environ.get("DEV_SCHEMA", "monitoramento_sas_dev")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "5922c26f81f1bbdd")

# ----- guardas anti-prod: matam o script se o destino não for claramente _dev -----
if not DEV_SCHEMA.endswith("_dev"):
    sys.exit(f"❌ DEV_SCHEMA={DEV_SCHEMA!r} não termina em '_dev' — recuso escrever fora de dev.")
if DEV_SCHEMA == PROD_SCHEMA and DEV_CATALOG == PROD_CATALOG:
    sys.exit(f"❌ DEV == PROD ({DEV_CATALOG}.{DEV_SCHEMA}) — recuso sobrescrever prod com prod.")

# estado exclusivo de dev — não vem de prod (trilhas de auditoria são per-schema)
EXCLUDE = {
    "sas_pipeline_audit",
    "sas_inputs_audit",
    "sas_escopo_audit",
    "sas_egp_input_link_audit",   # audit dedicado ao overlay de vínculo (per-schema)
}

wc = WorkspaceClient()


def sql(stmt, want_rows=True):
    """Executa 1 statement no warehouse. Loga o statement (auditoria)."""
    print(f"  ▸ {stmt}", flush=True)
    r = wc.statement_execution.execute_statement(
        statement=stmt, warehouse_id=WAREHOUSE_ID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    # long polling se ainda pending/running
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = wc.statement_execution.get_statement(sid)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL falhou ({r.status.state}): {r.status.error}\n  {stmt}")
    if not want_rows or not r.result:
        return []
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest else []
    # Segue next_chunk_index: com INLINE só o PRIMEIRO chunk vem na resposta, então ler
    # apenas `r.result.data_array` truncava em silêncio. Aqui isso alimentava a cópia
    # prod->dev, ou seja, o dev ficava com um recorte do prod sem ninguém saber — some
    # uma das causas do "sync parcial" que já obrigou a conferir contagens na mão.
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = wc.statement_execution.get_statement_result_chunk_n(sid, nxt)
    return [dict(zip(cols, row)) for row in linhas]


def list_prod_tables():
    """Descobre as tabelas em prod. Filtra sas_*, aplica EXCLUDE."""
    rows = sql(f"SHOW TABLES IN {PROD_CATALOG}.{PROD_SCHEMA}")
    # SHOW TABLES retorna colunas: database, tableName, isTemporary
    tables = [r.get("tableName") for r in rows if (r.get("tableName") or "").startswith("sas_")]
    return sorted(set(tables) - EXCLUDE)


def sync_one(t, dry_run=False):
    """Substitui a tabela em dev por um DEEP CLONE da tabela em prod (atômico, Delta)."""
    src = f"{PROD_CATALOG}.{PROD_SCHEMA}.{t}"
    dst = f"{DEV_CATALOG}.{DEV_SCHEMA}.{t}"
    q = f"CREATE OR REPLACE TABLE {dst} DEEP CLONE {src}"
    if dry_run:
        print(f"  [dry-run] {q}")
        return
    t0 = time.time()
    sql(q, want_rows=False)
    # count de sanidade
    n = sql(f"SELECT count(*) AS n FROM {dst}")[0].get("n")
    print(f"  ✔ {t}  rows={n}  ({time.time()-t0:.1f}s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="lista o que faria, sem escrever")
    ap.add_argument("--only", nargs="+", metavar="TABLE", help="sincroniza só essas tabelas")
    ap.add_argument("--yes", action="store_true", help="pula confirmação interativa")
    args = ap.parse_args()

    print(f"prod (read-only): {PROD_CATALOG}.{PROD_SCHEMA}")
    print(f"dev  (write):     {DEV_CATALOG}.{DEV_SCHEMA}")
    print(f"warehouse:        {WAREHOUSE_ID}")
    print()

    tables = list_prod_tables()
    if args.only:
        req = set(args.only)
        missing = req - set(tables)
        if missing:
            sys.exit(f"❌ tabelas não encontradas em prod (ou excluídas): {sorted(missing)}")
        tables = [t for t in tables if t in req]

    print(f"tabelas a sincronizar ({len(tables)}):")
    for t in tables:
        print(f"  - {t}")
    print(f"\nexcluídas (estado próprio de dev): {sorted(EXCLUDE)}")
    print()

    if args.dry_run:
        print("--- DRY RUN ---")
    elif not args.yes:
        try:
            resp = input(f"prosseguir e SOBRESCREVER {len(tables)} tabelas em {DEV_SCHEMA}? [y/N] ")
        except EOFError:
            sys.exit("❌ stdin fechado; use --yes se está rodando não-interativo")
        if resp.strip().lower() not in ("y", "yes"):
            sys.exit("cancelado.")

    t0 = time.time()
    for t in tables:
        sync_one(t, dry_run=args.dry_run)
    print(f"\n✔ concluído em {time.time()-t0:.1f}s ({len(tables)} tabelas)")


if __name__ == "__main__":
    main()

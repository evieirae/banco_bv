"""Patch scoped à correção %DESCOMPACTA: aplica APENAS as chaves derivadas
do fix (whitelist) do snapshot bkp_sas_* ao schema alvo (dev prod-mirror
ou prod). Não toca em nenhuma linha fora da whitelist.

Uso:
  python patch_descompacta.py                       # dry-run contra dev
  python patch_descompacta.py --apply               # aplica em dev
  python patch_descompacta.py --schema monitoramento_sas --apply --prod-confirm
                                                    # aplica em PROD

Pré-requisitos:
  - bkp_sas_{inputs_monitor,egp_inputs,lineage_edges} existem em
    bv_dev_db.monitoramento_sas_dev (snapshot pós-publish com o fix).
  - /tmp/descompacta_whitelist.txt existe (gerado pelo passo de compute).
  - DATABRICKS_CONFIG_PROFILE=bv, DATABRICKS_DEFAULT_WAREHOUSE_ID ou --warehouse-id.
"""
import argparse
import os
import sys
from databricks.sdk import WorkspaceClient

WAREHOUSE = os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID", "5922c26f81f1bbdd")
PROD_SCHEMA = "monitoramento_sas"
BKP_SCHEMA = "bv_dev_db.monitoramento_sas_dev"  # onde vivem os bkp_*
WHITELIST_FILE = "/tmp/descompacta_whitelist.txt"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="bv_dev_db")
    ap.add_argument("--schema", default="monitoramento_sas_dev",
                    help="alvo (default sandbox); use monitoramento_sas com --prod-confirm p/ prod")
    ap.add_argument("--apply", action="store_true", help="escreve (default: dry-run)")
    ap.add_argument("--prod-confirm", action="store_true",
                    help="obrigatório se --schema apontar para PROD")
    ap.add_argument("--warehouse-id", default=WAREHOUSE)
    args = ap.parse_args()
    if args.schema == PROD_SCHEMA and args.apply and not args.prod_confirm:
        ap.error(f"--apply contra PROD ({args.catalog}.{args.schema}) requer --prod-confirm")
    return args


def main():
    args = parse_args()
    tgt = f"{args.catalog}.{args.schema}"
    print(f"== PATCH DESCOMPACTA ==")
    print(f"  bkp source: {BKP_SCHEMA}.bkp_sas_*")
    print(f"  target:     {tgt}.sas_*")
    print(f"  apply:      {args.apply}{'  (PROD!)' if args.schema == PROD_SCHEMA else ''}")

    wl = [ln.strip() for ln in open(WHITELIST_FILE) if ln.strip()]
    print(f"  whitelist:  {len(wl)} chaves")

    wc = WorkspaceClient()
    def run(sql, want=False):
        print(f"  ▸ {sql[:180]}{' ...' if len(sql) > 180 else ''}")
        r = wc.statement_execution.execute_statement(
            warehouse_id=args.warehouse_id, statement=sql, wait_timeout="50s"
        )
        if r.status.state.value != "SUCCEEDED":
            raise SystemExit(f"FAIL: {r.status}")
        return (r.result.data_array if r.result else []) or []

    # (Re)cria a staging da whitelist no schema-alvo (idempotente entre runs).
    STG = f"{tgt}.tmp_desc_whitelist"
    print(f"\n-- staging whitelist ({STG}) --")
    run(f"CREATE OR REPLACE TABLE {STG} (chave_canonica STRING) USING DELTA")
    for i in range(0, len(wl), 200):
        vals = ",".join(f"('{c}')" for c in wl[i:i+200])
        run(f"INSERT INTO {STG} VALUES {vals}")
    n_stg = int(run(f"SELECT count(*) FROM {STG}", True)[0][0])
    print(f"  whitelist staged: {n_stg}")

    # 1) inputs_monitor — INSERT novas chaves.
    print("\n-- sas_inputs_monitor --")
    sel = f"""SELECT b.chave_canonica, b.artifact, b.categoria, b.source_types, b.qtd_projetos,
       b.areas, b.escopo_indi, b.modernizada_auto, b.status_humano, b.responsavel,
       b.observacao, b.updated_at, b.updated_by, b.orfao, b.refreshed_at, b.origem,
       b.paths_fisicos, b.n_paths_fisicos
FROM {BKP_SCHEMA}.bkp_sas_inputs_monitor b
JOIN {STG} w ON b.chave_canonica = w.chave_canonica
WHERE b.chave_canonica NOT IN (SELECT chave_canonica FROM {tgt}.sas_inputs_monitor)"""
    n = int(run(f"SELECT count(*) FROM ({sel}) x")[0][0])
    print(f"  a inserir: {n}")
    if args.apply and n > 0:
        run(f"INSERT INTO {tgt}.sas_inputs_monitor {sel}")

    # 2) egp_inputs — INSERT pares (projeto, chave). Atributos (area, onda,
    #    escopo_indi, ciclo_id) vêm de sas_lineage_nodes ALVO (registry canônico do
    #    projeto no schema-alvo). Isso evita divergência com linhas pré-existentes
    #    do mesmo projeto (ex.: Onda drifted no bkp → duplica card no frontend).
    print("\n-- sas_egp_inputs --")
    sel = f"""SELECT b.projeto,
       COALESCE(n.area, b.area) AS area,
       COALESCE(n.onda, b.onda) AS onda,
       COALESCE(n.escopo_indi, b.escopo_indi) AS escopo_indi,
       COALESCE(n.ciclo_id, b.ciclo_id) AS ciclo_id,
       b.chave_canonica, b.artifact, b.categoria, b.source_types, b.modernizada_auto
FROM {BKP_SCHEMA}.bkp_sas_egp_inputs b
JOIN {STG} w ON b.chave_canonica = w.chave_canonica
LEFT JOIN {tgt}.sas_lineage_nodes n ON b.projeto = n.projeto
WHERE NOT EXISTS (
  SELECT 1 FROM {tgt}.sas_egp_inputs d
  WHERE d.projeto = b.projeto AND d.chave_canonica = b.chave_canonica
)"""
    n = int(run(f"SELECT count(*) FROM ({sel}) x")[0][0])
    print(f"  a inserir: {n}")
    if args.apply and n > 0:
        run(f"INSERT INTO {tgt}.sas_egp_inputs {sel}")

    # 3) lineage_edges — INSERT arestas onde via_tabelas referencia chave da whitelist.
    #    (Schema alvo tem 4 cols; bkp tem 5 — max_produtores é descartado.)
    print("\n-- sas_lineage_edges --")
    sel = f"""SELECT b.projeto_alvo, b.depende_do, b.via_tabelas, b.qtd_via
FROM {BKP_SCHEMA}.bkp_sas_lineage_edges b
WHERE EXISTS (
  SELECT 1 FROM {STG} w
  WHERE b.via_tabelas LIKE concat('%', regexp_replace(w.chave_canonica, '^tabela::', ''), '%')
)
AND NOT EXISTS (
  SELECT 1 FROM {tgt}.sas_lineage_edges d
  WHERE d.projeto_alvo = b.projeto_alvo AND d.depende_do = b.depende_do
)"""
    n = int(run(f"SELECT count(*) FROM ({sel}) x")[0][0])
    print(f"  a inserir: {n}")
    if args.apply and n > 0:
        run(f"INSERT INTO {tgt}.sas_lineage_edges {sel}")

    # Limpa staging
    run(f"DROP TABLE IF EXISTS {STG}")

    print(f"\n{'✅ PATCH aplicado' if args.apply else '[dry-run] nenhuma escrita'} em {tgt}")


if __name__ == "__main__":
    sys.exit(main())

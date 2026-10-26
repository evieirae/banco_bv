#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dump READ-ONLY das tabelas de OVERLAY HUMANO do app monitoramento-sas, para rodar ANTES
de um re-publish (que faz full replace de sas_egp_inputs/lineage_* e MERGE em
sas_inputs_monitor).

Por que: o publish preserva as colunas humanas e nem toca nas tabelas de overlay, mas a
identidade é `(projeto, chave_canonica)` / `categoria::ARTIFACT`. Se uma re-extração
mudar o nome de um artefato ou de um EGP (re-key), a edição humana fica numa linha órfã
e o item reentra como pendente. Este dump é o seguro para reaplicar nesse caso.

Tabelas cobertas (as que o publish NÃO recria — perda aqui é irrecuperável):
  sas_egp_input_link (+audit)   vínculos quebrados por par (EGP, input)
  sas_inputs_monitor            colunas humanas: etapa/status/responsavel/observacao
  sas_escopo (+audit)           escopo editável (ativo/inativo)
  sas_egp_pipeline (+audit)     funis de migração por EGP, mês, jira
  sas_output_producer_choice    produtor canônico escolhido
  sas_gestao_status/datas/bv    tela de Gestão
  sas_inputs_preworking         checklist de pré-working
  sas_app_config                capacidade do plano etc.
  sas_priorizacao_snapshot      plano congelado
  sas_inputs_audit              histórico de edições de input

Uso:
  cd egps_analysis
  venv/bin/python3 docs/analises/backup_overlays_prod.py \
      --profile bv --warehouse-id 5922c26f81f1bbdd
  # -> docs/analises/backup_prod_overlays_<AAAA-MM-DD>/<tabela>.csv
"""
import argparse
import csv
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))

# Tabelas de overlay humano. Sem coluna de ordenação: a leitura é única e segue
# next_chunk_index (ver run()). A config antiga pedia uma "coluna de ordenação única"
# por tabela e duas das declaradas NÃO eram únicas, o que corrompia a paginação.
TABELAS = [
    "sas_egp_input_link",
    "sas_egp_input_link_audit",
    "sas_inputs_monitor",
    "sas_escopo",
    "sas_escopo_audit",
    "sas_egp_pipeline",
    "sas_pipeline_audit",
    "sas_output_producer_choice",
    "sas_gestao_status",
    "sas_gestao_datas",
    "sas_gestao_bv",
    "sas_inputs_preworking",
    "sas_app_config",
    "sas_priorizacao_snapshot",
    "sas_inputs_audit",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"),
                     help="sufixo da pasta de saída (default: hoje)")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_DEFAULT_WAREHOUSE_ID")

    outdir = args.outdir or os.path.join(BASE, f"backup_prod_overlays_{args.date}")
    os.makedirs(outdir, exist_ok=True)

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"

    def run(sql):
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if (resp.status and resp.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:400]}")
        cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest else []
        # Segue next_chunk_index: antes lia SÓ o primeiro chunk inline, então qualquer
        # tabela que não coubesse nele era truncada em silêncio — num script cuja função
        # é ser a rede de segurança ANTES de operação destrutiva.
        data, chunk = [], resp.result
        while chunk is not None:
            data.extend(chunk.data_array or [])
            nxt = chunk.next_chunk_index
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
        return cols, data

    print(f"== backup de overlays ==  origem: {fq}  ->  {outdir}")
    total_linhas, falhas = 0, []
    for tabela in TABELAS:
        try:
            n = int(run(f"SELECT count(*) AS n FROM {fq}.{tabela}")[1][0][0])
        except RuntimeError as e:
            falhas.append((tabela, str(e).split("\n")[0][:90]))
            print(f"  [SKIP] {tabela:<28} {str(e).split(chr(10))[0][:70]}")
            continue

        # Leitura única + next_chunk_index, SEM paginação por OFFSET. A paginação antiga
        # ordenava por uma coluna declarada "única" que não era — `projeto` em
        # sas_egp_input_link (um EGP tem vários inputs) e `chave_canonica` em
        # sas_inputs_audit (várias linhas por chave). LIMIT/OFFSET sobre ordenação com
        # empates não é determinístico entre as páginas: linhas caem e outras se
        # repetem — e como as duas coisas se compensam, o check `len(rows) == n` abaixo
        # continuava dizendo "ok" com um backup silenciosamente errado.
        if n == 0:
            cols, rows = run(f"SELECT * FROM {fq}.{tabela} LIMIT 0")
        else:
            cols, rows = run(f"SELECT * FROM {fq}.{tabela}")

        path = os.path.join(outdir, f"{tabela}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wtr = csv.writer(f, delimiter=";")
            wtr.writerow(cols)
            wtr.writerows(rows)
        ok = "ok" if len(rows) == n else f"ATENÇÃO: esperava {n}"
        print(f"  {tabela:<28} {len(rows):>6} linhas  ({ok})")
        if len(rows) != n:
            falhas.append((tabela, f"dump {len(rows)} != count {n}"))
        total_linhas += len(rows)

    print(f"\ntotal: {total_linhas} linhas em {outdir}")
    if falhas:
        print("PROBLEMAS:")
        for t, m in falhas:
            print(f"  - {t}: {m}")
    else:
        print("todas as tabelas conferiram com o count().")


if __name__ == "__main__":
    main()

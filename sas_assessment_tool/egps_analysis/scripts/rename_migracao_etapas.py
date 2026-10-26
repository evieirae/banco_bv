#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migração ÚNICA: renomeia 3 etapas do funil de MIGRAÇÃO já gravadas em
`sas_egp_pipeline.etapa_migracao` — o rótulo é o próprio valor persistido (não há
código separado do texto), então renomear só `PIPELINE_PROJETO` em
`egps_analysis/app/backend/main.py` / `frontend/src/pipeline.ts` faz qualquer EGP
HOJE numa dessas 3 etapas sumir do funil (a etapa deixa de bater com a lista nova —
ver `_funnel_bars`/`et not in idx`). Este script casa os dados com o rename de código.

NÃO mexe no funil de INPUTS (`PIPELINE_INPUT`/`sas_inputs_monitor.etapa`) — "Pré-
Working" e "Aplicação de Grant" são rótulos compartilhados por coincidência entre os
dois funis; só a coluna `etapa_migracao` de `sas_egp_pipeline` é tocada aqui.

Mapeamento (confirmado com o usuário 2026-08-24 — não alterar sem revisitar a decisão):

  etapa_migracao (antigo)      -> etapa_migracao (novo)
  ------------------------------------------------------------------------------
  Pré-Working                  -> Pré-Working + Outputs
  Aprv. PR                     -> Aprv. PR + Validação Governança
  Artefatos de GOV.            -> Aplicação de Grant

Escreve via UPDATE (1 por mapeamento) + 1 linha de auditoria por EGP afetado em
`sas_pipeline_audit` (campo='etapa_migracao', mesmo padrão do PATCH
/api/egp-pipeline). Idempotente: depois de rodar, o rótulo antigo não existe mais —
rodar de novo não encontra candidatos.

Uso:
  cd egps_analysis
  python scripts/rename_migracao_etapas.py --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # dry-run (conta, não escreve)
  python scripts/rename_migracao_etapas.py --apply --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # aplica no sandbox _dev (default)
  python scripts/rename_migracao_etapas.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd  # PROD
"""
import argparse
import os
import sys
import time
import uuid

PROD_SCHEMA = "monitoramento_sas"

RENAMES = [
    ("Pré-Working", "Pré-Working + Outputs"),
    ("Aprv. PR", "Aprv. PR + Validação Governança"),
    ("Artefatos de GOV.", "Aplicação de Grant"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="conecta e escreve no Databricks (default: dry-run, só conta)")
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas_dev"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID")
                     or os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
                    help="perfil do ~/.databrickscfg (OAuth/U2M); alternativa a DATABRICKS_HOST/TOKEN")
    ap.add_argument("--prod-confirm", action="store_true",
                    help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    args = ap.parse_args()

    if args.apply and args.schema == PROD_SCHEMA and not args.prod_confirm:
        ap.error(f"--apply contra PROD ('{args.catalog}.{args.schema}') requer --prod-confirm. "
                 f"Sem ele, use o sandbox (default --schema monitoramento_sas_dev).")
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_WAREHOUSE_ID")

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
    except ImportError:
        print("ERRO: databricks-sdk não instalado no venv ativo.", file=sys.stderr)
        sys.exit(1)

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"
    t_pipe = f"{fq}.sas_egp_pipeline"
    t_pipe_aud = f"{fq}.sas_pipeline_audit"

    def run(sql, want_rows=True):
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id,
            wait_timeout="50s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if (resp.status and resp.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:500]}")
        if not want_rows or not resp.result:
            return []
        cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest else []
        # Segue next_chunk_index: com INLINE só o PRIMEIRO chunk vem na resposta, e ler
        # apenas `data_array` truncava em silêncio — num rename que decide o que escrever
        # a partir do que leu, isso é rename parcial sem erro na tela.
        linhas, chunk = [], resp.result
        while chunk is not None:
            linhas.extend(chunk.data_array or [])
            nxt = getattr(chunk, "next_chunk_index", None)
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
        return [dict(zip(cols, row)) for row in linhas]

    def sql_lit(v):
        # ver nota em publish_to_databricks.sql_lit: no Spark '' concatena literais
        # e engole o apóstrofo; o escape correto é \' (e a contrabarra vem antes).
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"

    _tgt = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"== rename_migracao_etapas ==  destino: {fq}  [{_tgt}]  {'APPLY' if args.apply else 'DRY-RUN'}")

    total_candidatos = 0
    for old, new in RENAMES:
        rows = run(f"SELECT projeto FROM {t_pipe} WHERE etapa_migracao = {sql_lit(old)}")
        projetos = [r["projeto"] for r in rows]
        total_candidatos += len(projetos)
        print(f"  {old!r:22s} -> {new!r:38s} {len(projetos)} EGP(s)")

        if not args.apply or not projetos:
            continue

        run(f"UPDATE {t_pipe} SET etapa_migracao = {sql_lit(new)}, "
            f"updated_by = current_user(), updated_at = cast(current_timestamp() AS STRING) "
            f"WHERE etapa_migracao = {sql_lit(old)}", want_rows=False)

        vals = ", ".join(
            f"({sql_lit(uuid.uuid4().hex)}, {sql_lit(p)}, 'migracao', 'etapa_migracao', "
            f"{sql_lit(old)}, {sql_lit(new)}, current_user(), cast(current_timestamp() AS STRING))"
            for p in projetos
        )
        run(f"INSERT INTO {t_pipe_aud} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES {vals}", want_rows=False)
        print(f"    UPDATE + auditoria ok ({len(projetos)} linha(s)).")

    if not args.apply:
        print(f"\n[dry-run] {total_candidatos} EGP(s) no total seriam atualizados. "
              f"Rode com --apply (e --prod-confirm se for PROD) para aplicar.")
        return

    if total_candidatos == 0:
        print("\nnada a fazer (idempotente — rótulos antigos não encontrados).")
        return

    print(f"\nrename ok: {total_candidatos} EGP(s) atualizados em {t_pipe} + auditoria em {t_pipe_aud}.")
    check = run(f"SELECT etapa_migracao, count(*) AS n FROM {t_pipe} WHERE etapa_migracao IN "
                f"({', '.join(sql_lit(new) for _, new in RENAMES)}) GROUP BY etapa_migracao")
    print("  verificação (contagem nos rótulos novos):")
    for r in check:
        print(f"    {r.get('etapa_migracao')!r:38s} {r.get('n')}")


if __name__ == "__main__":
    main()

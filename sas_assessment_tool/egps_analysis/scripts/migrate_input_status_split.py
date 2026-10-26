#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migração ÚNICA: backfill de `status_humano` (5 valores legados) para as novas colunas
`etapa` (funil de ingestão, PIPELINE_INPUT) + `status` (progresso na etapa, STATUS_INPUT)
em `sas_inputs_monitor`. Ver `egps_analysis/app/backend/main.py` (PIPELINE_INPUT/
STATUS_INPUT/_eff_etapa/_eff_status_input) para o modelo novo.

Isto é DELIBERADAMENTE um script manual, não um self-heal automático (ao contrário do
ALTER TABLE ADD COLUMNS, que o app já faz sozinho via `_ensure_input_pipeline_cols`):
é um mapeamento de NEGÓCIO sobre milhares de linhas já editadas por analistas, então
precisa de revisão humana antes de rodar contra produção.

Mapeamento (confirmado com o usuário — não alterar sem revisitar a decisão):

  status_humano (+ legado)              -> etapa              | status
  ------------------------------------------------------------------------------
  A receber / A ingerir / Não recebido  -> A Receber           | A Iniciar
  Recebido / Em análise / Priorizado    -> Recebido            | Concluído
  Em ingestão                           -> Ingestão UAT        | Em Andamento
  Modernizado / Disponível              -> Modernizado         | Concluído
  Sanitizado / Sanitizada / Descartada  -> Modernizado         | Sanitizado
    / Descartado

Linhas sem status_humano (NULL/vazio) NÃO são tocadas — ficam com etapa/status NULL e
continuam caindo no fallback de `modernizada_auto` em tempo de leitura (mesmo
comportamento de hoje). `status_humano` NUNCA é apagado/sobrescrito — fica congelado
como histórico.

Idempotente: só atualiza linhas com `etapa IS NULL` — rodar de novo não faz nada.

Uso:
  cd egps_analysis
  python scripts/migrate_input_status_split.py --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # dry-run (conta, não escreve)
  python scripts/migrate_input_status_split.py --apply --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # aplica no sandbox _dev (default)
  python scripts/migrate_input_status_split.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd  # PROD
"""
import argparse
import os
import sys
import time

PROD_SCHEMA = "monitoramento_sas"

# CASE WHEN em ordem — cobre tanto os 5 valores atuais de STATUS_OPTIONS quanto os
# aliases legados que _eff_status() já normalizava na leitura (Disponível, Sanitizada,
# Descartada/Descartado, Em análise, A ingerir, Não recebido, Priorizado).
ETAPA_CASE = """CASE status_humano
  WHEN 'A receber' THEN 'A Receber'
  WHEN 'A ingerir' THEN 'A Receber'
  WHEN 'Não recebido' THEN 'A Receber'
  WHEN 'Recebido' THEN 'Recebido'
  WHEN 'Em análise' THEN 'Recebido'
  WHEN 'Priorizado' THEN 'Recebido'
  WHEN 'Em ingestão' THEN 'Ingestão UAT'
  WHEN 'Modernizado' THEN 'Modernizado'
  WHEN 'Disponível' THEN 'Modernizado'
  WHEN 'Sanitizado' THEN 'Modernizado'
  WHEN 'Sanitizada' THEN 'Modernizado'
  WHEN 'Descartada' THEN 'Modernizado'
  WHEN 'Descartado' THEN 'Modernizado'
  ELSE NULL
END"""

STATUS_CASE = """CASE status_humano
  WHEN 'A receber' THEN 'A Iniciar'
  WHEN 'A ingerir' THEN 'A Iniciar'
  WHEN 'Não recebido' THEN 'A Iniciar'
  WHEN 'Recebido' THEN 'Concluído'
  WHEN 'Em análise' THEN 'Concluído'
  WHEN 'Priorizado' THEN 'Concluído'
  WHEN 'Em ingestão' THEN 'Em Andamento'
  WHEN 'Modernizado' THEN 'Concluído'
  WHEN 'Disponível' THEN 'Concluído'
  WHEN 'Sanitizado' THEN 'Sanitizado'
  WHEN 'Sanitizada' THEN 'Sanitizado'
  WHEN 'Descartada' THEN 'Sanitizado'
  WHEN 'Descartado' THEN 'Sanitizado'
  ELSE NULL
END"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="conecta e escreve no Databricks (default: dry-run, só conta)")
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas_dev"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
                    help="perfil do ~/.databrickscfg (OAuth/U2M); alternativa a DATABRICKS_HOST/TOKEN")
    ap.add_argument("--prod-confirm", action="store_true",
                    help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    args = ap.parse_args()

    if args.apply and args.schema == PROD_SCHEMA and not args.prod_confirm:
        ap.error(f"--apply contra PROD ('{args.catalog}.{args.schema}') requer --prod-confirm. "
                 f"Sem ele, use o sandbox (default --schema monitoramento_sas_dev).")
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_DEFAULT_WAREHOUSE_ID")

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
    except ImportError:
        print("ERRO: databricks-sdk não instalado no venv ativo.", file=sys.stderr)
        sys.exit(1)

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"
    t_in = f"{fq}.sas_inputs_monitor"

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
        # apenas `data_array` truncava em silêncio — numa migração que decide o que
        # escrever a partir do que leu, isso é migração parcial sem erro na tela.
        linhas, chunk = [], resp.result
        while chunk is not None:
            linhas.extend(chunk.data_array or [])
            nxt = getattr(chunk, "next_chunk_index", None)
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
        return [dict(zip(cols, row)) for row in linhas]

    _tgt = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"== migrate_input_status_split ==  destino: {fq}  [{_tgt}]  {'APPLY' if args.apply else 'DRY-RUN'}")

    # 1. garante as colunas (mesmo self-heal do app — _ensure_input_pipeline_cols)
    try:
        run(f"SELECT etapa, status FROM {t_in} LIMIT 0", want_rows=False)
    except RuntimeError:
        if not args.apply:
            print("  [dry-run] colunas etapa/status ainda não existem — seriam criadas com --apply.")
        else:
            run(f"ALTER TABLE {t_in} ADD COLUMNS (etapa STRING, status STRING)", want_rows=False)
            print("  colunas etapa/status adicionadas (ALTER).")

    # 2. distribuição atual de status_humano (p/ conferência antes/depois)
    dist = run(f"SELECT status_humano, count(*) AS n FROM {t_in} GROUP BY status_humano ORDER BY n DESC")
    print("  distribuição atual de status_humano:")
    for r in dist:
        print(f"    {r.get('status_humano')!r:30s} {r.get('n')}")

    pend = run(f"SELECT count(*) AS n FROM {t_in} WHERE etapa IS NULL "
               f"AND status_humano IS NOT NULL AND status_humano <> ''")
    n_pend = int(pend[0]["n"]) if pend else 0
    print(f"  linhas elegíveis p/ backfill (etapa IS NULL AND status_humano preenchido): {n_pend}")

    unmapped = run(f"SELECT DISTINCT status_humano FROM {t_in} WHERE etapa IS NULL "
                    f"AND status_humano IS NOT NULL AND status_humano <> '' "
                    f"AND ({ETAPA_CASE}) IS NULL")
    if unmapped:
        print("  ATENÇÃO — valores de status_humano SEM mapeamento (ficarão sem etapa/status):")
        for r in unmapped:
            print(f"    {r.get('status_humano')!r}")

    if not args.apply:
        print("\n[dry-run] nada escrito. Rode com --apply para aplicar o backfill acima.")
        return

    run(f"UPDATE {t_in} SET etapa = ({ETAPA_CASE}), status = ({STATUS_CASE}) "
        f"WHERE etapa IS NULL AND status_humano IS NOT NULL AND status_humano <> ''",
        want_rows=False)

    depois = run(f"SELECT count(*) AS n FROM {t_in} WHERE etapa IS NOT NULL")
    print(f"  UPDATE ok. Linhas com etapa preenchida agora: {depois[0]['n'] if depois else '?'}")
    novadist = run(f"SELECT etapa, status, count(*) AS n FROM {t_in} "
                    f"GROUP BY etapa, status ORDER BY etapa, status")
    print("  distribuição nova (etapa, status):")
    for r in novadist:
        print(f"    {r.get('etapa')!r:22s} {r.get('status')!r:14s} {r.get('n')}")


if __name__ == "__main__":
    main()

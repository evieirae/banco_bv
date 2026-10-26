#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill ÚNICO: marca `modernizado_bv='true'` em `sas_inputs_preworking` para inputs que
já estão modernizados fora da nossa esteira — a coluna "Modernizados (BV)" do gráfico
"Inputs sanitizados/modernizados (BV)/recebidos por semana" (aba Gestão → Gestão de
Inputs) nasce vazia (campo manual novo, 2026-08) e sem isso ficaria zerada até alguém
marcar input por input pela UI.

Critério (mesmo do endpoint `GET /api/inputs-recebidos-serie`, ver
`egps_analysis/app/backend/main.py`):
  - universo = indi_deps (frontier de hoje, mesmo cômputo do app — fecho transitivo de
    dependências, não é um WHERE simples, por isso este é um script e não uma query solta);
  - etapa efetiva = 'Modernizado' E status efetivo <> 'Sanitizado' (`_eff_etapa`/
    `_eff_status_input`);
  - EXCLUI quem já tem `recebido='true'` no checklist de pré-working — esses passaram pela
    NOSSA esteira e já contam certo em "Recebidos"; marcá-los como BV também violaria a
    exclusividade mútua das 3 colunas do gráfico.
  - EXCLUI quem já tem `modernizado_bv='true'` (idempotente — rodar de novo não retrabalha).

`data_modernizado_bv` fica em branco de propósito: não existe trilha de auditoria
histórica de quando `modernizada_auto` virou 'Disponível' (é sobrescrito a cada publish
sem gravar a transição), então não há data confiável pra atribuir — os itens caem no
bucket "pré" do gráfico até alguém editar a data manualmente pelo InputDetailPanel (spec
combinada com o usuário, 2026-08-19).

Escreve via MERGE (upsert, em lotes) + 1 linha de auditoria por input em
`sas_inputs_audit` (campo='preworking.modernizado_bv'), mesmo padrão do
PATCH /api/inputs/preworking. Idempotente.

Uso (rodar de dentro de egps_analysis/app, venv do backend ativo):
  cd egps_analysis/app
  ../venv/bin/python ../scripts/backfill_modernizado_bv.py --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # dry-run (conta, não escreve)
  ../venv/bin/python ../scripts/backfill_modernizado_bv.py --apply --profile bv \\
      --warehouse-id 5922c26f81f1bbdd                    # aplica no sandbox _dev (default)
  ../venv/bin/python ../scripts/backfill_modernizado_bv.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd  # PROD
"""
import argparse
import os
import sys

PROD_SCHEMA = "monitoramento_sas"
BATCH_SIZE = 300  # linhas por MERGE/INSERT — evita statement gigante em bases grandes


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

    # main.py lê PUBLISH_CATALOG/PUBLISH_SCHEMA/DATABRICKS_WAREHOUSE_ID/
    # DATABRICKS_CONFIG_PROFILE do ambiente NO IMPORT (nível de módulo) — precisam estar
    # setados ANTES do import abaixo, não dá pra passar como parâmetro depois.
    os.environ["PUBLISH_CATALOG"] = args.catalog
    os.environ["PUBLISH_SCHEMA"] = args.schema
    os.environ["DATABRICKS_WAREHOUSE_ID"] = args.warehouse_id
    if args.profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile

    backend_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "app", "backend"))
    sys.path.insert(0, backend_dir)
    import main as m  # noqa: E402  (import tardio de propósito, ver acima)

    assert m.CATALOG == args.catalog and m.SCHEMA == args.schema, (
        "main.py não pegou o catalog/schema pedido — confira import tardio / cache de módulo.")

    _tgt = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"== backfill_modernizado_bv ==  destino: {m.FQ}  [{_tgt}]  {'APPLY' if args.apply else 'DRY-RUN'}")

    m._ensure_preworking_table()

    frontier, _base = m._frontier_egps("indi_deps", [])
    print(f"  frontier indi_deps: {len(frontier)} EGPs")
    if not frontier:
        print("  frontier vazio — nada a fazer.")
        return
    finl = ", ".join(m.sql_lit(p) for p in frontier)
    universe_where = (f"chave_canonica IN (SELECT DISTINCT chave_canonica FROM {m.T_EGP} "
                      f"WHERE projeto IN ({finl}))")
    eff_et = m._eff_etapa()
    eff_st = m._eff_status_input()

    rows = m.run_sql(
        f"WITH universo AS (SELECT chave_canonica FROM {m.T_IN} i "
        f"  WHERE {universe_where} AND {eff_et} = 'Modernizado' AND {eff_st} <> 'Sanitizado') "
        f"SELECT u.chave_canonica, p.recebido, p.modernizado_bv FROM universo u "
        f"LEFT JOIN {m.T_PWK} p ON p.chave_canonica = u.chave_canonica")

    ja_recebido = [r for r in rows if (r.get("recebido") or "") == "true"]
    ja_bv = [r for r in rows if (r.get("modernizado_bv") or "") == "true"]
    candidatos = [r["chave_canonica"] for r in rows
                  if (r.get("recebido") or "") != "true" and (r.get("modernizado_bv") or "") != "true"]

    print(f"  total 'Modernizado, não Sanitizado' no universo indi_deps: {len(rows)}")
    print(f"    já com recebido=true (ficam como Recebidos, não tocados): {len(ja_recebido)}")
    print(f"    já com modernizado_bv=true (idempotente, não re-tocados): {len(ja_bv)}")
    print(f"    CANDIDATOS a marcar modernizado_bv=true: {len(candidatos)}")

    if not args.apply:
        print("\n[dry-run] nada escrito. Rode com --apply (e --prod-confirm se for PROD) para aplicar.")
        return
    if not candidatos:
        print("\nnada a fazer.")
        return

    for i in range(0, len(candidatos), BATCH_SIZE):
        batch = candidatos[i:i + BATCH_SIZE]
        vals = ", ".join(f"({m.sql_lit(k)})" for k in batch)
        m.run_sql(
            f"MERGE INTO {m.T_PWK} t USING (SELECT chave_canonica FROM (VALUES {vals}) "
            f"AS v(chave_canonica)) s ON t.chave_canonica = s.chave_canonica "
            f"WHEN MATCHED THEN UPDATE SET t.modernizado_bv = 'true', t.updated_by = current_user(), "
            f"t.updated_at = cast(current_timestamp() AS STRING) "
            f"WHEN NOT MATCHED THEN INSERT (chave_canonica, modernizado_bv, updated_by, updated_at, iniciado_em) "
            f"VALUES (s.chave_canonica, 'true', current_user(), cast(current_timestamp() AS STRING), "
            f"cast(current_timestamp() AS STRING))", want_rows=False)
        m.run_sql(
            f"INSERT INTO {m.T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, updated_by, updated_at) "
            f"SELECT chave_canonica, 'preworking.modernizado_bv', NULL, 'true', current_user(), current_timestamp() "
            f"FROM (VALUES {vals}) AS v(chave_canonica)", want_rows=False)
        print(f"  lote {i // BATCH_SIZE + 1}: {len(batch)} linhas (MERGE + audit) ok.")

    print(f"\nMERGE+audit ok: {len(candidatos)} linhas de {m.T_PWK} atualizadas/inseridas em "
          f"{(len(candidatos) + BATCH_SIZE - 1) // BATCH_SIZE} lote(s).")
    check = m.run_sql(f"SELECT count(*) AS n FROM {m.T_PWK} WHERE modernizado_bv = 'true'")
    print(f"verificação: total com modernizado_bv='true' em {m.T_PWK} agora = {check[0]['n']}")


if __name__ == "__main__":
    main()

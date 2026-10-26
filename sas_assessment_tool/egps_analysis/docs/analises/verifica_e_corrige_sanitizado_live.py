#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Revisão dos inputs marcados "Sanitizado" em BV_Migracao_SAS_Acao_Sanitizar_Desvincular_
2026-08-21.csv contra o inventário LIVE de produção (bv_dev_db.monitoramento_sas,
READ-ONLY — nenhum UPDATE/MERGE aqui).

Por que revisar: a análise offline (safra, 2026-08-13) que gerou os tiers é uma fotografia
de `text_egps/`. Desde então o escopo (sas_escopo.ativo) pode ter mudado — um EGP que
era o único leitor de um input pode ter sido despriorizado. "Sanitizado" é status GLOBAL
do input (afeta a leitura de qualquer EGP, inclusive um reativado no futuro); "Desvincular"
é só daquele par. Então, quando o único leitor de um input já não está mais ativo, é
mais seguro rebaixar a ação de Sanitizado -> Desvincular: o efeito prático hoje é igual
(nenhum EGP ativo depende do input), mas não fica uma marca "Sanitizado" cuja validade
não foi confirmada sob um leitor ativo — se o EGP for reativado, a ação correta reaparece
como uma decisão pendente em vez de uma marca esquecida.

Achados nesta rodada (2026-08-21, ver saída completa do script):
  - 106/141 inputs sem divergência -> mantém Sanitizado.
  - 3/141 já têm vínculo quebrado manual para o único leitor -> mantém Sanitizado
    (reforça a decisão já tomada por alguém, não precisa contradizer).
  - 1/141 (LUCAS.FERIADOS, calendário) com leitores a menos que a análise original,
    mas é recurso compartilhado -> mantém Sanitizado.
  - 31/141: o único leitor listado (8 EGPs distintos, todos com sas_escopo.ativo=false
    hoje) está despriorizado -> REBAIXADO para Desvincular.

Uso:
  cd egps_analysis
  venv/bin/python3 docs/analises/verifica_e_corrige_sanitizado_live.py \\
      --profile bv --warehouse-id 5922c26f81f1bbdd
  # escreve BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv corrigido no lugar
  # (faz backup do original em .bak antes de sobrescrever)
"""
import argparse
import csv
import os
import sys
import shutil
import time

_HERE_PUB = os.path.dirname(os.path.abspath(__file__))
_EGPS_PUB = os.path.dirname(os.path.dirname(_HERE_PUB))
if _EGPS_PUB not in sys.path:
    sys.path.insert(0, _EGPS_PUB)
import publish_to_databricks as _pub                       # noqa: E402
BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE, "BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv")


# Helper CANÔNICO (publish_to_databricks.sql_lit), não uma cópia local: ele escapa a
# contrabarra ANTES da aspa. As cópias locais só escapavam a aspa, e este corpus é
# cheio de caminho UNC/Windows (`N:\`, `\\bvnet\global\...`) que chega ao SQL via
# `observacao`/`comentario` escritos por analista. Em Spark SQL a `\` é escape dentro
# do literal: valor terminado em `\` escapa a aspa de fechamento e quebra (ou desloca)
# o statement; `\g` & cia corrompem o texto gravado em silêncio.
lit = _pub.sql_lit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_PATH)
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas"),
                     help="autoritativo = PROD por padrão, é só leitura (SELECT)")
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    ap.add_argument("--write", action="store_true",
                     help="sobrescreve o CSV com as correções (default: só relata)")
    args = ap.parse_args()
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_DEFAULT_WAREHOUSE_ID")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"

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
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:800]}")
        if not want_rows or not resp.result or not resp.result.data_array:
            return []
        cols = [c.name for c in resp.manifest.schema.columns]
        return [dict(zip(cols, row)) for row in resp.result.data_array]

    with open(args.csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
        fieldnames = list(rows[0].keys())

    sanit_idx = [i for i, r in enumerate(rows) if r["acao"] == "Sanitizado"]
    chaves = sorted({rows[i]["chave_canonica"] for i in sanit_idx})
    in_list = ",".join(lit(c) for c in chaves)

    egp_rows = run(f"SELECT chave_canonica, projeto FROM {fq}.sas_egp_inputs "
                    f"WHERE chave_canonica IN ({in_list}) AND escopo_indi = true")
    live_leitores = {}
    for r in egp_rows:
        live_leitores.setdefault(r["chave_canonica"], set()).add(r["projeto"])

    egps_envolvidos = sorted({rows[i]["egp"] for i in sanit_idx})
    in_egps = ",".join(lit(e) for e in egps_envolvidos)
    escopo_rows = run(f"SELECT projeto, ativo FROM {fq}.sas_escopo WHERE projeto IN ({in_egps})")
    ativo_por_egp = {r["projeto"]: str(r["ativo"]).lower() == "true" for r in escopo_rows}

    rebaixados, mantidos = [], []
    for i in sanit_idx:
        r = rows[i]
        if r["classe"] == "calendario":
            mantidos.append(r["input"])
            continue
        live_qtd = len(live_leitores.get(r["chave_canonica"], set()))
        egp_ativo = ativo_por_egp.get(r["egp"])
        if live_qtd == 0 and egp_ativo is False:
            rebaixados.append(i)
        else:
            mantidos.append(r["input"])

    print(f"Sanitizado no CSV: {len(sanit_idx)} linhas ({len(chaves)} inputs distintos)")
    print(f"  mantidos Sanitizado: {len(mantidos)}")
    print(f"  rebaixados p/ Desvincular (único leitor despriorizado, ativo=false): {len(rebaixados)}")
    for i in rebaixados:
        print(f"    - {rows[i]['input']}  (leitor: {rows[i]['egp']})")

    if rebaixados and args.write:
        for i in rebaixados:
            r = rows[i]
            r["acao"] = "Desvincular"
            r["comentario"] = (
                f"Revisão 2026-08-21 contra o inventário live: era Sanitizado (único leitor "
                f"em {r['estudo_origem']}), mas o EGP leitor ({r['egp']}) está despriorizado "
                f"(sas_escopo.ativo=false) hoje — nenhum EGP ativo depende deste input. "
                f"Rebaixado para Desvincular: mesmo efeito prático agora, mas não deixa uma "
                f"marca 'Sanitizado' global sem confirmação sob um leitor ativo — se "
                f"{r['egp']} for reativado, a pendência reaparece em vez de ficar escondida.")
        backup = args.csv + ".bak"
        shutil.copy(args.csv, backup)
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            wtr = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            wtr.writeheader()
            wtr.writerows(rows)
        print(f"\nCSV corrigido gravado em {args.csv} (backup em {backup})")
    elif rebaixados:
        print("\n(--write não passado: nada foi alterado no CSV; rode de novo com --write "
              "para aplicar o rebaixamento)")


if __name__ == "__main__":
    main()

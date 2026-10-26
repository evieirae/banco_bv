#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dependências "sem produtor" no app que APARECEM sendo escritas nos logs do SAS.

O app marca como `SAS/Local (externo)` — "dep. produtor ausente" — toda tabela SAS/Local que
nenhum EGP do corpus cria. São 3.839 pendentes (937 no escopo Indicium), e quem lê espera que
venham de ingestão. Mas o corpus de `.egp` que temos é parcial: 2.544 dos 3.052 projetos que
aparecem nos logs não estão nele. Este script cruza as duas pontas e responde: quais dessas
tabelas têm produtor, só não no nosso corpus?

Isso muda o TIPO de trabalho — de "pedir ingestão ao BV" para "pedir o .egp produtor" ou
"converter o produtor" —, e é por isso que sai em CSV para conversa com o BV, não em número
solto.

Fontes (só leitura): `monitoramento_sas.sas_inputs_monitor` (o que falta, com a régua
`_modern` do app) e `bv_migration_sas.lineage_sas_statements` (target_table por projeto/task,
derivada de log). Corpus local = `received_egps/**/*.egp` + `text_egps/*.txt`.

LIMITES, que entram no CSV para ninguém confundir evidência com garantia:
  - a janela do corpus de logs é curta (2025-07-31 a 2025-10-27): ausência aqui não prova
    que a tabela não tenha produtor;
  - o casamento é por NOME (`LIB.TABELA`), não por path — homônimo em lib diferente pode
    gerar falso-positivo, e a confirmação é ver o path do libname naquele projeto;
  - "aparece escrevendo no log" prova que existia e rodava naquela janela, não que ainda roda.

Uso:
    cd egps_analysis && venv/bin/python docs/analises/produtores_no_log.py
"""
import argparse
import collections
import csv
import datetime
import glob
import os
import re
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "..", "..")
MON = "bv_dev_db.monitoramento_sas"
LOG = "bv_dev_db.bv_migration_sas"


def _sql(w, wid, stmt):
    from databricks.sdk.service.sql import StatementState, Disposition, Format
    r = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=wid, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(4)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise SystemExit("SQL falhou: " + str(r.status.error)[:300])
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def corpus_local():
    """Nomes de EGP que TEMOS (normalizados): binário recebido ou extraído."""
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper().replace(".EGP", ""))
    recv = {norm(os.path.basename(p)[:-4])
            for p in glob.glob(os.path.join(BASE, "received_egps", "**", "*.egp"), recursive=True)}
    txt = {norm(os.path.basename(p)[:-4].split("__", 1)[-1])
           for p in glob.glob(os.path.join(BASE, "text_egps", "*.txt"))}
    return (recv | txt) - {""}, norm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="bv")
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID",
                                                            "5922c26f81f1bbdd"))
    args = ap.parse_args()
    sys.path.insert(0, os.path.join(BASE, "app", "backend"))
    import input_state as S                        # régua `_modern` do app, não uma cópia
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=args.profile)
    q = lambda s: _sql(w, args.warehouse_id, s)

    falta = q(f"""SELECT upper(artifact) tab, escopo_indi, qtd_projetos, etapa, status
    FROM {MON}.sas_inputs_monitor
    WHERE orfao = false AND categoria = 'tabela' AND origem LIKE 'SAS/Local%externo%'
      AND NOT {S._modern()}""")
    print(f"dependências sem produtor e pendentes: {len(falta)} "
          f"({sum(1 for r in falta if str(r['escopo_indi']).lower() == 'true')} no escopo)")

    alvo = sorted({r["tab"] for r in falta})
    pares = []
    for i in range(0, len(alvo), 400):            # IN em lotes: a lista inteira estoura o SQL
        lista = ", ".join("'" + t.replace("'", "\\'") + "'" for t in alvo[i:i + 400])
        # `lineage_sas_statements` não tem coluna de data; a data vem do NOME do log
        # (`SASApp_WorkspaceServer_2025-08-01_srv-...`), que é o que permite dizer "rodou em
        # N dias" sem fazer join com as 135M linhas de `log_process`.
        dia = r"regexp_extract(log_file, '([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)"
        pares += q(f"""SELECT upper(trim(target_table)) tab, project_name,
          count(DISTINCT log_file) logs, count(DISTINCT {dia}) dias, max({dia}) ultima
        FROM {LOG}.lineage_sas_statements
        WHERE upper(trim(target_table)) IN ({lista})
        GROUP BY upper(trim(target_table)), project_name""")
    corpus, norm = corpus_local()
    fora = [p for p in pares if norm(p["project_name"]) not in corpus]
    por_tab = collections.defaultdict(list)
    for p in fora:
        por_tab[p["tab"]].append(p)
    meta = {r["tab"]: r for r in falta}

    linhas = []
    for tab, ps in por_tab.items():
        m = meta.get(tab, {})
        ps.sort(key=lambda p: -int(p["dias"] or 0))
        linhas.append({
            "tabela": tab,
            "consumidores_no_app": int(m.get("qtd_projetos") or 0),
            "no_escopo_indi": str(m.get("escopo_indi")).lower() == "true",
            "etapa_no_app": m.get("etapa") or "",
            "status_no_app": m.get("status") or "",
            "n_produtores_no_log": len(ps),
            "produtor_mais_ativo": ps[0]["project_name"].strip("'"),
            "dias_de_execucao": int(ps[0]["dias"] or 0),
            "ultima_execucao": str(ps[0]["ultima"])[:10],
            "outros_produtores": " | ".join(p["project_name"].strip("'") for p in ps[1:6]),
            "obs": "nome sem path: confirmar libname; janela do log 2025-07-31..2025-10-27",
        })
    linhas.sort(key=lambda r: (-r["consumidores_no_app"], r["tabela"]))
    hoje = datetime.date.today().isoformat()
    out = os.path.join(AQUI, f"BV_Migracao_SAS_Produtores_No_Log_{hoje}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        wr.writeheader()
        wr.writerows(linhas)
    esc = [r for r in linhas if r["no_escopo_indi"]]
    print(f"\ntabelas com produtor FORA do corpus: {len(linhas)}  (escopo Indicium: {len(esc)})")
    print(f"  consumidores no app somados: {sum(r['consumidores_no_app'] for r in linhas)}")
    print("\n  top 8 por consumidores:")
    for r in linhas[:8]:
        e = "ESCOPO" if r["no_escopo_indi"] else "      "
        print(f"   {e} {r['consumidores_no_app']:>3} cons · {r['tabela'][:38]:38s} <- "
              f"{r['produtor_mais_ativo'][:34]} ({r['dias_de_execucao']}d)")
    print(f"\n-> {out}")


if __name__ == "__main__":
    raise SystemExit(main())

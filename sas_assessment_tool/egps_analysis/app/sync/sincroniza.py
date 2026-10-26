# -*- coding: utf-8 -*-
"""Sincronização Databricks -> Postgres (ADR 0005, Fase 1). Roda como tarefa ECS agendada.

Uso: python -m sync.sincroniza
Ambiente: DATABRICKS_HOST / DATABRICKS_TOKEN (token pessoal de quem cuida do app, temporário
até tudo sair do Databricks; o WorkspaceClient também aceita DATABRICKS_CLIENT_ID/SECRET de uma
conta de serviço), DATABRICKS_WAREHOUSE_ID, ORIGEM_SCHEMA (padrão bv_dev_db.monitoramento_sas),
PG_DSN ou PGHOST/PGUSER/PGPASSWORD/PGDATABASE, PG_PAPEL (sincronizador na AWS),
VERSAO_CODIGO (opcional).
Sai com código 1 e a linha "[sync] FALHA" no log em qualquer erro — o alarme do CloudWatch
filtra essa linha; o app mostra a faixa vermelha quando a última sincronização boa envelhece.
"""
import os
import sys
import traceback

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg import sql

from . import carrega, espelho, leitor, mapeamento as mp, retrato

FUSOS_UTC = ("Etc/UTC", "UTC", "Z", "+00:00")


def le_tudo(w, warehouse, origem):
    """Uma leitura por tabela. As 5 do 1a também são espelhadas: lê as colunas do espelho
    (que incluem as do de-para) e as duas partes usam a mesma leitura."""
    fuso = leitor.le_tabela(w, warehouse, "(SELECT current_timezone() AS fuso)", ["fuso"])[0]["fuso"]
    if fuso not in FUSOS_UTC:   # CAST(timestamp AS STRING) sai no fuso da sessão
        raise RuntimeError(f"sessão do Databricks em {fuso}, não UTC: os instantes sairiam deslocados")
    linhas = {}
    for t in dict.fromkeys([*espelho.TABELAS, *mp.ORIGEM]):
        if t in espelho.TABELAS:
            faltam = set(mp.ORIGEM.get(t, ())) - set(espelho.colunas(t))
            if faltam:
                raise RuntimeError(f"{t}: o de-para lê colunas fora do espelho: {sorted(faltam)}")
            linhas[t] = leitor.le_tabela(w, warehouse, f"{origem}.{t}", espelho.colunas(t),
                                         espelho.selecao(t))
        else:
            linhas[t] = leitor.le_tabela(w, warehouse, f"{origem}.{t}", mp.ORIGEM[t])
    return linhas


def main():
    origem = os.environ.get("ORIGEM_SCHEMA", "bv_dev_db.monitoramento_sas")
    try:
        warehouse = os.environ["DATABRICKS_WAREHOUSE_ID"]
        w = WorkspaceClient()
        linhas = le_tudo(w, warehouse, origem)
        with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
            # Entra como mestre (girado pela plataforma) e baixa para o papel da carga.
            papel = os.environ.get("PG_PAPEL")
            if papel:
                conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(papel)))
                conn.commit()
            resumo = carrega.carrega(conn, retrato.monta(linhas), os.environ.get("VERSAO_CODIGO"))
        print(f"[sync] OK {resumo}", flush=True)
    except Exception as e:  # noqa: BLE001 — qualquer falha tem de virar alarme
        print(f"[sync] FALHA {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normaliza grafias divergentes de sas_egp_pipeline.responsavel_bv (2026-09-15).

Duas pessoas estavam gravadas com duas grafias, o que as separaria em duas
"sub-áreas" distintas no app: "Leticia" (2 EGPs) é a mesma pessoa que
"Leticia Domingos Duarte" (61), e "Igor Brito_Riscos" (7) carregava a área
no próprio nome. Idempotente: rodar de novo não muda nada.

    python egps_analysis/scripts/normaliza_responsavel_bv.py            # só mostra
    python egps_analysis/scripts/normaliza_responsavel_bv.py --apply    # grava
"""
import argparse

from databricks.sdk import WorkspaceClient

TABELA = "bv_dev_db.monitoramento_sas.sas_egp_pipeline"
WAREHOUSE = "5922c26f81f1bbdd"

# (grafia errada, grafia canônica)
RENOMES = [
    ("Leticia", "Leticia Domingos Duarte"),
    ("Igor Brito_Riscos", "Igor Brito"),
]


def lit(v):
    """Literal SQL escapado (mesma regra de sql_lit em app/backend/main.py)."""
    # ver nota em publish_to_databricks.sql_lit: no Spark '' concatena literais e
    # engole o apóstrofo (D'Ávila viraria DÁvila); o escape correto é \'.
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def consulta(w, sql):
    """Executa e devolve TODAS as linhas.

    Dois cuidados que a versão anterior não tinha, e que num script que escreve em prod
    a partir do que lê viram escrita parcial silenciosa:
      - espera o statement terminar (`wait_timeout` pode devolver ainda PENDING/RUNNING)
        e confere o estado, em vez de ler o resultado de um statement que talvez tenha
        falhado;
      - segue `next_chunk_index` — com INLINE só o PRIMEIRO chunk vem na resposta.
    """
    import time

    from databricks.sdk.service.sql import StatementState

    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE, wait_timeout="50s")
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "?"
        raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:400]}")
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    return linhas


def distribuicao(w):
    return consulta(w, f"""SELECT responsavel_bv, count(*) AS n FROM {TABELA}
        WHERE responsavel_bv IS NOT NULL AND trim(responsavel_bv) <> ''
        GROUP BY 1 ORDER BY 2 DESC""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava (sem isso, só mostra)")
    ap.add_argument("--profile", default="bv")
    args = ap.parse_args()

    w = WorkspaceClient(profile=args.profile)

    print("ANTES:")
    for nome, n in distribuicao(w):
        print(f"  {n:>4}  {nome}")

    for errado, certo in RENOMES:
        # via lit(): hoje os valores são constantes do módulo, mas um nome com apóstrofo
        # (D'Ávila) quebraria a query montada por f-string crua.
        sql = (f"UPDATE {TABELA} SET responsavel_bv = {lit(certo)} "
               f"WHERE trim(responsavel_bv) = {lit(errado)}")
        if args.apply:
            consulta(w, sql)
            print(f"aplicado: {errado!r} -> {certo!r}")
        else:
            print(f"[dry-run] {sql}")

    if args.apply:
        print("DEPOIS:")
        for nome, n in distribuicao(w):
            print(f"  {n:>4}  {nome}")


if __name__ == "__main__":
    main()

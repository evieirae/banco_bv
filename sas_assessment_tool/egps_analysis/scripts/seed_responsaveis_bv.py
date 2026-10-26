#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Popula o cadastro sas_responsaveis_bv (Responsável BV -> sub-área interna do BV).

A sub-área é atributo da PESSOA: o EGP a herda do seu `responsavel_bv` (texto livre)
pela chave `nome_key` (nome normalizado). Este seed traz os responsáveis que já
aparecem em sas_egp_pipeline em 2026-09-15, com as áreas informadas pelo BV.

Idempotente por nome_key (não duplica linhas), mas NÃO é inócuo: o MERGE **sobrescreve**
a sub-área com o valor desta lista e força `ativo = true`. Ou seja, rodar de novo desfaz
edições feitas na tela (Gestão → Responsáveis BV) e **reativa** quem foi desativado lá.
Depois do seed inicial, a tela é a fonte da verdade — só rode isto de novo para semear um
ambiente novo ou para reverter deliberadamente ao estado desta lista.

    python egps_analysis/scripts/seed_responsaveis_bv.py            # só mostra
    python egps_analysis/scripts/seed_responsaveis_bv.py --apply    # grava
"""
import argparse
import re
import unicodedata

from databricks.sdk import WorkspaceClient

CATALOGO = "bv_dev_db"
SCHEMA_PROD = "monitoramento_sas"          # app de produção
SCHEMA_DEV = "monitoramento_sas_dev"       # app dev + `local_app.sh`
WAREHOUSE = "5922c26f81f1bbdd"

# (nome como gravado nos EGPs, sub-área). "Não localizado" fica sem sub-área de
# propósito: é um marcador do BV, não uma pessoa — aparece como "Sem sub-área".
RESPONSAVEIS = [
    ("Adamor Luz", "Digital"),
    ("Rafael Vasconcelos Ribeiro", "Digital"),
    ("Carolina Matos", "Operações"),
    ("Daniel Vitor", "Operações"),
    ("cynthia", "Operações"),
    ("Cleber William De Jesus Saure", "MIS"),
    ("Cristiano", "MIS"),
    ("Joao Carneiro", "Estratégia - cartões"),
    ("Leticia Domingos Duarte", "Estratégia - rodas"),
    ("Igor Brito", "Riscos"),
    ("Não localizado", ""),
]

DDL = """CREATE TABLE IF NOT EXISTS {tabela} (nome_key STRING, nome STRING,
  subarea STRING, ativo BOOLEAN, created_by STRING, created_at STRING,
  updated_by STRING, updated_at STRING) USING DELTA"""


# 3 cópias desta regra, todas com teste: _norm_nome_bv (app/backend/main.py), normNome
# (app/frontend/src/subareas.ts) e esta. Mudou numa, muda nas três.
_ESPACOS = re.compile(r"[\s\u0085\u001c-\u001f\u200b\ufeff]+")


def norm_nome_bv(nome):
    r"""Chave canônica do nome. Invisíveis (BOM do Excel, NEL/separadores de mainframe,
    zero-width) são listados à mão porque Python e JS os classificam diferente; marca é
    filtrada por CATEGORIA (= \p{M} do JS), não por combining() != 0."""
    s = unicodedata.normalize("NFKD", (nome or "").lower())
    s = "".join(c for c in s if not unicodedata.category(c).startswith("M"))
    return _ESPACOS.sub(" ", s).strip()


def lit(v):
    if v is None or v == "":
        return "NULL"
    # ver nota em publish_to_databricks.sql_lit: no Spark '' concatena literais e
    # engole o apóstrofo (D'Ávila viraria DÁvila); o escape correto é \'.
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def executa(w, sql):
    """Executa e devolve TODAS as linhas.

    Antes: lia o resultado sem esperar o statement terminar nem conferir o estado (com
    `wait_timeout` ele pode voltar PENDING/RUNNING, ou FAILED) e ficava só no PRIMEIRO
    chunk inline. Num script de seed que grava em prod, os dois viram MERGE parcial sem
    erro nenhum na tela.
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


def merge_sql(tabela, nome, subarea):
    key = norm_nome_bv(nome)
    return (
        f"MERGE INTO {tabela} t USING (SELECT {lit(key)} AS nome_key) s "
        f"ON t.nome_key = s.nome_key "
        f"WHEN MATCHED THEN UPDATE SET t.nome = {lit(nome)}, t.subarea = {lit(subarea)}, "
        f"t.ativo = true, t.updated_by = current_user(), "
        f"t.updated_at = cast(current_timestamp() AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (nome_key, nome, subarea, ativo, created_by, "
        f"created_at, updated_by, updated_at) VALUES ({lit(key)}, {lit(nome)}, "
        f"{lit(subarea)}, true, current_user(), cast(current_timestamp() AS STRING), "
        f"current_user(), cast(current_timestamp() AS STRING))")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava (sem isso, só mostra)")
    ap.add_argument("--profile", default="bv")
    ap.add_argument("--schema", default=SCHEMA_PROD,
                    help=f"schema alvo ({SCHEMA_PROD} = prod, {SCHEMA_DEV} = dev/local)")
    args = ap.parse_args()

    if not args.apply:
        for nome, sub in RESPONSAVEIS:
            print(f"[dry-run] {norm_nome_bv(nome):<32} {nome:<32} {sub or '—'}")
        return

    tabela = f"{CATALOGO}.{args.schema}.sas_responsaveis_bv"
    w = WorkspaceClient(profile=args.profile)
    executa(w, DDL.format(tabela=tabela))
    for nome, sub in RESPONSAVEIS:
        executa(w, merge_sql(tabela, nome, sub))
        print(f"ok  {nome:<32} {sub or '—'}")

    print(f"\nCADASTRO ({tabela}):")
    for row in executa(w, f"SELECT nome, subarea, ativo FROM {tabela} ORDER BY subarea, nome"):
        print(f"  {row[0]:<32} {row[1] or '—':<22} ativo={row[2]}")


if __name__ == "__main__":
    main()

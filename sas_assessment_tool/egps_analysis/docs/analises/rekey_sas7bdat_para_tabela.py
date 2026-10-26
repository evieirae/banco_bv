#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-key do estado humano quando um `.sas7bdat` deixa de ser `arquivo` e vira `tabela`.

Contexto: `orchestrator_inventory._sas7bdat_as_libname_table()` converte
`file_in '<membro>.sas7bdat'` em `table_in 'LIB.MEMBRO'` quando o diretório do arquivo tem
LIBNAME do projeto. Isso MUDA a chave canônica:

    arquivo::EMPILHA_RENEG_FINAL_202406.SAS7BDAT  ->  tabela::GTAVARES.EMPILHA_RENEG_FINAL_202406

O MERGE do publish preserva as colunas humanas POR CHAVE (`sas_inputs_monitor`:
etapa/status/responsavel/observacao/updated_*; `sas_egp_input_link`: link_broken). Chave nova
= linha nova, então sem este re-key a edição humana fica órfã na chave velha.

Também reporta o estado humano que cai pelo guard de macro
(`publish_to_databricks.is_macro_artifact`): esses artefatos deixam de existir como input, e
o estado deles não tem para onde ir — some de propósito, mas nunca em silêncio.

READ-ONLY por padrão: imprime o relatório e escreve o SQL em docs/analises/. Só escreve em
banco com --apply, e contra o schema de PROD só com --i-know-its-prod.

Uso:
    egps_analysis/venv/bin/python docs/analises/rekey_sas7bdat_para_tabela.py
    ... --apply --schema monitoramento_sas_dev
"""
import argparse
import collections
import csv
import datetime
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_EGPS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _EGPS)

import publish_to_databricks as pub                       # noqa: E402

R06 = os.path.join(_EGPS, "06_prontidao_tabela.csv")
LABEL = ".sas7bdat sob LIBNAME"
PROD_SCHEMA = "monitoramento_sas"
WID = "5922c26f81f1bbdd"
STAMP = datetime.date.today().isoformat()
OUT_SQL = os.path.join(_HERE, f"rekey_sas7bdat_{STAMP}.sql")

HUMAN_COLS = ("etapa", "status", "responsavel", "observacao", "updated_by", "updated_at")


# Helper CANÔNICO (publish_to_databricks.sql_lit), não uma cópia: ele escapa a
# contrabarra ANTES da aspa. As cópias locais só escapavam a aspa, e este corpus é
# cheio de caminho UNC/Windows (`N:\`, `\\bvnet\global\...`) que entra em SQL via
# `observacao` escrita por analista. Em Spark SQL a `\` é escape dentro do literal:
# um valor terminado em `\` escapa a aspa de fechamento e quebra (ou desloca) o
# statement; `\g` & cia corrompem o texto gravado em silêncio.
sql_lit = pub.sql_lit


# --------------------------------------------------------------- mapa a partir do 06
def build_map():
    """(mapa old->new, ambiguos, por_projeto). Chave velha = arquivo::<MEMBRO>.SAS7BDAT —
    é como o publish canonizava o `file_in` (basename em UPPER)."""
    novo_por_velho = collections.defaultdict(set)
    projs = collections.defaultdict(set)
    with open(R06, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("category") != "table_in" or LABEL not in (r.get("source_type") or ""):
                continue
            art = (r.get("artifact") or "").strip().upper()
            if "." not in art:
                continue
            membro = art.rsplit(".", 1)[-1]
            velho = f"arquivo::{membro}.SAS7BDAT"
            novo = f"tabela::{art}"
            novo_por_velho[velho].add(novo)
            projs[velho].add(r.get("project"))
    mapa = {v: next(iter(n)) for v, n in novo_por_velho.items() if len(n) == 1}
    ambiguos = {v: sorted(n) for v, n in novo_por_velho.items() if len(n) > 1}
    return mapa, ambiguos, projs


# ------------------------------------------------------------------------- prod (read)
def connect(profile, catalog, schema):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format
    w = WorkspaceClient(profile=profile)
    fq = f"{catalog}.{schema}"

    def q(sql):
        r = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=WID, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
        sid = r.statement_id
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = w.statement_execution.get_statement(statement_id=sid)
        if not r.status or r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if (r.status and r.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:400]}")
        cols = [c.name for c in r.manifest.schema.columns]
        rows, chunk = [], r.result
        while chunk is not None:
            rows.extend(chunk.data_array or [])
            nxt = chunk.next_chunk_index
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
        return [dict(zip(cols, row)) for row in rows]

    return q, fq


def tem_estado(r):
    """Linha carrega decisão humana? (etapa/status derivados do auto NÃO contam)"""
    return bool(r.get("updated_by") or (r.get("responsavel") or "").strip()
                or (r.get("observacao") or "").strip() or r.get("status") == "Sanitizado")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="bv")
    ap.add_argument("--catalog", default="bv_dev_db")
    ap.add_argument("--schema", default="monitoramento_sas_dev")
    ap.add_argument("--apply", action="store_true", help="executa os UPDATEs (default: dry-run)")
    ap.add_argument("--forca", action="store_true",
                    help="aplica mesmo com chave de destino ausente (os UPDATEs "
                         "correspondentes casarão 0 linhas — normalmente significa que "
                         "o publish ainda não rodou)")
    ap.add_argument("--sobrescrever", action="store_true",
                    help="aplica mesmo quando a chave de destino já tem estado humano "
                         "(etapa/status/responsavel/observacao), substituindo-o")
    ap.add_argument("--i-know-its-prod", action="store_true",
                    help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    args = ap.parse_args()
    if args.apply and args.schema == PROD_SCHEMA and not args.i_know_its_prod:
        sys.exit(f"ERRO: --apply contra PROD exige --i-know-its-prod (schema={args.schema})")

    mapa, ambiguos, projs = build_map()
    print(f"== Re-key .sas7bdat -> LIB.MEMBRO ==\n")
    print(f"  conversões no 06        : {len(mapa) + len(ambiguos)}")
    print(f"  mapeáveis 1:1           : {len(mapa)}")
    print(f"  AMBÍGUAS (1 velho -> N) : {len(ambiguos)}   <- não migradas, decisão manual")
    for v, ns in list(ambiguos.items())[:6]:
        print(f"     {v}  ->  {', '.join(ns)}")

    q, fq = connect(args.profile, args.catalog, args.schema)
    print(f"\n  alvo: {fq}  ({'APPLY' if args.apply else 'dry-run'})")

    cols = ", ".join(HUMAN_COLS)
    velhos = list(mapa)
    lit = ", ".join(sql_lit(v) for v in velhos)
    linhas = q(f"SELECT chave_canonica, artifact, {cols} FROM {fq}.sas_inputs_monitor "
               f"WHERE chave_canonica IN ({lit})") if velhos else []
    com_estado = [r for r in linhas if tem_estado(r)]
    print(f"\n  linhas do mapa presentes no destino : {len(linhas)}")
    print(f"  └ COM decisão humana (a migrar)     : {len(com_estado)}")

    links = q(f"SELECT chave_canonica, projeto, link_broken FROM {fq}.sas_egp_input_link "
              f"WHERE chave_canonica IN ({lit})") if velhos else []
    print(f"  vínculos (sas_egp_input_link)       : {len(links)}")

    # estado humano que some pelo guard de macro (não tem destino)
    mac = q(f"SELECT chave_canonica, artifact, {cols} FROM {fq}.sas_inputs_monitor "
            f"WHERE categoria = 'arquivo'")
    mac = [r for r in mac if pub.is_macro_artifact(r.get("artifact")) and tem_estado(r)]
    print(f"\n  PERDA ACEITA — estado humano em artefato de macro (descartado pelo guard): {len(mac)}")
    for r in mac:
        print(f"     {r['artifact']:<42} status={r.get('status')} por={r.get('updated_by')}")

    stmts = []
    for r in com_estado:
        novo = mapa[r["chave_canonica"]]
        sets = ", ".join(f"{c} = {sql_lit(r.get(c))}" for c in HUMAN_COLS if c != "updated_at")
        stmts.append(f"UPDATE {fq}.sas_inputs_monitor SET {sets} "
                     f"WHERE chave_canonica = {sql_lit(novo)};")
    for r in links:
        novo = mapa[r["chave_canonica"]]
        stmts.append(f"UPDATE {fq}.sas_egp_input_link SET chave_canonica = {sql_lit(novo)} "
                     f"WHERE chave_canonica = {sql_lit(r['chave_canonica'])} "
                     f"AND projeto = {sql_lit(r['projeto'])};")

    with open(OUT_SQL, "w", encoding="utf-8") as f:
        f.write(f"-- re-key .sas7bdat -> LIB.MEMBRO · {fq} · {STAMP}\n")
        f.write(f"-- rodar DEPOIS do publish (a chave nova precisa existir)\n")
        f.write("\n".join(stmts) + ("\n" if stmts else ""))
    print(f"\n  {len(stmts)} statements -> {OUT_SQL}")

    # --- PRÉ-VOO: a chave de DESTINO tem de existir ------------------------------------
    # Todo UPDATE aqui é `WHERE chave_canonica = <novo>` e depende do publish já ter
    # criado a chave nova. Sem isso o UPDATE casa 0 linhas e o laço abaixo imprime
    # "i/N ok" assim mesmo: o operador vê sucesso e o estado humano (etapa/status/
    # responsavel/observacao) não foi migrado para lugar nenhum.
    destinos = sorted({mapa[r["chave_canonica"]] for r in com_estado})
    faltando, colisoes = [], []
    if destinos:
        _in = ", ".join(sql_lit(d) for d in destinos)
        presentes = q(f"SELECT {', '.join(('chave_canonica',) + HUMAN_COLS)} "
                      f"FROM {fq}.sas_inputs_monitor WHERE chave_canonica IN ({_in})")
        por_chave = {r["chave_canonica"]: r for r in presentes}
        faltando = [d for d in destinos if d not in por_chave]
        colisoes = [r for r in presentes if tem_estado(r)]

    if faltando:
        print(f"\n  ❌ {len(faltando)} chave(s) de DESTINO não existe(m) em "
              f"{fq}.sas_inputs_monitor:")
        for d in faltando[:10]:
            print(f"     {d}")
        if len(faltando) > 10:
            print(f"     ... e mais {len(faltando) - 10}")
        print("     Rode o publish/Processar primeiro (ele cria a chave nova) e só "
              "então reaplique.")

    if colisoes:
        # O UPDATE seta TODAS as HUMAN_COLS incondicionalmente. Se um analista já editou
        # a linha de destino (ela existe no app assim que o publish a cria), esses
        # valores seriam substituídos pelos vindos da chave `arquivo::` antiga.
        print(f"\n  ⚠️  {len(colisoes)} chave(s) de destino JÁ tem estado humano — "
              f"aplicar sobrescreve o que está lá:")
        for r in colisoes[:10]:
            print(f"     {r['chave_canonica']:<52} status={r.get('status')} "
                  f"por={r.get('updated_by')}")
        if len(colisoes) > 10:
            print(f"     ... e mais {len(colisoes) - 10}")

    if not args.apply:
        print("\n  [dry-run] nada foi escrito. Use --apply para executar.")
        return
    if faltando and not args.forca:
        print("\n  ABORTADO: destino ausente (acima). Use --forca para aplicar mesmo "
              "assim (os UPDATEs correspondentes casarão 0 linhas).")
        sys.exit(2)
    if colisoes and not args.sobrescrever:
        print("\n  ABORTADO: há estado humano no destino (acima). Use --sobrescrever "
              "para substituí-lo conscientemente.")
        sys.exit(2)

    print("\n  == APPLY ==")
    for i, s in enumerate(stmts, 1):
        q(s)
        print(f"    {i}/{len(stmts)} ok")
    print("  concluído.")


if __name__ == "__main__":
    main()

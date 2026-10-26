#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safras REAIS de cada padrão de arquivo, lidas do corpus de logs SAS no Databricks.

Complementa `catalogo_inputs_macro.py`: lá o padrão vem do código (`&DT_ARQ._BASE.csv` na
pasta X); aqui ele é confrontado com o que o SAS de fato leu/escreveu. É a única fonte de
HISTÓRICO sem acesso ao `N:` — o log interno do `.egp` traz uma execução, o corpus traz
todas as que couberem na janela ingerida.

Fonte: `bv_dev_db.bv_migration_sas.log_process` (135,2M linhas; 68.658 arquivos de log).
Só SELECT. **A janela do corpus é curta** (medida em 17/09/2026: 2025-07-31 a 2025-10-27):
padrão executado fora dela não aparece, e ausência aqui NÃO significa que o arquivo não
exista. `dim_macro_vars` não serve para isto: tem só `LET`/`LIB`, extraídos do CÓDIGO.

A busca é dirigida pelos literais do esqueleto (uma alternância regex só), em vez de
extrair todo nome datado do corpus — extração aberta estourava em volume e o corte por
"mais mencionados" enviesava a cobertura.

Uso:
    cd egps_analysis && venv/bin/python docs/analises/safras_vistas_no_log.py
    ... --catalogo docs/analises/BV_Migracao_SAS_Catalogo_Inputs_Macro_2026-09-17.csv
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
FQ = "bv_dev_db.bv_migration_sas"
TABELA = f"{FQ}.log_process"
# Lista de safras por padrão pode ter milhares (1.591 no maior caso): a coluna guarda as
# primeiras N, e `n_safras_vistas` guarda o total — número truncado sem aviso é pior que
# número ausente.
TETO_LISTA = 60
csv.field_size_limit(10 ** 7)


def literal_discriminante(esqueleto):
    """Maior trecho literal do esqueleto (o que não é macro). `None` se não discrimina.

    `#.SAS7BDAT` tem só a extensão como literal e casaria qualquer arquivo — devolver
    `None` aqui é o que impede o script de dizer "achei 20 mil safras" para um padrão que
    não identifica nada.
    """
    partes = [p for p in esqueleto.split("#") if p]
    if not partes:
        return None
    maior = max(partes, key=len).rsplit(".", 1)[0]
    maior = maior.strip("_-. ")
    # Esqueleto pode trazer resíduo de macro não normalizada (`%SYSFUNC(...)`, `'18NOV2025'D`,
    # `&VAR`): esses caracteres quebram a string SQL e não são nome de arquivo. Aceita só o
    # alfabeto de nome de arquivo — literal fora dele vira "não discrimina", que é honesto.
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", maior or ""):
        return None
    return maior if len(re.sub(r"[^A-Z0-9]", "", maior.upper())) >= 6 else None


def regex_do_esqueleto(esqueleto):
    """Esqueleto -> regex do nome inteiro; cada `#` é UMA macro-var e não atravessa `_`."""
    lits = esqueleto.split("#")
    return re.compile("^" + r"[^_]*".join(re.escape(x) for x in lits) + "$", re.I)


def roda_sql(sql, profile="bv", warehouse="5922c26f81f1bbdd"):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format
    w = WorkspaceClient(profile=profile)
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(5)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise SystemExit("SQL falhou: " + str(r.status.error)[:300])
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogo", default=None, help="CSV do catalogo_inputs_macro (default: o mais recente)")
    ap.add_argument("--profile", default="bv")
    args = ap.parse_args()
    cam = args.catalogo or max(glob.glob(os.path.join(AQUI, "BV_Migracao_SAS_Catalogo_Inputs_Macro_*.csv")),
                               default=None)
    if not cam:
        raise SystemExit("rode catalogo_inputs_macro.py primeiro")
    cat = [r for r in csv.DictReader(open(cam, encoding="utf-8-sig")) if r["tipo_macro"] == "data"]
    pares = collections.defaultdict(list)
    for r in cat:
        pares[(r["dir_resolvido"], r["esqueleto"])].append(r)
    alvos = {k: literal_discriminante(k[1]) for k in pares}
    uteis = {k: v for k, v in alvos.items() if v}
    print(f"catálogo: {len(cat)} refs de data · {len(pares)} padrões "
          f"({len(uteis)} com literal discriminante)")

    lits = sorted({v.upper() for v in uteis.values()})
    alt = "|".join(re.escape(x) for x in lits)
    sql = f"""
WITH achado AS (
  SELECT log_date,
    upper(regexp_extract(content,
      '([A-Za-z0-9_.\\\\-]*(?:{alt})[A-Za-z0-9_.\\\\-]*\\\\.(?:csv|xlsx|xls|txt|dat|zip|sas7bdat))', 1)) nome
  FROM {TABELA}
  WHERE upper(content) RLIKE '{alt}')
SELECT nome, count(*) mencoes, min(log_date) primeira, max(log_date) ultima
FROM achado WHERE nome <> '' GROUP BY nome"""
    print(f"consultando {TABELA} ({len(lits)} literais numa alternância)…")
    vistos = roda_sql(sql, args.profile)
    print(f"nomes distintos casados no log: {len(vistos)}")

    tok = re.compile(r"(20[0-9]{6}|20[0-9]{4}|[0-9]{8})")
    linhas = []
    for k, refs in sorted(pares.items()):
        lit = alvos[k]
        rx = regex_do_esqueleto(k[1]) if lit else None
        m = [v for v in vistos if rx and rx.match(v["nome"])] if rx else []
        safras = sorted({t.group(1) for v in m for t in [tok.search(v["nome"])] if t})
        egps = sorted({r["egp"] for r in refs})
        linhas.append({
            "esqueleto": k[1],
            "dir_resolvido": k[0],
            "direcoes": ",".join(sorted({r["direcao"] for r in refs})),
            "no_escopo_indi": any(r["no_escopo_indi"] == "True" for r in refs),
            "n_egps": len(egps),
            "egps": " | ".join(egps[:6]),
            "discrimina": bool(lit),
            "n_nomes_vistos": len(m),
            "n_safras_vistas": len(safras),
            "safra_min": safras[0] if safras else "",
            "safra_max": safras[-1] if safras else "",
            "primeira_mencao": min((v["primeira"] for v in m), default=""),
            "ultima_mencao": max((v["ultima"] for v in m), default=""),
            "safras": " | ".join(safras[:TETO_LISTA]) + (" | …" if len(safras) > TETO_LISTA else ""),
            "macro_vars": ",".join(sorted({r["macro_vars"] for r in refs})),
        })
    linhas.sort(key=lambda r: (-r["n_safras_vistas"], r["esqueleto"]))
    hoje = datetime.date.today().isoformat()
    out = os.path.join(AQUI, f"BV_Migracao_SAS_Safras_No_Log_{hoje}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        wr.writeheader()
        wr.writerows(linhas)

    com = [r for r in linhas if r["n_safras_vistas"] > 0]
    hist = [r for r in com if r["n_safras_vistas"] > 1]
    print(f"\npadrões com safra vista no log : {len(com)} de {len(linhas)}")
    print(f"  com HISTÓRICO (>=2 safras)   : {len(hist)}")
    print(f"  no escopo Indicium           : {sum(1 for r in com if r['no_escopo_indi'])}")
    print(f"  sem literal discriminante    : {sum(1 for r in linhas if not r['discrimina'])}"
          " (não dá para afirmar nada sobre eles)")
    jan = [r["primeira_mencao"] for r in com if r["primeira_mencao"]]
    if jan:
        print(f"  janela observada             : {min(jan)[:10]} a "
              f"{max(r['ultima_mencao'] for r in com if r['ultima_mencao'])[:10]}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    raise SystemExit(main())

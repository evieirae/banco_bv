# -*- coding: utf-8 -*-
"""Compara, tabela a tabela, o espelho no Postgres com o Databricks — ADR 0005, Fase 1.

Vem antes da comparação por rota (paridade.compara): prova que a cópia é fiel célula a
célula, NO FORMATO QUE O APP RECEBE — o Databricks em JSON_ARRAY, como o run_sql do app, e o
Postgres pela view compat formatada por db_pg.texto. A comparação é de multiconjunto (o
Delta não tem ordem). Não imprime valor nenhum (há e-mail e texto livre): só contagens e o
nome das colunas que diferem.

Rode logo depois de uma sincronização: o que alguém editar no app do Databricks entre a
sincronização e a comparação aparece como diferença (rode de novo para confirmar).

Uso (a partir de egps_analysis/app):
  DATABRICKS_CONFIG_PROFILE=<perfil> PG_DSN=postgresql://... \\
    python -m paridade.tabelas --warehouse <id> [--origem bv_dev_db.monitoramento_sas] [--tabela sas_x] \\
    [--escritas [--desde <instante UTC>]]
"""
import argparse
import collections
import os
import re
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import db_pg  # noqa: E402
from sync import espelho, leitor  # noqa: E402


# Depois do roteiro de escritas (paridade.escritas, Fase 2) os dois lados carimbaram em instantes
# diferentes e sortearam ids diferentes. Esses valores viram a CLASSE do valor, que ainda tem de
# bater dos dois lados: '... +00' no texto do Postgres não é o formato do Spark e continua
# aparecendo como diferença. Instante vale em qualquer coluna (o audit do snapshot da
# priorização grava a hora em valor_novo); data sem hora não é instante e compara pelo valor.
# Os dois formatos têm classe própria ('<instante>' e '<instante T>'): se um lado trocar um
# pelo outro, aparece. Sem --desde, TODO instante vira classe, inclusive os anteriores ao
# roteiro (a fidelidade deles é a da comparação SEM --escritas, 40/40). Com --desde, só vira
# classe o instante a partir dele; o anterior compara pelo valor, e então aparece (a) UPDATE
# traduzido que perdeu o carimbo (o valor antigo difere do que o outro lado carimbou) e
# (b) UPDATE amplo demais que carimbou linhas a mais. O instante novo continua só pela classe:
# fuso deslocado para trás além da folga (ex.: sessão em America/Sao_Paulo) cai antes do
# --desde e aparece; deslocado para frente continua só pela classe.
INSTANTE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?", re.ASCII)
INSTANTE_T = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?Z", re.ASCII)
ID_GERADO = re.compile(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                       re.ASCII)


DESDE_FORMATO = re.compile(r"\d{4}-\d\d-\d\d( \d\d:\d\d(:\d\d)?|T\d\d:\d\d(:\d\d(\.\d{1,6})?)?Z)", re.ASCII)


def _segundo(v):
    return v[:19].replace("T", " ")


def desde_valido(texto):
    """Tipo do --desde. A comparação é lexicográfica: formato fora do padrão desligaria a
    proteção em silêncio, então só 'AAAA-MM-DD HH:MM[:SS]' e 'AAAA-MM-DDTHH:MM[:SS][.f]Z' passam."""
    if not DESDE_FORMATO.fullmatch(texto):
        raise argparse.ArgumentTypeError(
            f"{texto!r}: use 'AAAA-MM-DD HH:MM[:SS]' ou 'AAAA-MM-DDTHH:MM[:SS][.f]Z' (UTC)")
    s = texto.rstrip("Z").replace("T", " ")
    return s[:19] if len(s) >= 19 else s + ":00"


def mascara(colunas, linha, desde=None):
    desde = _segundo(desde) if desde else None
    saida = []
    for c, v in zip(colunas, linha, strict=True):
        if v is not None and (INSTANTE.fullmatch(v) or INSTANTE_T.fullmatch(v)):
            if desde is None or _segundo(v) >= desde:
                v = "<instante T>" if "T" in v else "<instante>"
        elif v is not None and c == "id" and ID_GERADO.fullmatch(v):
            v = "<id>"
        saida.append(v)
    return tuple(saida)


def diferenca(antigo, novo, colunas):
    """antigo/novo: listas de tuplas (texto). Devolve o resumo sem valores."""
    a, b = collections.Counter(antigo), collections.Counter(novo)
    so_a, so_b = a - b, b - a
    cols = set()
    for x in so_a:                     # coluna que difere entre a linha que sobrou de cada lado
        for y in so_b:                 # e a mais parecida do outro lado
            dif = [c for c, p, q in zip(colunas, x, y) if p != q]
            if len(dif) <= max(1, len(colunas) // 3):
                cols.update(dif)
                break
    return {"linhas_databricks": len(antigo), "linhas_postgres": len(novo),
            "so_no_databricks": sum(so_a.values()), "so_no_postgres": sum(so_b.values()),
            "colunas_que_diferem": sorted(cols)}


def le_postgres(conn, tabela):
    cols = espelho.colunas(tabela)
    return [tuple(db_pg.texto(v) for v in r)
            for r in conn.execute(f"SELECT {', '.join(cols)} FROM compat.{tabela}")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compara o espelho com o Databricks, tabela a tabela")
    ap.add_argument("--warehouse", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    ap.add_argument("--origem", default="bv_dev_db.monitoramento_sas")
    ap.add_argument("--tabela", action="append")
    ap.add_argument("--escritas", action="store_true",
                    help="depois de paridade.escritas: carimbo de instante e id gerado comparam pela classe")
    ap.add_argument("--desde", type=desde_valido,
                    help="com --escritas: só instante a partir deste (UTC, 'AAAA-MM-DD HH:MM:SS') "
                    "vira classe; é o início do roteiro com uma folga (ex.: 1 minuto antes), por causa do "
                    "relógio entre as máquinas. Sem ele, todo instante vira classe")
    args = ap.parse_args(argv)
    if args.desde and not args.escritas:
        ap.error("--desde só vale com --escritas")
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    iguais, total = 0, 0
    with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
        for t in args.tabela or espelho.TABELAS:
            cols = espelho.colunas(t)
            antigo = [tuple(r[c] for c in cols)
                      for r in leitor.le_tabela(w, args.warehouse, f"{args.origem}.{t}", cols)]
            novo = le_postgres(conn, t)
            if args.escritas:
                antigo = [mascara(cols, x, args.desde) for x in antigo]
                novo = [mascara(cols, x, args.desde) for x in novo]
            r = diferenca(antigo, novo, cols)
            igual = r["so_no_databricks"] == r["so_no_postgres"] == 0
            iguais, total = iguais + igual, total + 1
            print(f"[tabelas] {'IGUAL' if igual else 'DIFERE'} {t}: {r}", flush=True)
    print(f"[tabelas] {iguais}/{total} tabelas iguais")
    sys.exit(0 if iguais == total else 1)


if __name__ == "__main__":
    main()

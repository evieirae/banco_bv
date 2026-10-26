# -*- coding: utf-8 -*-
"""Qual banco o app usa e como escrever um literal de texto nele (ADR 0005).

Na Fase 1 o MESMO código serve o app do Databricks (prod atual) e o app na AWS (Postgres).
Fora daqui e de db_pg.py o backend não pergunta qual é o banco: o que muda de um para o
outro é o literal e a execução — o resto do SQL é escrito na forma que roda nos dois.
"""
import os

DB_BACKEND = os.environ.get("DB_BACKEND", "databricks").strip().lower()
if DB_BACKEND not in ("databricks", "postgres"):
    raise RuntimeError(f"DB_BACKEND inválido: {DB_BACKEND!r} (use databricks ou postgres)")
PG = DB_BACKEND == "postgres"


def lit(v, pg=None):
    """Literal SQL de texto (None vira NULL).

    Spark: a aspa vira \\' e a contrabarra é dobrada antes — no Spark `'O''Brien'` são DOIS
    literais concatenados e o apóstrofo some em silêncio (verificado no warehouse).
    Postgres (standard_conforming_strings=on, o padrão): a aspa vira '' e a contrabarra é
    literal — o \\' do Spark lá FECHA a string, e `x\\' OR 1=1 --` vira injeção.
    """
    if v is None:
        return "NULL"
    s = str(v)
    if PG if pg is None else pg:
        return "'" + s.replace("'", "''") + "'"
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

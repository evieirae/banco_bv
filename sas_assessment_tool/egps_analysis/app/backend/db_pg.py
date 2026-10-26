# -*- coding: utf-8 -*-
"""Execução de SQL no Postgres com o MESMO contrato de main.run_sql (ADR 0005).

O contrato vem do Databricks (formato JSON_ARRAY): toda célula volta como TEXTO, ou None.
O app foi escrito em cima disso (`== "true"`, `int(r["n"])`, `substr(ts, 1, 7)` no front),
e na Fase 1 a resposta da API não muda — então o texto é reproduzido aqui, em vez de o app
inteiro aprender tipos nativos agora. Booleano vira "true"/"false"; instante vira ISO-8601
em UTC com milissegundos e "Z"; data vira AAAA-MM-DD; lista vira JSON.

`search_path` põe `compat` ANTES de `pg_catalog`: as funções com nome do Spark que moram em
compat (regexp_replace global, split por regex, count_if...) sombreiam as do sistema.
"""
import datetime
import decimal
import json
import os
import threading

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

SEARCH_PATH = "compat, derivado, pg_catalog, public"
ESCRITA = ("insert", "update", "delete", "merge", "create", "alter", "drop", "truncate",
           "grant", "revoke", "copy", "comment", "vacuum")
# SQLSTATE -> marca que main._objeto_ausente / main._sql_http_error já reconhecem.
_MARCA = {
    "42P01": "TABLE_OR_VIEW_NOT_FOUND",   # undefined_table
    "42703": "UNRESOLVED_COLUMN",         # undefined_column
    "42501": "permission denied",         # insufficient_privilege
}

_pool = None
_pool_lock = threading.Lock()


class ErroSQL(Exception):
    """Falha de SQL, com a mensagem no formato que o main já classifica."""


def _configura(conn):
    conn.execute(f"SET search_path = {SEARCH_PATH}")
    conn.execute("SET TIME ZONE 'UTC'")
    # O instante gravado em coluna texto (main.AGORA = localtimestamp) sai no formato do Spark
    # ('2026-10-15 19:27:07.090031') só com DateStyle ISO: fixado aqui, não herdado do servidor.
    conn.execute("SET DateStyle = 'ISO, MDY'")
    # Na AWS o app entra com o usuário MESTRE (o único que o indicium-secret-rotation gira)
    # e baixa os privilégios da sessão para PG_PAPEL (app_leitura na Fase 1; app_escrita no dev a partir do 2a e na prod a partir da virada). Barreira contra
    # escrita por engano; não contra quem já injeta SQL (RESET ROLE desfaz) — essa é do
    # sql_lit/parâmetros e do middleware de acesso.
    papel = os.environ.get("PG_PAPEL")
    if papel:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(papel)))
    conn.commit()


def pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            # PG_DSN no uso local; no ECS vêm as variáveis padrão da libpq (PGHOST, PGUSER,
            # PGPASSWORD do Secrets Manager...) e a string de conexão fica vazia.
            dsn = os.environ.get("PG_DSN") or ""
            if not dsn and not os.environ.get("PGHOST"):
                raise RuntimeError("Sem PG_DSN nem PGHOST (DB_BACKEND=postgres).")
            _pool = ConnectionPool(dsn, min_size=1, max_size=int(os.environ.get("PG_POOL_MAX", "10")),
                                   configure=_configura, open=True)
    return _pool


def texto(v):
    """Uma célula no formato que o Databricks devolvia."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return v.isoformat(timespec="milliseconds") + "Z"
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return format(v, "f")
    if isinstance(v, (list, tuple)):
        return json.dumps([texto(x) for x in v], ensure_ascii=False)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def e_escrita(statement):
    """Primeira palavra é comando que escreve. Defesa em profundidade: a barreira de verdade
    é o papel de banco do app (app_leitura só tem SELECT)."""
    palavras = statement.split(None, 1)
    return bool(palavras) and palavras[0].lower() in ESCRITA


def run(statement, want_rows=True, params=None, somente_leitura=False):
    if somente_leitura and e_escrita(statement):
        raise ErroSQL("permission denied: escrita recusada — app em modo leitura")
    try:
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(statement, params)
                if not want_rows or cur.description is None:
                    return None
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, (texto(v) for v in linha))) for linha in cur.fetchall()]
    except psycopg.Error as e:
        codigo = getattr(e, "sqlstate", None) or ""
        raise ErroSQL(f"{_MARCA.get(codigo, '')} [{codigo}] {e}".strip()) from e

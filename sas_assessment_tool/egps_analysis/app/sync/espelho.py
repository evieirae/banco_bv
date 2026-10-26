# -*- coding: utf-8 -*-
"""Espelho fiel das tabelas Delta que o app lê (ADR 0005, Fase 1 — decisão de 14/10/2026).

Na Fase 1 o Databricks é a fonte da verdade e o app na AWS só lê. As tabelas que o app lê
entram no Postgres como CÓPIA FIEL no schema `legado` — mesmas colunas, mesmos tipos, mesmos
valores, inclusive '' x NULL e os instantes que o Databricks guarda como texto — e cada view
`compat.<tabela>` só lê de lá. Assim a resposta da API sai igual à do Databricks por
construção. O de-para com correções para o schema novo é da Fase 2, grupo a grupo; as 5
tabelas do 1a continuam sendo normalizadas também (cadastro, âncoras, início da Fase 2).

Tipos: string -> text, int -> integer, bigint -> bigint, double -> double precision,
boolean -> boolean, timestamp -> timestamp SEM fuso, em UTC. Sem fuso porque assim
`CAST(x AS STRING)` no Postgres sai igual ao do Spark e o driver devolve
AAAA-MM-DDTHH:MM:SS.mmmZ, como o JSON do Databricks. O TIMESTAMP é LIDO como
`CAST(x AS STRING)`: o JSON do Databricks corta em milissegundos; o texto guarda os micros.
"""
import datetime

from .espelho_tabelas import TABELAS

TIPO_PG = {"string": "text", "int": "integer", "bigint": "bigint", "double": "double precision",
           "boolean": "boolean", "timestamp": "timestamp"}


class ValorInesperado(ValueError):
    pass


def colunas(tabela):
    return tuple(c for c, _ in TABELAS[tabela])


def selecao(tabela):
    """Expressões do SELECT no Databricks, na ordem de colunas(tabela)."""
    return tuple(f"CAST({c} AS STRING) AS {c}" if t == "timestamp" else c for c, t in TABELAS[tabela])


def converte(tipo, v):
    """Texto do Databricks -> valor Python do tipo da coluna em `legado`. Texto fica como veio."""
    if v is None:
        return None
    if tipo == "string":
        return v
    if tipo in ("int", "bigint"):
        return int(v)
    if tipo == "double":
        return float(v)
    if tipo == "boolean":
        if v in ("true", "false"):
            return v == "true"
        raise ValorInesperado(f"booleano inesperado: {v!r}")
    if tipo == "timestamp":
        d = datetime.datetime.fromisoformat(v)      # 'AAAA-MM-DD HH:MM:SS[.ffffff]', sessão em UTC
        if d.tzinfo is not None:                    # 'Z' (formato JSON) também é UTC
            if d.utcoffset() != datetime.timedelta(0):
                raise ValorInesperado(f"instante fora de UTC: {v!r}")
            d = d.replace(tzinfo=None)
        return d
    raise ValorInesperado(f"tipo Delta não previsto: {tipo!r}")


def monta(linhas):
    """`linhas`: tabela Delta -> lista de dicts (texto). Devolve tabela -> lista de tuplas na
    ordem de colunas(). Tabela ausente vira lista vazia (a massa sintética só traz algumas);
    coluna ausente vira NULL."""
    saida = {}
    for t, cols in TABELAS.items():
        saida[t] = [tuple(converte(tipo, r.get(c)) for c, tipo in cols) for r in linhas.get(t, [])]
    return saida


def carrega(cur, espelho):
    """Regrava `legado` inteiro (DELETE + COPY) dentro da transação de quem chama."""
    resumo = {}
    for t in TABELAS:
        cur.execute(f"DELETE FROM legado.{t}")
        with cur.copy(f"COPY legado.{t} ({', '.join(colunas(t))}) FROM STDIN") as cp:
            for linha in espelho.get(t, []):
                cp.write_row(linha)
        resumo[t] = len(espelho.get(t, []))
    return resumo

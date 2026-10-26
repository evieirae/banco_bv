# -*- coding: utf-8 -*-
"""Aplica as migrações numeradas de db/migrations, em ordem (ADR 0005).

Cada arquivo roda numa transação; a versão só é registrada se o arquivo inteiro passou.
Tabela ou coluna nova no app só entra com a migração correspondente — os `_ensure_*` e as
sondas ALTER ADD COLUMNS do tempo do Databricks não rodam no Postgres.

O banco tem de ter collation "C": o Spark ordena texto por bytes (`TI` antes de `Teste`,
`Ágil` depois de `Zeta`), e o app no Postgres precisa devolver as listas na mesma ordem.
A collation só se escolhe ao CRIAR o banco — por isso o RDS nasce sem banco do app e
`--cria-banco` o cria (o `db_name` do Terraform usaria a collation de idioma da instância).

Uso:  PG_DSN=postgresql://... python -m db.migra               aplica as pendentes
      PG_DSN=postgresql://... python -m db.migra --cria-banco  cria o banco (collation C), se
                                                               faltar, e aplica as pendentes
      PG_DSN=postgresql://... python -m db.migra --status      lista aplicadas e pendentes
"""
import argparse
import os
import pathlib
import re
import sys

import psycopg
from psycopg import conninfo, sql

PASTA = pathlib.Path(__file__).with_name("migrations")
_NOME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
COLLATION = "C"


def arquivos(pasta=PASTA):
    achados = []
    for p in sorted(pathlib.Path(pasta).glob("*.sql")):
        m = _NOME.match(p.name)
        if not m:
            raise SystemExit(f"nome de migração fora do padrão NNNN_nome.sql: {p.name}")
        achados.append((m.group(1), p))
    versoes = [v for v, _ in achados]
    if len(versoes) != len(set(versoes)):
        raise SystemExit(f"versão repetida em {pasta}: {versoes}")
    return achados


def cria_banco(dsn, saida=print):
    """Cria o banco do DSN com collation C, conectando no banco `postgres` do mesmo servidor.
    True se criou, False se já existia (a collation do existente é conferida pelo `aplica`)."""
    partes = conninfo.conninfo_to_dict(dsn)
    nome = partes.get("dbname")
    if not nome:
        raise SystemExit("PG_DSN sem dbname: não sei que banco criar")
    with psycopg.connect(conninfo.make_conninfo(dsn, dbname="postgres"), autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nome,)).fetchone():
            saida(f"[migra] banco {nome} já existe")
            return False
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 LC_COLLATE {}").format(
            sql.Identifier(nome), sql.Literal(COLLATION)))
    saida(f"[migra] banco {nome} criado (collation {COLLATION})")
    return True


def _confere_collation(conn):
    nome, col = conn.execute("SELECT datname, datcollate FROM pg_database "
                             "WHERE datname = current_database()").fetchone()
    if col != COLLATION:
        raise SystemExit(f"banco {nome} com collation {col!r}; o app precisa de {COLLATION!r} "
                         f"(ordem de bytes, como o Spark). Recrie com --cria-banco.")
    # A collation C não muda a CAIXA: upper() segue o LC_CTYPE do banco (o padrão do
    # servidor; no RDS, en_US.UTF-8). Com LC_CTYPE 'C' o upper() só vê ASCII, e a regra de
    # família (MARÇO, ABRIL...) daria chave diferente da do Spark, sem erro nenhum.
    if conn.execute("SELECT upper('ç') = 'Ç'").fetchone()[0] is not True:
        raise SystemExit(f"banco {nome}: upper('ç') não dá 'Ç' (LC_CTYPE sem Unicode); o app "
                         f"precisa da caixa como no Spark. Recrie num servidor com LC_CTYPE UTF-8.")


def _garante_controle(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migracao ("
                 "versao text PRIMARY KEY, arquivo text NOT NULL, "
                 "aplicada_em timestamptz NOT NULL DEFAULT now())")


def aplicadas(conn):
    return {r[0] for r in conn.execute("SELECT versao FROM public.schema_migracao")}


def aplica(dsn, pasta=PASTA, saida=print):
    # autocommit é obrigatório: sem ele o SELECT de `aplicadas` abre uma transação
    # implícita, cada `conn.transaction()` vira SAVEPOINT dentro dela, e a falha de um
    # arquivo desfaz também os anteriores (pego pelo test_arquivo_que_falha_nao_deixa_rastro).
    with psycopg.connect(dsn, autocommit=True) as conn:
        _confere_collation(conn)
        _garante_controle(conn)
        feitas = aplicadas(conn)
        novas = 0
        for versao, caminho in arquivos(pasta):
            if versao in feitas:
                continue
            with conn.transaction():
                conn.execute(caminho.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.schema_migracao (versao, arquivo) VALUES (%s, %s)",
                             (versao, caminho.name))
            saida(f"[migra] aplicada {caminho.name}")
            novas += 1
        saida(f"[migra] {novas} nova(s); {len(feitas) + novas} no total")
        return novas


def status(dsn, pasta=PASTA, saida=print):
    with psycopg.connect(dsn, autocommit=True) as conn:
        _garante_controle(conn)
        feitas = aplicadas(conn)
    for versao, caminho in arquivos(pasta):
        saida(f"{'aplicada' if versao in feitas else 'PENDENTE'}  {caminho.name}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--cria-banco", action="store_true")
    args = ap.parse_args(argv)
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        sys.exit("PG_DSN não definido")
    if args.cria_banco:
        cria_banco(dsn)
    (status if args.status else aplica)(dsn)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Migrações aplicadas num banco limpo: comportamento do schema e das funções Spark."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
pytestmark = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


@pytest.fixture(scope="module")
def conn():
    import psycopg
    nome = "t_schema_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    c = psycopg.connect(dsn, autocommit=True)
    c.execute("SET search_path = compat, derivado, pg_catalog, public")
    c.execute("SELECT set_config('app.usuario', 'teste@indicium.ai', false)")
    yield c
    c.close()
    with psycopg.connect(DSN, autocommit=True) as c2:
        c2.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _um(conn, sql):
    return conn.execute(sql).fetchone()[0]


@pytest.mark.parametrize("sql, esperado", [
    ("SELECT CAST(42 AS STRING)", "42"),
    ("SELECT CAST('1.5' AS DOUBLE)", 1.5),
    ("SELECT split('a|b|c', '[|]')", ["a", "b", "c"]),
    ("SELECT element_at(split('a|b', '[|]'), 1)", "a"),
    ("SELECT array_contains(split('a|b', '[|]'), 'b')", True),
    ("SELECT arrays_overlap(split('a|b', '[|]'), split('c|b', '[|]'))", True),
    ("SELECT size(split('a|b', '[|]'))", 2),
    ("SELECT regexp_replace('a-b-c', '-', '')", "abc"),
    ("SELECT count_if(x > 1) FROM (VALUES (1), (2), (3)) t(x)", 2),
    ("SELECT date_format(timestamptz '2026-10-14 15:04:05+00', 'yyyy-MM-dd')", "2026-10-14"),
    ("SELECT date_format(date '2026-10-14', 'yyyy-MM')", "2026-10"),
    ("SELECT date_format(from_utc_timestamp(timestamptz '2026-10-14 02:00+00', 'America/Sao_Paulo'), 'yyyy-MM-dd')",
     "2026-10-13"),
    ("SELECT count(*) FROM (SELECT explode(split('a|b|c', '[|]')) AS x) t", 3),
])
def test_funcoes_spark(conn, sql, esperado):
    assert _um(conn, sql) == esperado


def test_ancora_com_estado_humano_nao_se_apaga_e_rekey_propaga(conn):
    import psycopg
    conn.execute("INSERT INTO corpus.egp (projeto) VALUES ('Area__EGP_A')")
    conn.execute("INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('tabela::LIB.T', 'tabela', 'LIB.T')")
    conn.execute("INSERT INTO trabalho.leitura_dispensada (projeto, input_chave) VALUES ('Area__EGP_A', 'tabela::LIB.T')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("DELETE FROM corpus.input WHERE chave = 'tabela::LIB.T'")
    conn.execute("UPDATE corpus.input SET chave = 'tabela::LIB.T2', artefato = 'LIB.T2' WHERE chave = 'tabela::LIB.T'")
    assert _um(conn, "SELECT input_chave FROM trabalho.leitura_dispensada") == "tabela::LIB.T2"
    assert _um(conn, "SELECT atualizado_por FROM trabalho.leitura_dispensada") == "teste@indicium.ai"


def test_comentario_tem_um_alvo_so(conn):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO trabalho.gestao_comentario (projeto, input_chave, autor, texto) "
                     "VALUES ('Area__EGP_A', 'tabela::LIB.T2', 'a@indicium.ai', 'x')")


def test_papel_de_leitura_nao_escreve(conn):
    import psycopg
    conn.execute("CREATE ROLE t_leitor LOGIN IN ROLE app_leitura")
    try:
        conn.execute("SET ROLE t_leitor")
        assert _um(conn, "SELECT count(*) FROM corpus.egp") >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO corpus.egp (projeto) VALUES ('x__y')")
    finally:
        conn.execute("RESET ROLE")
        conn.execute("DROP ROLE t_leitor")


def test_prefixo_da_chave_bate_com_a_categoria(conn):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('arquivo::X', 'tabela', 'X')")

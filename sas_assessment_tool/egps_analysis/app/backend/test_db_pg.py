# -*- coding: utf-8 -*-
"""db_pg: formato de saída igual ao do Databricks + execução real contra um Postgres.

Os testes de execução precisam de PG_TEST_DSN. Sem ele são pulados — EXCETO no CI, onde
PG_TEST_OBRIGATORIO=1 transforma o pulo em falha (pular em silêncio esconderia o gate).
"""
import datetime
import decimal
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import db_pg  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


@pytest.fixture
def pool_novo(monkeypatch):
    """Cada teste abre o próprio pool (com o ambiente dele) e o FECHA no fim — trocar o
    pool sem fechar deixa threads do psycopg_pool penduradas e polui a saída."""
    monkeypatch.setenv("PG_DSN", DSN or "")
    db_pg._pool = None
    yield
    if db_pg._pool is not None:
        db_pg._pool.close()
    db_pg._pool = None


def test_texto_reproduz_o_formato_do_databricks():
    utc = datetime.timezone.utc
    assert db_pg.texto(None) is None
    assert db_pg.texto(True) == "true" and db_pg.texto(False) == "false"
    assert db_pg.texto(7) == "7"
    assert db_pg.texto(decimal.Decimal("12.50")) == "12.50"
    assert db_pg.texto(datetime.datetime(2026, 10, 14, 15, 4, 5, 123456, tzinfo=utc)) == "2026-10-14T15:04:05.123Z"
    sp = datetime.timezone(datetime.timedelta(hours=-3))
    assert db_pg.texto(datetime.datetime(2026, 10, 14, 12, 0, tzinfo=sp)) == "2026-10-14T15:00:00.000Z"
    assert db_pg.texto(datetime.date(2026, 10, 1)) == "2026-10-01"
    assert db_pg.texto(["a", "b"]) == '["a", "b"]'


def test_e_escrita():
    assert db_pg.e_escrita("  INSERT INTO x VALUES (1)")
    assert db_pg.e_escrita("merge into t using s on 1=1 when matched then delete")
    assert not db_pg.e_escrita("SELECT 1")
    assert not db_pg.e_escrita("")


@precisa_pg
def test_run_devolve_texto(pool_novo):
    linhas = db_pg.run("SELECT true AS b, 2 AS n, NULL::text AS z, 'O''Brien' AS s")
    assert linhas == [{"b": "true", "n": "2", "z": None, "s": "O'Brien"}]


@precisa_pg
def test_run_com_params_e_percent_literal(pool_novo):
    assert db_pg.run("SELECT 'a%' AS p")[0]["p"] == "a%"
    assert db_pg.run("SELECT %s::int + 1 AS n", params=(41,))[0]["n"] == "42"


@precisa_pg
def test_tabela_ausente_vira_marca_que_o_main_entende(pool_novo):
    with pytest.raises(db_pg.ErroSQL, match="TABLE_OR_VIEW_NOT_FOUND"):
        db_pg.run("SELECT * FROM nao_existe_tabela")


@precisa_pg
def test_sessao_baixa_para_o_papel_configurado(pool_novo, monkeypatch):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't_papel_app') "
                  "THEN CREATE ROLE t_papel_app NOLOGIN; END IF; END $$")
    monkeypatch.setenv("PG_PAPEL", "t_papel_app")
    assert db_pg.run("SELECT current_user AS u")[0]["u"] == "t_papel_app"


@precisa_pg
def test_sessao_fixa_fuso_e_formato_do_instante(pool_novo, monkeypatch):
    """O instante gravado em coluna texto (`cast(AGORA AS STRING)` do main, Fase 2) só sai no
    formato do Spark ('2026-10-15 19:27:07.090031') com a sessão em UTC e DateStyle ISO. O
    app fixa os dois, sem herdar do servidor: aqui a conexão chega com outros."""
    import psycopg
    hostil = psycopg.conninfo.make_conninfo(DSN, options="-c DateStyle=SQL,DMY -c TimeZone=America/Sao_Paulo")
    monkeypatch.setenv("PG_DSN", hostil)
    r = db_pg.run("SELECT current_setting('DateStyle') AS ds, current_setting('TimeZone') AS tz, "
                  "localtimestamp::text AS agora")[0]
    assert (r["ds"], r["tz"]) == ("ISO, MDY", "UTC"), r
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?", r["agora"]), r


def test_modo_leitura_recusa_escrita_sem_ir_ao_banco():
    with pytest.raises(db_pg.ErroSQL, match="permission denied"):
        db_pg.run("DELETE FROM x", somente_leitura=True)

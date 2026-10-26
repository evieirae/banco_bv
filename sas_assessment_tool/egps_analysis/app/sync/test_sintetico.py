# -*- coding: utf-8 -*-
"""Massa sintética do ensaio: passa pelo caminho real e enche as views compat."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import sintetico  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")


def test_massa_e_deterministica():
    assert sintetico.linhas() == sintetico.linhas()


@pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
def test_carga_sintetica_enche_o_app():
    import psycopg
    nome = "t_sint_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    try:
        migra.aplica(dsn, saida=lambda *_: None)
        with psycopg.connect(dsn) as conn:
            resumo = sintetico.carrega_sintetico(conn, gestao="Treino@indicium.ai")
            assert resumo["corpus.egp"] == 40 and resumo["corpus.input"] == 300
            assert resumo["ancoras_acrescentadas"]["input"] == 0
            n, escopo = conn.execute("SELECT count(*), count(*) FILTER (WHERE escopo_indi) "
                                     "FROM compat.sas_inputs_monitor").fetchone()
            assert n == 300 and 0 < escopo < 300
            assert conn.execute("SELECT papel, ativo FROM cadastro.usuario "
                                "WHERE email = 'treino@indicium.ai'").fetchone() == ("gestao", True)
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")

# -*- coding: utf-8 -*-
"""Literal de texto nos dois dialetos — e a prova de que o do Spark é injeção no Postgres."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import dialeto  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")


def test_spark_dobra_contrabarra_e_escapa_aspa():
    assert dialeto.lit("O'Brien", pg=False) == "'O\\'Brien'"
    assert dialeto.lit("a\\b", pg=False) == "'a\\\\b'"


def test_postgres_dobra_aspa_e_deixa_contrabarra():
    assert dialeto.lit("O'Brien", pg=True) == "'O''Brien'"
    assert dialeto.lit("a\\b", pg=True) == "'a\\b'"


def test_none_vira_null():
    assert dialeto.lit(None, pg=True) == "NULL" and dialeto.lit(None, pg=False) == "NULL"


@pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
def test_no_postgres_o_literal_devolve_o_mesmo_texto():
    import psycopg
    ataque = "x\\' OR 1=1 --"
    with psycopg.connect(DSN) as conn:
        assert conn.execute(f"SELECT {dialeto.lit(ataque, pg=True)}").fetchone()[0] == ataque
        # e o escape do Spark, no Postgres, NÃO devolve o mesmo texto (é o furo):
        with pytest.raises(psycopg.Error):
            conn.execute(f"SELECT {dialeto.lit(ataque, pg=False)} AS s").fetchone()

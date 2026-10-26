# -*- coding: utf-8 -*-
"""SQL escrito para rodar igual no Spark e no Postgres (ADR 0005, 1b): confere no Postgres de
verdade contra a régua em Python. O lado Spark dessas mesmas expressões é o que o app de
produção já roda; a comparação de leituras (paridade) fecha a ponta entre os dois."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import familias as F  # noqa: E402
from backend import main as m  # noqa: E402
from db import migra  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
SEM_OVERRIDES = {"juntar": {}, "separar": set()}


@pytest.fixture(scope="module")
def conn():
    import psycopg
    nome = "t_port_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    migra.aplica(f"{base}/{nome}", saida=lambda *_: None)
    with psycopg.connect(f"{base}/{nome}", autocommit=True) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")
        yield c
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


@precisa_pg
@pytest.mark.parametrize("art,cat,paths", [
    ("GRIMALDI.CARGA_MASSIFICADOS_20250415", "tabela", None),
    ("SEGUROS.RECLAMACOES_ICATU_ABR25", "tabela", None),
    ("X.BASE_MARÇO25", "tabela", None),                      # upper() fora do ASCII
    ("ALVESDS.EMP_8_20260305._GCP", "tabela", None),
    ("ATIVOS.ATIVOS_ENCART_23_202509.30", "tabela", None),
    ("grimaldi.carga_massificados_202506", "tabela", None),
    ("202506", "tabela", None),
    ("EXCECOES_20250701.CSV", "arquivo", "/RISCOSBV/COBRANCA/EXCECOES_20250701.CSV"),
    ("EXCECOES_20250701.CSV", "arquivo", "\\\\srv\\COBRANCA\\EXCECOES_20250701.CSV | /B/X.CSV"),
    ("EXCECOES_20250701.CSV", "arquivo", ""),
    ("EXCECOES_20250701.CSV", "arquivo", None),
    ("ANSWERS.CSV", "arquivo", "/A/B/ANSWERS.CSV"),
    ("SCRIPT_20250101.SAS", "script", None),
])
def test_chave_de_familia_no_postgres_igual_a_regra_python(conn, art, cat, paths):
    expr = F.familia_candidata_sql(_lit(art), _lit(cat), _lit(paths), overrides=SEM_OVERRIDES)
    assert conn.execute(f"SELECT {expr}").fetchone()[0] == F.familia_candidata(art, cat, paths)


@precisa_pg
@pytest.mark.parametrize("lista,valores", [
    ("Cobranças | Crédito | Riscos", ["Crédito"]),
    ("Cobranças | Crédito | Riscos", ["Créd"]),               # pedaço de item não casa
    (" Cobranças|Riscos ", ["Riscos", "Jurídico"]),
    ("Planejamento e P&L (Rodas)", ["Planejamento e P&L (Rodas)"]),
    ("O'Brien | X", ["O'Brien"]),
])
def test_lista_tem_algum_casa_item_a_item(conn, monkeypatch, lista, valores):
    monkeypatch.setattr(m.dialeto, "PG", True)       # literal com a regra de aspas do Postgres
    esperado = any(v in [t.strip() for t in lista.split("|")] for v in valores)
    assert conn.execute(f"SELECT {m._lista_tem_algum(_lit(lista), valores)}").fetchone()[0] is esperado

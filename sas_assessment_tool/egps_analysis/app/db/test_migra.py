# -*- coding: utf-8 -*-
"""Executor de migrações: ordem, idempotência e rollback do arquivo que falha."""
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


@pytest.fixture
def banco_limpo():
    """Banco descartável por teste (CREATE DATABASE não roda dentro de transação)."""
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    yield f"{base}/{nome}"
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def test_aplica_em_ordem_e_e_idempotente(tmp_path, banco_limpo):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
    (tmp_path / "0002_b.sql").write_text("INSERT INTO a VALUES (1); INSERT INTO a VALUES (2);")
    assert migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None) == 2
    assert migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None) == 0


def test_arquivo_que_falha_nao_deixa_rastro(tmp_path, banco_limpo):
    import psycopg
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE ok (x int);")
    (tmp_path / "0002_quebra.sql").write_text("CREATE TABLE meia (x int); SELECT 1/0;")
    with pytest.raises(psycopg.Error):
        migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None)
    with psycopg.connect(banco_limpo) as c:
        assert c.execute("SELECT to_regclass('public.meia')").fetchone()[0] is None
        assert {r[0] for r in c.execute("SELECT versao FROM schema_migracao")} == {"0001"}


def test_banco_sem_collation_c_e_recusado(tmp_path):
    """O app ordena texto como o Spark (bytes). Banco com collation de idioma ordenaria
    `TI`/`Teste`, `Ágil`/`Zeta` diferente — e a diferença só apareceria na comparação."""
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'en_US.utf8'")
    base, _, _ = DSN.rpartition("/")
    try:
        (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
        with pytest.raises(SystemExit, match="collation"):
            migra.aplica(f"{base}/{nome}", tmp_path, saida=lambda *_: None)
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def test_banco_com_ctype_sem_unicode_e_recusado(tmp_path):
    """Collation C ordena como o Spark, mas a caixa vem do LC_CTYPE: com 'C' o upper('ç')
    fica 'ç' e a chave de família de MARÇO sairia diferente da do Spark, em silêncio."""
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'")
    base, _, _ = DSN.rpartition("/")
    try:
        (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
        with pytest.raises(SystemExit, match="upper"):
            migra.aplica(f"{base}/{nome}", tmp_path, saida=lambda *_: None)
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def test_cria_banco_com_collation_c_e_idempotente():
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    base, _, _ = DSN.rpartition("/")
    try:
        assert migra.cria_banco(f"{base}/{nome}", saida=lambda *_: None) is True
        assert migra.cria_banco(f"{base}/{nome}", saida=lambda *_: None) is False
        with psycopg.connect(f"{base}/{nome}") as c:
            assert c.execute("SELECT datcollate FROM pg_database "
                             "WHERE datname = current_database()").fetchone()[0] == "C"
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)")


def test_nome_fora_do_padrao_e_recusado(tmp_path):
    (tmp_path / "1_sem_zero.sql").write_text("SELECT 1;")
    with pytest.raises(SystemExit, match="padrão"):
        migra.arquivos(tmp_path)

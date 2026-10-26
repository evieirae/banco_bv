# -*- coding: utf-8 -*-
"""Espelho fiel: o que o Databricks devolve tem de voltar igual pela view compat."""
import datetime
import os
import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import migra  # noqa: E402
from sync import espelho  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"

# Tabelas que o backend cita e que NÃO são espelhadas, com o motivo. Tabela nova no app tem
# de entrar no espelho (sync/espelho_tabelas.py + migração) ou aqui — o teste abaixo recusa
# o esquecimento, que no Postgres viraria resposta vazia em silêncio (_objeto_ausente).
FORA_DO_ESPELHO = {
    "sas_egp_prioridades": "não migra (spec): rotas sem tela",
    "sas_consulta_egp": "não migra (ADR 0004): rotina de consulta fica desligada no Postgres",
    "sas_consulta_egp_dia": "idem",
    "sas_consulta_input": "idem",
    "sas_consulta_input_dia": "idem",
}


# ------------------------------------------------------------------ conversão
def test_texto_fica_como_veio_inclusive_vazio():
    assert espelho.converte("string", "") == "" and espelho.converte("string", " a ") == " a "
    assert espelho.converte("string", None) is None


def test_numeros_booleanos_e_instantes():
    assert espelho.converte("int", "7") == 7 and espelho.converte("bigint", "10233") == 10233
    assert espelho.converte("double", "100.0") == 100.0
    assert espelho.converte("boolean", "false") is False
    assert espelho.converte("timestamp", "2026-06-16 15:53:59.840271") == \
        datetime.datetime(2026, 6, 16, 15, 53, 59, 840271)
    assert espelho.converte("timestamp", "2026-10-14T15:28:33.607Z") == \
        datetime.datetime(2026, 10, 14, 15, 28, 33, 607000)


def test_valor_fora_do_previsto_para_a_sincronizacao():
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("boolean", "sim")
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("timestamp", "2026-06-16 15:53:59-03:00")
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("array<string>", "[]")


def test_selecao_le_instante_como_texto():
    sel = dict(zip(espelho.colunas("sas_inputs_audit"), espelho.selecao("sas_inputs_audit")))
    assert sel["updated_at"] == "CAST(updated_at AS STRING) AS updated_at"
    assert sel["campo"] == "campo"


def test_monta_tabela_ausente_vazia_e_coluna_ausente_nula():
    m = espelho.monta({"sas_funil_area": [{"area": "Cobrança", "qtd_dor1": "168"}]})
    assert m["sas_funil_area"] == [("Cobrança", 168, None, None)]
    assert m["sas_escopo"] == [] and len(m) == len(espelho.TABELAS)


def test_toda_tabela_do_backend_esta_no_espelho_ou_tem_motivo():
    citadas = set()
    for p in BACKEND.glob("*.py"):    # tabela de verdade = nome montado sobre o schema do app
        if not p.name.startswith("test_"):
            citadas |= set(re.findall(r"\{(?:FQ|fq)\}\.(sas_[a-z0-9_]+)", p.read_text(encoding="utf-8")))
    assert len(citadas) > 30          # o padrão ainda acha as tabelas (sanidade do próprio teste)
    sem_destino = citadas - set(espelho.TABELAS) - set(FORA_DO_ESPELHO)
    assert not sem_destino, f"tabelas sem espelho nem motivo: {sorted(sem_destino)}"


# ------------------------------------------------------------------ banco
@pytest.fixture
def banco():
    import psycopg
    nome = "t_esp_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


@precisa_pg
def test_legado_bate_com_a_lista(banco):
    import psycopg
    with psycopg.connect(banco) as c:
        for t in espelho.TABELAS:
            cols = c.execute("SELECT column_name, data_type FROM information_schema.columns "
                             "WHERE table_schema = 'legado' AND table_name = %s ORDER BY ordinal_position",
                             (t,)).fetchall()
            esperado = [(col, "timestamp without time zone" if tipo == "timestamp" else espelho.TIPO_PG[tipo])
                        for col, tipo in espelho.TABELAS[t]]
            assert cols == esperado, t
            vcols = [r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'compat' "
                "AND table_name = %s ORDER BY ordinal_position", (t,))]
            assert vcols == list(espelho.colunas(t)), f"compat.{t}"


def _amostra(tipo, i):
    """Uma célula como o Databricks devolve; varia entre linhas para cobrir '' e NULL."""
    return {"string": ("texto", "", None)[i % 3], "int": ("7", None, "0")[i % 3],
            "bigint": "10233", "double": ("87.5", "100.0", None)[i % 3],
            "boolean": ("true", "false", None)[i % 3],
            "timestamp": ("2026-06-16 15:53:59.840271", "2026-06-23 17:37:46", None)[i % 3]}[tipo]


@precisa_pg
def test_ida_e_volta_pelo_compat_sai_como_no_databricks(banco):
    """Célula pela view compat, formatada pelo driver do app (db_pg.texto), tem de ser o texto
    que o Databricks devolveria. Instante: o JSON do Databricks sai em ms com 'Z', e
    CAST(x AS STRING) sai com os micros, sem fuso — os dois iguais aos do Spark."""
    import psycopg
    import db_pg
    linhas = {t: [{c: _amostra(tipo, i) for c, tipo in cols} for i in range(3)]
              for t, cols in espelho.TABELAS.items()}
    with psycopg.connect(banco) as conn:
        with conn.transaction(), conn.cursor() as cur:
            espelho.carrega(cur, espelho.monta(linhas))
        conn.execute("SET search_path = compat, derivado, pg_catalog, public")
        json_do_databricks = {"2026-06-16 15:53:59.840271": "2026-06-16T15:53:59.840Z",
                              "2026-06-23 17:37:46": "2026-06-23T17:37:46.000Z", None: None}
        for t, cols in espelho.TABELAS.items():
            lidas = [tuple(db_pg.texto(v) for v in r) for r in conn.execute(f"SELECT * FROM compat.{t}")]
            esperadas = [tuple(json_do_databricks[r[c]] if tipo == "timestamp" else r[c]
                               for c, tipo in cols) for r in linhas[t]]
            chave = lambda x: repr(x)  # noqa: E731
            assert sorted(lidas, key=chave) == sorted(esperadas, key=chave), t
        ts = sorted((r[0] or "") for r in conn.execute(
            "SELECT CAST(updated_at AS STRING) FROM compat.sas_inputs_audit"))
        assert ts == ["", "2026-06-16 15:53:59.840271", "2026-06-23 17:37:46"]


@precisa_pg
def test_so_a_sincronizacao_regrava_o_legado(banco):
    import psycopg
    papel = "t_esp_" + uuid.uuid4().hex[:6]
    with psycopg.connect(banco, autocommit=True) as adm:
        adm.execute(f"CREATE ROLE {papel} LOGIN IN ROLE sincronizador")
    try:
        with psycopg.connect(banco) as conn:
            conn.execute(f"SET ROLE {papel}")
            with conn.transaction(), conn.cursor() as cur:
                espelho.carrega(cur, espelho.monta({"sas_funil_area": [{"area": "X", "qtd_dor1": "1"}]}))
        with psycopg.connect(banco) as conn:
            conn.execute("SET ROLE app_leitura")
            assert conn.execute("SELECT area FROM compat.sas_funil_area").fetchall() == [("X",)]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("DELETE FROM legado.sas_funil_area")
    finally:
        with psycopg.connect(banco, autocommit=True) as adm:
            adm.execute(f"DROP OWNED BY {papel}")
            adm.execute(f"DROP ROLE {papel}")


@precisa_pg
def test_toda_tabela_do_legado_tem_os_privilegios_da_sincronizacao(banco):
    """Confere, papel a papel, os privilégios de que app e sincronização precisam em cada tabela do
    espelho. O padrão do legado só dá SELECT; INSERT/DELETE vem tabela a tabela, e o esquecido só
    apareceria na AWS. A mensagem diz qual papel, privilégio e objeto faltou."""
    import psycopg
    with psycopg.connect(banco) as c:
        for t in espelho.TABELAS:
            for papel, objeto, priv in (("app_leitura", f"compat.{t}", "SELECT"),
                                        ("app_leitura", f"legado.{t}", "SELECT"),
                                        ("sincronizador", f"legado.{t}", "SELECT"),
                                        ("sincronizador", f"legado.{t}", "INSERT"),
                                        ("sincronizador", f"legado.{t}", "DELETE")):
                ok = c.execute("SELECT has_table_privilege(%s, %s, %s)", (papel, objeto, priv)).fetchone()[0]
                assert ok, f"{papel} sem {priv} em {objeto}"


@precisa_pg
def test_funcoes_do_spark_que_faltavam(banco):
    import psycopg
    with psycopg.connect(banco) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")
        assert c.execute("SELECT instr('a | B | c', 'B'), instr('abc', 'z'), instr(NULL, 'a')").fetchone() \
            == (5, 0, None)
        assert c.execute("SELECT regexp_extract('tabela::X', '^([^:]+)::', 1), "
                         "regexp_extract('sem', '^([^:]+)::', 1), regexp_extract(NULL, 'a', 1)").fetchone() \
            == ("tabela", "", None)

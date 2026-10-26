# -*- coding: utf-8 -*-
"""Sincronização: leitura sem truncar, de-para fiel e carga atômica com âncoras completas."""
import os
import sys
import uuid
from types import SimpleNamespace as NS

import pytest
from databricks.sdk.service.sql import StatementState

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import carrega, leitor, mapeamento as mp, retrato  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


# ---------------------------------------------------------------- leitor
class _Execucao:
    def __init__(self, chunks, total):
        self._chunks, self._total = chunks, total

    def _chunk(self, i):
        prox = i + 1 if i + 1 < len(self._chunks) else None
        return NS(data_array=self._chunks[i], next_chunk_index=prox)

    def execute_statement(self, **_):
        return NS(statement_id="s1", status=NS(state=StatementState.SUCCEEDED, error=None),
                  result=self._chunk(0), manifest=NS(total_row_count=self._total))

    def get_statement_result_chunk_n(self, sid, i):
        return self._chunk(i)


def test_leitor_segue_todos_os_chunks():
    w = NS(statement_execution=_Execucao([[["a"]], [["b"]], [["c"]]], 3))
    assert leitor.le_tabela(w, "wh", "x.y", ["c"]) == [{"c": "a"}, {"c": "b"}, {"c": "c"}]


def test_leitor_falha_alto_se_o_total_nao_bate():
    w = NS(statement_execution=_Execucao([[["a"]]], 2))
    with pytest.raises(RuntimeError, match="truncamento"):
        leitor.le_tabela(w, "wh", "x.y", ["c"])


# ---------------------------------------------------------------- de-para
def _monitor(**kw):
    # Instantes no formato em que a sincronização lê (CAST(x AS STRING), sessão em UTC).
    base = {"chave_canonica": "tabela::LIB.T", "artifact": "LIB.T", "categoria": "tabela",
            "source_types": "PROC SQL | DATA", "qtd_projetos": "2", "areas": "Cobranças | Riscos",
            "escopo_indi": "true", "modernizada_auto": "A ingerir", "responsavel": "",
            "observacao": None, "updated_at": None, "updated_by": None, "orfao": "false",
            "refreshed_at": "2026-10-13 10:00:00", "origem": "BigQuery",
            "paths_fisicos": None, "etapa": "A Receber", "status": "A Iniciar"}
    base.update(kw)
    return base


def test_input_converte_tipos_e_listas():
    t = mp.input_(_monitor())
    assert t[4] == ["PROC SQL", "DATA"] and t[5] == ["Cobranças", "Riscos"]
    assert t[6] == 2 and t[7] is False and t[8] == [] and t[9] is False


def test_estado_do_publish_leva_a_sentinela():
    e = mp.estado_input(_monitor())
    assert e[1:5] == ("A Receber", "A Iniciar", None, None) and e[6] == mp.SENTINELA_PUBLISH


def test_estado_editado_guarda_quem_e_quando():
    e = mp.estado_input(_monitor(responsavel="Fulano@indicium.ai", updated_by="b@indicium.ai",
                                 updated_at="2026-10-01 12:00:00.000123"))
    assert e[3] == "fulano@indicium.ai" and e[6] == "b@indicium.ai" and e[5].isoformat().startswith("2026-10-01T12:00")


def test_valor_fora_do_previsto_para_tudo():
    with pytest.raises(mp.ValorInesperado):
        mp.input_(_monitor(modernizada_auto="Talvez"))
    with pytest.raises(mp.ValorInesperado):
        mp.input_(_monitor(orfao="sim"))


def test_escopo_seed_vira_nulo_e_id_hex_vira_uuid():
    r = {"id": "0" * 31 + "1", "egp_dor1": "X", "area": "Cobranças", "status_extracao": "exato",
         "projeto": "Cobranças__X", "origem": "csv", "created_by": None, "created_at": "seed",
         "ativo": "true"}
    t = mp.escopo_item(r)
    assert t[0] == "00000000-0000-0000-0000-000000000001" and t[7] is None and t[8] == "seed"


# ---------------------------------------------------------------- carga
def _linhas():
    return {
        "sas_lineage_nodes": [{"projeto": "Cob__A", "area": "Cobranças", "ciclo_id": "0"}],
        "sas_inputs_monitor": [_monitor(responsavel="fulano@indicium.ai",
                                        updated_by="fulano@indicium.ai",
                                        updated_at="2026-10-01 12:00:00.000123")],
        "sas_egp_inputs": [
            {"projeto": "Cob__A", "chave_canonica": "tabela::LIB.T", "artifact": "LIB.T",
             "categoria": "tabela", "source_types": "PROC SQL"},
            {"projeto": "Cob__A", "chave_canonica": "tabela::LIB.T", "artifact": "LIB.T",
             "categoria": "tabela", "source_types": "PROC SQL"},
            {"projeto": "Cob__SUMIU", "chave_canonica": "arquivo::X.CSV", "artifact": "X.CSV",
             "categoria": "arquivo", "source_types": ""}],
        "sas_escopo": [{"id": "a" * 32, "egp_dor1": "A", "area": "Cobranças",
                        "status_extracao": "exato", "projeto": "Cob__A", "origem": "csv",
                        "created_by": None, "created_at": "seed", "ativo": "true"}],
        "sas_analistas": [{"email": "Fulano@indicium.ai", "nome": "Fulano", "ativo": "true",
                           "organograma": "true", "papel": "DE"}],
    }


@pytest.fixture
def banco():
    import psycopg
    nome = "t_sync_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


@precisa_pg
def test_carga_completa_ancoras_e_e_repetivel(banco):
    import psycopg
    ret = retrato.monta(_linhas())
    assert ret["ancoras_acrescentadas"] == {"egp": 1, "input": 1, "pares_duplicados_descartados": 1}
    with psycopg.connect(banco) as conn:
        r1 = carrega.carrega(conn, ret)
        r2 = carrega.carrega(conn, retrato.monta(_linhas()))   # 2ª vez: mesmo resultado
        assert r1["corpus.egp_input"] == r2["corpus.egp_input"] == 2
        conn.execute("SET search_path = compat, derivado, pg_catalog, public")
        orfaos = conn.execute("SELECT projeto FROM corpus.egp WHERE orfao").fetchall()
        assert orfaos == [("Cob__SUMIU",)]
        u = conn.execute("SELECT papel, ativo, cargo FROM cadastro.usuario WHERE email = 'fulano@indicium.ai'").fetchone()
        assert u == ("leitor", False, "DE")          # sincronização nunca dá acesso
        assert conn.execute("SELECT count(*) FROM historico.publicacao WHERE ok").fetchone()[0] == 2
        # compat lê o espelho: devolve o que o Databricks gravou, inclusive o escopo_indi
        linha = conn.execute("SELECT areas, escopo_indi, updated_by FROM compat.sas_inputs_monitor").fetchone()
        assert linha == ("Cobranças | Riscos", True, "fulano@indicium.ai")
        assert r2["espelho"]["sas_inputs_monitor"] == 1 and r2["espelho"]["sas_egp_inputs"] == 3


@precisa_pg
def test_carga_roda_com_o_papel_sincronizador(banco):
    """O login da tarefa ECS só tem o papel `sincronizador` (0004): a carga inteira tem de
    caber nesses privilégios, senão a sincronização de prod falha no primeiro apply."""
    import psycopg
    papel = "t_sync_" + uuid.uuid4().hex[:6]
    with psycopg.connect(banco, autocommit=True) as adm:
        adm.execute(f"CREATE ROLE {papel} LOGIN IN ROLE sincronizador")
    try:
        with psycopg.connect(banco) as conn:
            conn.execute(f"SET ROLE {papel}")
            resumo = carrega.carrega(conn, retrato.monta(_linhas()))
            assert resumo["corpus.input"] == 2
    finally:
        with psycopg.connect(banco, autocommit=True) as adm:
            adm.execute(f"DROP OWNED BY {papel}")
            adm.execute(f"DROP ROLE {papel}")


@precisa_pg
def test_falha_no_meio_nao_troca_o_retrato(banco):
    import psycopg
    with psycopg.connect(banco) as conn:
        carrega.carrega(conn, retrato.monta(_linhas()))
        ruim = retrato.monta(_linhas())
        ruim["trabalho.estado_input"] = [("tabela::NAO_EXISTE",) + ruim["trabalho.estado_input"][0][1:]]
        with pytest.raises(psycopg.Error):
            carrega.carrega(conn, ruim)
        assert conn.execute("SELECT count(*) FROM trabalho.estado_input").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM historico.publicacao").fetchone()[0] == 1

# -*- coding: utf-8 -*-
"""Modo Postgres do backend: despacho do run_sql, DDL nunca enviado, identidade e acesso."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

ENSURES = ["_ensure_analistas_table", "_ensure_responsaveis_bv_table", "_ensure_link_tables",
           "_ensure_dep_mantida_tables", "_ensure_periodo_tables", "_ensure_ingestao_tables",
           "_ensure_out_pipe_table", "_ensure_escopo_ativo", "_ensure_node_metric_cols",
           "_ensure_input_pipeline_cols", "_ensure_pipe_table", "_ensure_prio_snapshot_table",
           "_ensure_gestao_tables", "_ensure_preworking_table", "_ensure_prio_table"]


def test_run_sql_vai_ao_postgres_no_modo_pg(monkeypatch):
    chamadas = []
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m.db_pg, "run", lambda s, w=True, p=None, somente_leitura=False:
                        chamadas.append((s, p)) or [{"x": "1"}])
    assert m.run_sql("SELECT 1 AS x") == [{"x": "1"}]
    assert m.run_sql("SELECT %s AS x", params=(1,)) == [{"x": "1"}]
    assert chamadas == [("SELECT 1 AS x", None), ("SELECT %s AS x", (1,))]


def test_params_no_databricks_e_erro_alto(monkeypatch):
    monkeypatch.setattr(m.dialeto, "PG", False)
    with pytest.raises(ValueError, match="params"):
        m.run_sql("SELECT 1", params=(1,))


@pytest.mark.parametrize("nome", ENSURES)
def test_ensure_nao_manda_ddl_no_postgres(monkeypatch, nome):
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m, "run_sql", lambda *a, **k: pytest.fail(f"{nome} enviou SQL no modo PG"))
    monkeypatch.setattr(m, "_run_sp", lambda *a, **k: pytest.fail(f"{nome} enviou SQL no modo PG"))
    fn = getattr(m, nome)
    getattr(fn, "__wrapped__", fn)()


def _cliente(monkeypatch, papel, somente_leitura=False, email="fulano@bv.com.br"):
    """TestClient no modo PG com identidade dev e cadastro stubado (papel=None: sem cadastro)."""
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m, "IDENTIDADE", "dev")
    monkeypatch.setattr(m, "DEV_USUARIO", email)
    monkeypatch.setattr(m, "SOMENTE_LEITURA", somente_leitura)
    m._sessoes.clear()

    def fake(stmt, want_rows=True, *, params=None):
        if "from cadastro.usuario" in " ".join(stmt.split()).lower():
            return [{"papel": papel}] if papel else []
        return []
    monkeypatch.setattr(m, "run_sql", fake)
    return TestClient(m.app)


def test_sem_cadastro_nao_entra(monkeypatch):
    c = _cliente(monkeypatch, None)
    assert c.get("/api/config").status_code == 403


def test_health_e_me_sao_livres(monkeypatch):
    c = _cliente(monkeypatch, None)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/me").json()["user"] is None


def test_leitor_ve_o_proprio_papel(monkeypatch):
    c = _cliente(monkeypatch, "leitor")
    assert c.get("/api/me").json() == {"user": "fulano@bv.com.br", "papel": "leitor"}


def _rotas_de_escrita():
    for r in m.app.routes:
        for metodo in sorted(getattr(r, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}):
            if getattr(r, "path", "").startswith("/api/"):
                yield metodo, r.path.replace("{", "").replace("}", "")


def test_leitor_nao_escreve_em_rota_nenhuma(monkeypatch):
    c = _cliente(monkeypatch, "leitor")
    rotas = list(_rotas_de_escrita())
    assert len(rotas) >= 28
    for metodo, caminho in rotas:
        r = c.request(metodo, caminho, json={})
        assert r.status_code == 403, f"{metodo} {caminho} -> {r.status_code}"


def test_banco_fora_do_ar_na_checagem_de_acesso_responde_502(monkeypatch):
    """A checagem roda no middleware, FORA dos handlers do FastAPI: sem tratar, a falha do
    banco virava 500 com traceback em vez do 502 "Falha SQL" das rotas."""
    c = _cliente(monkeypatch, "leitor")

    def fora_do_ar(*a, **k):
        raise m.HTTPException(502, "Falha SQL: couldn't get a connection")
    monkeypatch.setattr(m, "run_sql", fora_do_ar)
    r = c.get("/api/config")
    assert r.status_code == 502 and "Falha SQL" in r.json()["detail"]


def test_gestao_tambem_nao_escreve_com_somente_leitura(monkeypatch):
    c = _cliente(monkeypatch, "gestao", somente_leitura=True)
    assert c.patch("/api/inputs", json={}).status_code == 403


def test_config_traz_sincronizacao_e_modo_leitura(monkeypatch):
    c = _cliente(monkeypatch, "leitor", somente_leitura=True)
    monkeypatch.setattr(m, "_sincronizado_em", lambda: "2026-10-14T12:00:00.000Z")
    cfg = c.get("/api/config").json()
    assert cfg["somente_leitura"] is True and cfg["sincronizado_em"] == "2026-10-14T12:00:00.000Z"


def test_quem_nao_e_gestao_ve_so_o_estado_atual_do_com_bv():
    payload = {"rows": [{"id": "A", "bvEventos": [
        {"id": "1", "comBv": True, "data": "2026-10-01", "autor": "x@indicium.ai"},
        {"id": "2", "comBv": False, "data": "2026-10-05", "autor": "y@indicium.ai"}]},
        {"id": "B", "bvEventos": []}]}
    out = m._sem_historico_com_bv(payload)
    assert out["rows"][0]["bvEventos"] == [{"comBv": False, "data": "2026-10-05"}]
    assert out["rows"][1]["bvEventos"] == []
    assert payload["rows"][0]["bvEventos"][0]["autor"] == "x@indicium.ai"   # original intacto (cache)

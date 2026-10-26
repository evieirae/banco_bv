# -*- coding: utf-8 -*-
"""O pré-working do antecessor chega na lista de EGPs atualizados.

A leitura usava `t_egp_pipe`, nome nunca definido em `register` — o NameError caía no
`except Exception` best-effort, então todo antecessor saía com `preworking=None` e cada
GET escrevia um aviso no stderr. run_sql stubado, sem rede."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import egps_atualizados


def test_preworking_do_antecessor_e_lido_do_funil_de_migracao():
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if "from c.s.sas_egp_pipeline " in s and "preworking_preenchido" in s:
            return [{"projeto": "Area__A", "preworking_preenchido": "true",
                     "preworking_data": "2026-10-01"}]
        if "from c.s.sas_egp_atualizados" in s and "row_number()" in s:
            return [{"egp_key": "k1", "versao_id": "v1", "nome": "A v2",
                     "egp_original": "Area__A", "n_inputs": 0, "n_disp": 0,
                     "n_novos": 0, "pct": 100.0, "n_versoes": 1}]
        return []

    app = FastAPI()
    egps_atualizados.register(app, fake_run_sql, "c.s", modern_expr="true",
                              http_exc=HTTPException, enrich_contexto=lambda ctx: None)
    r = TestClient(app).get("/api/egps-atualizados")
    assert r.status_code == 200, r.text
    rows = r.json()["rows"] if isinstance(r.json(), dict) else r.json()
    ant = rows[0]["antecessores"][0]
    assert ant["projeto"] == "Area__A"
    assert ant["preworking"] is True
    assert ant["preworking_data"] == "2026-10-01"

# -*- coding: utf-8 -*-
"""O PATCH da ponte de tipo_vinculo invalida os caches do main.

`/api/egp-readiness` (payload cacheado por geração no main) lê
`sas_egp_atualizados_pipeline.tipo_vinculo`. Sem bump, o rótulo
Atualizado/Substituído/Unificado ficava velho por até 5 min — inclusive para quem
acabou de clicar. run_sql stubado, sem rede."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import egps_atualizados


def _app(on_write):
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if s.startswith("select 1 from c.s.sas_egp_atualizados "):
            return [{"1": 1}]
        return []
    app = FastAPI()
    egps_atualizados.register(app, fake_run_sql, "c.s", modern_expr="true",
                              http_exc=HTTPException, enrich_contexto=lambda ctx: None,
                              on_write=on_write)
    return TestClient(app)


def test_patch_tipo_vinculo_chama_o_gancho_de_invalidacao():
    chamadas = []
    r = _app(lambda: chamadas.append(1)).patch(
        "/api/egp-atualizado-pipeline", json={"egp_key": "k1", "tipo_vinculo": "atualizacao"})
    assert r.status_code == 200, r.text
    assert chamadas == [1]


def test_patch_recusado_nao_invalida():
    chamadas = []
    r = _app(lambda: chamadas.append(1)).patch(
        "/api/egp-atualizado-pipeline", json={"egp_key": "k1", "tipo_vinculo": "invalido"})
    assert r.status_code == 400
    assert chamadas == []


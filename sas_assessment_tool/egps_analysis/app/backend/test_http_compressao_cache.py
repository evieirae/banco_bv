# -*- coding: utf-8 -*-
"""Transporte: JSON grande comprimido e bundle com cache de longo prazo.

Payloads de 1,5-1,8 MB (readiness base, inputs) iam crus; o bundle do Vite (nome com hash)
não tinha Cache-Control e era revalidado a cada visita. Sem rede."""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import main as m


def test_json_grande_sai_comprimido():
    grande = {"rows": [{"projeto": f"Area__EGP_{i}", "etapa": "Conversão do Código"}
                       for i in range(3000)]}
    with patch.object(m, "_egp_readiness_uncached", lambda scope="indi": grande):
        m._endpoint_cache.clear()
        r = TestClient(m.app).get("/api/egp-readiness?scope=indi_deps",
                                  headers={"Accept-Encoding": "gzip"})
        m._endpoint_cache.clear()
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json() == grande


def test_assets_com_hash_sao_imutaveis_e_index_revalida():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "assets"))
        open(os.path.join(d, "index.html"), "w").write("<html></html>")
        open(os.path.join(d, "assets", "index-abc123.js"), "w").write("x")
        app = FastAPI()
        app.mount("/", m._SPAStaticFiles(directory=d, html=False), name="static")
        c = TestClient(app)
        js = c.get("/assets/index-abc123.js")
        rota = c.get("/egps/algum")
        raiz = c.get("/")
    assert "immutable" in js.headers.get("cache-control", "")
    assert rota.headers.get("cache-control") == "no-cache"
    assert raiz.headers.get("cache-control") == "no-cache"

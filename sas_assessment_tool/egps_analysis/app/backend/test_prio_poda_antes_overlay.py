# -*- coding: utf-8 -*-
"""Plano congelado × linha de base: os TOTAIS têm de sair da MESMA lista que a tela mostra.

O snapshot da priorização lista EGPs que já saíram do escopo; `_poda_fora_da_linha_base`
os tira de `meses[].egps`. O overlay (`_overlay_live_attribution`) recalcula `n_egps` do
mês e `resumo.total` — e rodava ANTES da poda, então contava quem a lista já não mostra
(medido 30/09/2026: card 206, lista 193; o mês nunca fechava "completo"). run_sql
stubado, sem rede."""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

PLANO = {
    "meses": [{"mes": 1, "egps": [
        {"projeto": "Area__DENTRO", "etapa": "Conversão", "status": "Em Andamento"},
        {"projeto": "Area__SAIU", "etapa": "Conversão", "status": "Em Andamento"},
    ]}],
    "resumo": {},
}


def _fake_run_sql(stmt, want_rows=True):
    s = " ".join(stmt.split()).lower()
    if "sas_priorizacao_snapshot" in s and s.startswith("select"):
        return [{"payload": json.dumps(PLANO), "saved_by": "x", "saved_at": "2026-09-30"}]
    return []


def test_totais_da_priorizacao_contam_so_a_lista_podada():
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_run_sql),
        patch.object(m, "_linha_base", lambda: {"Area__DENTRO": "base"}),
        patch.object(m, "_ensure_pipe_table", lambda: True),
        patch.object(m, "_vinculos_por_antecessor", lambda: {}),
        patch.object(m, "_blocking", lambda: {"blocked": set()}),
        patch.object(m, "_migrados_mes", lambda frontier: 0),
        patch.object(m, "_prio_live_input_stats", lambda meses: None),
    ]
    for p in patches:
        p.start()
    try:
        r = TestClient(m.app).get("/api/priorizacao")
        assert r.status_code == 200, r.text
        body = r.json()
        listados = [e["projeto"] for mm in body["meses"] for e in mm["egps"]]
        assert listados == ["Area__DENTRO"]
        assert body["meses"][0]["n_egps"] == len(body["meses"][0]["egps"])
        assert body["resumo"]["total"] == len(listados)
        assert body["n_egps"] == len(listados)
        assert body["fora_linha_base"] == 1
    finally:
        for p in patches:
            p.stop()

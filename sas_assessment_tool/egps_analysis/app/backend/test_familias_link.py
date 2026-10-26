#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PATCH /api/egp-input-link numa chave de FAMÍLIA — fan-out para as safras do EGP.

Com o drawer do EGP listando famílias, o botão de vínculo passa a mandar a chave
`familia::...`. Sem fan-out, o MERGE gravaria uma linha em sas_egp_input_link com uma
chave que NUNCA casa com sas_egp_inputs: a tela mostraria "vínculo quebrado" e o app
continuaria contando o input — falha silenciosa, o pior tipo neste app.

O fan-out é só para as safras que AQUELE EGP consome (o vínculo é por par EGP×input).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

FAM_NOME = "GRIMALDI.CARGA_MASSIFICADOS"
FAM = f"familia::tabela::{FAM_NOME}"
SAFRAS = [f"{FAM_NOME}_202501", f"{FAM_NOME}_202502"]
CHAVES = [f"tabela::{a}" for a in SAFRAS]


def _client(safras_no_egp=CHAVES, broken_atual=None):
    reg = {"sql": []}

    def fake_run_sql(stmt, want_rows=True, **kw):
        reg["sql"].append(stmt)
        s = stmt.strip().lower()
        if s.startswith("select") and "sas_egp_inputs" in s:
            return [{"chave_canonica": c} for c in safras_no_egp]
        if s.startswith("select") and "sas_egp_input_link" in s and "audit" not in s:
            return [] if broken_atual is None else [{"link_broken": broken_atual}]
        return []

    ps = [patch.object(m, "run_sql", side_effect=fake_run_sql),
          patch.object(m, "_require_gestao", lambda: True),
          patch.object(m, "_ensure_link_tables", lambda: True),
          patch.object(m, "FAMILIAS_ON", True),
          patch.object(m, "_familias_corpus",
                       lambda: {"chave": {("tabela", a): FAM_NOME for a in SAFRAS},
                                "membros": {("tabela", FAM_NOME): SAFRAS}})]
    for p in ps:
        p.start()
    return TestClient(m.app), reg, ps


def _stop(ps):
    for p in ps:
        p.stop()


def test_familia_quebra_o_vinculo_de_cada_safra():
    c, reg, ps = _client()
    try:
        r = c.patch("/api/egp-input-link", json={
            "projeto": "Cobrancas__Foo", "chave_canonica": FAM, "link_broken": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fan_out"] == {"safras": 2, "alteracoes": 2}
        merges = [s for s in reg["sql"] if "merge into" in s.lower()]
        assert len(merges) == 2
        for ch in CHAVES:
            assert any(ch in s for s in merges), f"{ch} não recebeu o vínculo"
        assert not any(FAM in s for s in merges), "a chave de família não pode ser gravada"
        auds = [s for s in reg["sql"] if "audit" in s.lower() and "insert" in s.lower()]
        assert len(auds) == 2
    finally:
        _stop(ps)


def test_familia_sem_safras_no_egp_e_404():
    c, reg, ps = _client(safras_no_egp=[])
    try:
        r = c.patch("/api/egp-input-link", json={
            "projeto": "Cobrancas__Foo", "chave_canonica": FAM, "link_broken": True})
        assert r.status_code == 404
        assert not any("merge into" in s.lower() for s in reg["sql"])
    finally:
        _stop(ps)


def test_chave_de_safra_segue_com_o_contrato_antigo():
    c, reg, ps = _client()
    try:
        r = c.patch("/api/egp-input-link", json={
            "projeto": "Cobrancas__Foo", "chave_canonica": CHAVES[0], "link_broken": True})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "projeto": "Cobrancas__Foo",
                            "chave_canonica": CHAVES[0], "link_broken": True}
        assert len([s for s in reg["sql"] if "merge into" in s.lower()]) == 1
    finally:
        _stop(ps)


def test_restaurar_vinculo_da_familia_apaga_as_linhas_das_safras():
    c, reg, ps = _client(broken_atual=True)
    try:
        r = c.patch("/api/egp-input-link", json={
            "projeto": "Cobrancas__Foo", "chave_canonica": FAM, "link_broken": False})
        assert r.status_code == 200, r.text
        assert r.json()["fan_out"] == {"safras": 2, "alteracoes": 2}
        dels = [s for s in reg["sql"] if s.strip().lower().startswith("delete")]
        assert len(dels) == 2
    finally:
        _stop(ps)

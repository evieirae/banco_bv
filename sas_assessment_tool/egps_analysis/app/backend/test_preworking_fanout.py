#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checklist de pré-working numa chave de FAMÍLIA: o auto-avanço tem de fazer fan-out.

Irmão de `test_preworking_familia.py`, que cobre a LEITURA (`_pwk_herdadas`: a linha de
família herda o checklist da safra). Aqui é a ESCRITA de estado que o checklist dispara.

O checklist em si é gravado NA chave da família (config de ingestão, uma por família —
ADR 0002), mas etapa/status é estado CONTADO e mora nas SAFRAS. Antes deste teste, o
auto-avanço lia `sas_inputs_monitor WHERE chave_canonica = 'familia::…'`, que não casa
linha nenhuma: o checklist batia 100%, o endpoint respondia 200 com `auto_avancado:false`
e NENHUM input saía de Pré-Working. Silencioso dos dois lados — e a aba ainda pintava a
família de verde.

Stub de `run_sql` no mesmo padrão de test_familias_patch.py — sem warehouse, sem credencial.
"""
import os
import re
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

FAM = "familia::tabela::GRIMALDI.CARGA_MASSIFICADOS"
SAFRAS = ["GRIMALDI.CARGA_MASSIFICADOS_202501",
          "GRIMALDI.CARGA_MASSIFICADOS_202502",
          "GRIMALDI.CARGA_MASSIFICADOS_202503"]
CHAVES = [f"tabela::{a}" for a in SAFRAS]

CHECKLIST_COMPLETO = {
    "chave_canonica": FAM,
    "origem_arquivo": "N:\\base\\arquivo.txt",
    "frequencia": "Mensal",
    "horario": "08:00",
    "tipo_carga": "Full",
    "pos_processamento": "Manter (nenhuma ação)",
    "dados_sensiveis": "Não",
    "recebido": "true",
    "data_recebimento": "2026-09-19",
}


def _client(etapas=None):
    """TestClient com flag ligada, corpus sintético e run_sql stubado.

    `etapas`: etapa corrente de cada safra (default: todas None = nunca tocadas).
    """
    etapas = etapas or {c: None for c in CHAVES}
    reg = {"sql": []}

    def fake_run_sql(stmt, want_rows=True, **kw):
        reg["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_inputs_preworking" in s:
            return []                                   # checklist ainda não existia
        # _chaves_estado: resolve a família -> chaves das safras
        if s.startswith("select") and "upper(artifact) in" in s:
            return [{"chave_canonica": c} for c in CHAVES]
        # leitura do estado corrente das safras, já por chave_canonica IN (...)
        if s.startswith("select") and "chave_canonica, etapa, status" in s:
            return [{"chave_canonica": c, "etapa": etapas[c], "status": None}
                    for c in CHAVES if c in stmt]
        return []

    corpus = {"chave": {("tabela", a): "GRIMALDI.CARGA_MASSIFICADOS" for a in SAFRAS},
              "membros": {("tabela", "GRIMALDI.CARGA_MASSIFICADOS"): list(SAFRAS)}}
    ps = [
        patch.object(m, "FAMILIAS_ON", True),
        patch.object(m, "run_sql", fake_run_sql),
        patch.object(m, "_ensure_preworking_table", lambda: None),
        patch.object(m, "_familias_corpus", lambda: corpus),
    ]
    for p in ps:
        p.start()
    return TestClient(m.app), reg, ps


def _para(ps):
    for p in ps:
        p.stop()


def _updates_no_monitor(reg):
    return [s for s in reg["sql"]
            if " ".join(s.split()).lower().startswith("update")
            and "sas_inputs_monitor" in s]


def test_checklist_de_familia_avanca_todas_as_safras():
    cli, reg, ps = _client()
    try:
        r = cli.patch("/api/inputs/preworking", json=CHECKLIST_COMPLETO)
    finally:
        _para(ps)
    assert r.status_code == 200, r.text
    assert r.json().get("auto_avancado") is True

    ups = _updates_no_monitor(reg)
    assert len(ups) == 1, f"esperado 1 UPDATE no monitor, veio {len(ups)}"
    up = ups[0]
    # escreve nas SAFRAS, nunca na chave de família
    for c in CHAVES:
        assert c in up, f"safra {c} ficou de fora do UPDATE"
    assert FAM not in up, "a chave de família vazou para a escrita de estado"
    assert "Ingestão UAT" in up and "A Iniciar" in up


def test_auditoria_sai_uma_por_safra_e_campo():
    cli, reg, ps = _client()
    try:
        cli.patch("/api/inputs/preworking", json=CHECKLIST_COMPLETO)
    finally:
        _para(ps)
    aud = [s for s in reg["sql"]
           if "sas_inputs_audit" in s and "'Ingestão UAT'" in s]
    assert len(aud) == 1, f"esperado 1 INSERT de auditoria do avanço, veio {len(aud)}"
    # 3 safras x 2 campos (etapa, status) = 6 tuplas
    assert aud[0].count("current_user(), current_timestamp()") == 6
    for c in CHAVES:
        assert c in aud[0]


def test_safra_ja_adiantada_nao_regride():
    """Família mista: só as safras que ainda não passaram de Pré-Working avançam."""
    etapas = {CHAVES[0]: "Ingestão PRD", CHAVES[1]: None, CHAVES[2]: "Pré-Working"}
    cli, reg, ps = _client(etapas)
    try:
        r = cli.patch("/api/inputs/preworking", json=CHECKLIST_COMPLETO)
    finally:
        _para(ps)
    assert r.status_code == 200, r.text
    ups = _updates_no_monitor(reg)
    assert len(ups) == 1
    assert CHAVES[0] not in ups[0], "safra já em Ingestão PRD foi rebaixada para Ingestão UAT"
    assert CHAVES[1] in ups[0] and CHAVES[2] in ups[0]


def test_chave_de_safra_solta_continua_avancando_so_ela():
    """Sem família envolvida o comportamento antigo tem de continuar idêntico."""
    reg = {"sql": []}
    solta = "tabela::LIB.TABELA_SEM_FAMILIA"

    def fake_run_sql(stmt, want_rows=True, **kw):
        reg["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_inputs_preworking" in s:
            return []
        if s.startswith("select") and "chave_canonica, etapa, status" in s:
            return [{"chave_canonica": solta, "etapa": None, "status": None}]
        return []

    ps = [
        patch.object(m, "FAMILIAS_ON", True),
        patch.object(m, "run_sql", fake_run_sql),
        patch.object(m, "_ensure_preworking_table", lambda: None),
        patch.object(m, "_familias_corpus", lambda: {"chave": {}, "membros": {}}),
    ]
    for p in ps:
        p.start()
    try:
        payload = dict(CHECKLIST_COMPLETO, chave_canonica=solta)
        r = cli_patch = TestClient(m.app).patch("/api/inputs/preworking", json=payload)
    finally:
        _para(ps)
    assert cli_patch.status_code == 200, r.text
    ups = _updates_no_monitor(reg)
    assert len(ups) == 1 and solta in ups[0]
    # não pode ter ido ao corpus procurar família para uma chave que não é `familia::`
    assert not any("upper(artifact) in" in " ".join(s.split()).lower() for s in reg["sql"])


def test_helper_chaves_estado_nao_vaza_chave_de_familia():
    """`_chaves_estado` devolve só chaves que existem em sas_inputs_monitor."""
    corpus = {"chave": {("tabela", a): "GRIMALDI.CARGA_MASSIFICADOS" for a in SAFRAS},
              "membros": {("tabela", "GRIMALDI.CARGA_MASSIFICADOS"): list(SAFRAS)}}
    with patch.object(m, "FAMILIAS_ON", True), \
         patch.object(m, "_familias_corpus", lambda: corpus), \
         patch.object(m, "run_sql", lambda *a, **k: [{"chave_canonica": c} for c in CHAVES]):
        assert m._chaves_estado(FAM) == CHAVES
        assert FAM not in m._chaves_estado(FAM)
    # chave comum passa reta, sem consultar nada
    with patch.object(m, "FAMILIAS_ON", True), \
         patch.object(m, "run_sql", _explode):
        assert m._chaves_estado("tabela::LIB.X") == ["tabela::LIB.X"]


def _explode(*a, **k):
    raise AssertionError("não deveria consultar o warehouse para uma chave comum")

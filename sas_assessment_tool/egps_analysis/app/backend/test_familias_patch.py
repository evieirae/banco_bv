#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PATCH /api/inputs numa chave de FAMÍLIA (ticket 03): fan-out + auditoria por safra.

Stub de `run_sql` (mesmo padrão de test_egp_input_link_endpoint.py) — não depende de
warehouse nem de credencial. O que está sob teste é o contrato do fan-out: UPDATE com IN
das safras, uma linha de auditoria por (safra, campo) REALMENTE alterado, e a linha de
família recalculada na resposta.
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


def _membro(art, **kw):
    r = {"chave_canonica": f"tabela::{art}", "artifact": art, "categoria": "tabela",
         "origem": "SAS/Local (externo)", "source_types": "table_in", "qtd_projetos": 1,
         "areas": "Cobranças", "escopo_indi": True, "modernizada_auto": "A ingerir",
         "etapa": None, "status": None, "responsavel": None, "observacao": None,
         "orfao": False, "paths_fisicos": "", "n_paths_fisicos": 0}
    r.update(kw)
    return r


def _client(membros):
    """TestClient com a flag ligada, corpus sintético e run_sql stubado."""
    reg = {"sql": [], "gen": m._lineage_gen}

    def fake_run_sql(stmt, want_rows=True, **kw):
        reg["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_inputs_monitor" in s and "upper(artifact) in" in s:
            return [dict(x) for x in membros]
        return []

    chave = {("tabela", a): "GRIMALDI.CARGA_MASSIFICADOS" for a in SAFRAS}
    corpus = {"chave": chave,
              "membros": {("tabela", "GRIMALDI.CARGA_MASSIFICADOS"): list(SAFRAS)}}
    ps = [
        patch.object(m, "FAMILIAS_ON", True),
        patch.object(m, "run_sql", fake_run_sql),
        patch.object(m, "_ensure_input_pipeline_cols", lambda: None),
        patch.object(m, "_familias_corpus", lambda: corpus),
        patch.object(m, "_familia_egp_counts", lambda: {}),
        patch.object(m, "_autoprodutor_candidatos", lambda: {}),
    ]
    for p in ps:
        p.start()
    return TestClient(m.app), reg, ps


def _stop(ps):
    for p in ps:
        p.stop()


def _updates(reg):
    return [s for s in reg["sql"] if " ".join(s.split()).lower().startswith("update")]


def _audits(reg):
    return [s for s in reg["sql"] if "sas_inputs_audit" in s and "insert" in s.lower()]


def test_fan_out_escreve_em_todas_as_safras_e_audita_cada_uma():
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "etapa": "Recebido",
                                           "status": "Em Andamento"})
        assert r.status_code == 200, r.text
        ups = _updates(reg)
        assert len(ups) == 1
        # UPDATE único com IN das 3 safras (nunca por chave de família — ela não existe na tabela)
        assert "chave_canonica IN (" in ups[0]
        for a in SAFRAS:
            assert f"tabela::{a}" in ups[0]
        assert FAM not in ups[0]
        # auditoria: 3 safras × 2 campos = 6 linhas
        aud = _audits(reg)
        assert len(aud) == 1
        assert aud[0].count("'etapa'") == 3 and aud[0].count("'status'") == 3
        body = r.json()
        assert body["fan_out"] == {"safras": 3, "alteracoes": 6}
        assert (body["etapa"], body["status"]) == ("Recebido", "Em Andamento")
        assert body["is_familia"] is True and body["n_safras"] == 3
    finally:
        _stop(ps)


def test_fan_out_sobrescreve_sanitizado_e_zera_estado_misto():
    """Consequência aceita no ADR 0002: marcar a família como pendente derruba o
    `Sanitizado` das safras fora da janela — e o antes fica na auditoria."""
    membros = [_membro(SAFRAS[0], status="Sanitizado", observacao="fora da janela 12M"),
               _membro(SAFRAS[1], status="Sanitizado"),
               _membro(SAFRAS[2], etapa="A Receber", status="A Iniciar")]
    cli, reg, ps = _client(membros)
    try:
        r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "status": "A Iniciar"})
        assert r.status_code == 200, r.text
        aud = _audits(reg)[0]
        # as duas Sanitizadas entram na auditoria com o valor antigo; a que já estava
        # "A Iniciar" não gera linha (sem mudança real)
        assert aud.count("'Sanitizado'") == 2
        assert "'A Iniciar'" in aud
        body = r.json()
        assert body["fan_out"]["alteracoes"] == 2
        assert body["estado_misto"] is False       # as 3 safras convergiram
        assert body["status"] == "A Iniciar"
    finally:
        _stop(ps)


def test_sem_mudanca_real_em_nenhuma_safra_da_400():
    membros = [_membro(a, responsavel="ana@x") for a in SAFRAS]
    cli, reg, ps = _client(membros)
    try:
        r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "responsavel": "ana@x"})
        assert r.status_code == 400
        assert not _updates(reg) and not _audits(reg)
    finally:
        _stop(ps)


def test_autoprodutor_exige_pelo_menos_uma_safra_candidata():
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "status": "Autoprodutor"})
        assert r.status_code == 400
        assert "Autoprodutor" in r.text
        assert not _updates(reg)
    finally:
        _stop(ps)


def test_autoprodutor_aceito_quando_uma_safra_e_candidata():
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        with patch.object(m, "_autoprodutor_candidatos",
                          lambda: {f"tabela::{SAFRAS[1]}": "Cobranças__X"}):
            r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "status": "Autoprodutor"})
        assert r.status_code == 200, r.text
        assert len(_updates(reg)) == 1
    finally:
        _stop(ps)


def test_chave_de_safra_nao_faz_fan_out():
    """Edição numa safra (drawer do EGP ainda lista safras) escreve só nela."""
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        # o caminho de safra faz SELECT do estado atual; o stub devolve [] -> 404,
        # e o que importa é que NÃO passou pelo fan-out (nenhum UPDATE com IN)
        r = cli.patch("/api/inputs", json={"chave_canonica": f"tabela::{SAFRAS[0]}",
                                           "etapa": "Recebido"})
        assert r.status_code == 404
        assert not [u for u in _updates(reg) if "IN (" in u]
    finally:
        _stop(ps)


def test_familia_sem_safras_no_corpus_da_404():
    cli, reg, ps = _client([])
    try:
        r = cli.patch("/api/inputs", json={"chave_canonica": FAM, "etapa": "Recebido"})
        assert r.status_code == 404
    finally:
        _stop(ps)


def test_bump_de_geracao_invalida_os_caches():
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        antes = m._lineage_gen
        cli.patch("/api/inputs", json={"chave_canonica": FAM, "etapa": "Recebido"})
        assert m._lineage_gen > antes
    finally:
        _stop(ps)


def test_update_nao_escreve_a_chave_de_familia_em_nenhuma_tabela():
    """A chave `familia::` é de transporte: não pode virar linha em tabela chaveada por
    chave_canonica real (senão o publish a marcaria órfã e ela viraria lixo permanente)."""
    cli, reg, ps = _client([_membro(a) for a in SAFRAS])
    try:
        cli.patch("/api/inputs", json={"chave_canonica": FAM, "etapa": "Recebido"})
        escritas = [s for s in reg["sql"]
                    if re.match(r"\s*(update|insert)", s, re.I)]
        assert escritas
        for s in escritas:
            assert FAM not in s
    finally:
        _stop(ps)

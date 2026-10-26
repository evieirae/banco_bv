# -*- coding: utf-8 -*-
"""Testes do vínculo no PATCH /api/egp-pipeline. run_sql stubado — sem credencial, sem rede."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m


def _mk_client(pipe_rows=None, projetos_corpus=("Cobranças__X__ATU20260923",)):
    """TestClient com run_sql stubado. `pipe_rows` é o que o SELECT de sas_egp_pipeline
    devolve; `projetos_corpus` é quem existe em sas_lineage_nodes (guarda do sucessor)."""
    calls = {"sql": []}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_egp_pipeline" in s and "limit 0" not in s:
            return list(pipe_rows or [])
        if s.startswith("select") and "sas_lineage_nodes" in s:
            # honra o WHERE da query: devolver a lista inteira faria a guarda do
            # sucessor passar sempre, escondendo o que o teste quer provar.
            return [{"projeto": p} for p in projetos_corpus if p.lower() in s]
        return []

    patches = [
        patch.object(m, "run_sql", side_effect=fake_run_sql),
        patch.object(m, "_require_gestao", lambda: None),
        patch.object(m, "_ensure_pipe_table", lambda: True),
    ]
    for p in patches:
        p.start()
    return TestClient(m.app), calls, patches


def _stop(patches):
    for p in patches:
        p.stop()


def test_patch_aceita_tipo_e_sucessor():
    client, calls, patches = _mk_client()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 200, r.text
        gravado = " ".join(" ".join(calls["sql"]).split())
        assert "egp_vinculo_tipo" in gravado
        assert "egp_sucessor" in gravado
    finally:
        _stop(patches)


def test_patch_recusa_tipo_invalido():
    client, _calls, patches = _mk_client()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Trocado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 400
        assert "tipo de vínculo" in r.text.lower()
    finally:
        _stop(patches)


def _nega_gestao():
    from fastapi import HTTPException
    raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")


def test_recusa_vinculo_de_quem_nao_e_gestao():
    # Classificar como Substituído faz um EGP entrar no escopo e outro fechar: é decisão de
    # escopo, com o mesmo peso de um DOR1 (spec §3.5.19).
    client, _calls, patches = _mk_client()
    patch_g = patch.object(m, "_require_gestao", side_effect=_nega_gestao)
    patch_g.start()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 403
    finally:
        patch_g.stop()
        _stop(patches)


def test_etapa_e_status_seguem_abertos_sem_gestao():
    # A guarda é SÓ dos campos de vínculo: editar etapa/status continua aberto, como hoje.
    client, _calls, patches = _mk_client(pipe_rows=[
        {"et": "Pré-conversão", "st": "Em Andamento"}])
    patch_g = patch.object(m, "_require_gestao", side_effect=_nega_gestao)
    patch_g.start()
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 200, r.text
    finally:
        patch_g.stop()
        _stop(patches)


def test_recusa_sucessor_fora_do_corpus():
    # O ponteiro só pode apontar para projeto que já existe: antes disso o espelhamento
    # agiria sobre o vazio (spec §2, etapa 3).
    client, _calls, patches = _mk_client(projetos_corpus=("Cobranças__Outro",))
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 404
        assert "corpus" in r.text.lower()
    finally:
        _stop(patches)


def test_recusa_vincular_egp_migrado():
    client, _calls, patches = _mk_client(pipe_rows=[{"et": "Migrado", "st": "Migrado"}])
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 409
        assert "migrado" in r.text.lower()
    finally:
        _stop(patches)


def test_recusa_editar_etapa_espelhada():
    client, _calls, patches = _mk_client(pipe_rows=[
        {"et": "Pré-conversão", "st": "Em Andamento", "vinc_tipo": "Atualizado",
         "sucessor": "Cobranças__X__ATU20260923"}])
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 409
        assert "espelh" in r.text.lower()
    finally:
        _stop(patches)


def test_permite_editar_etapa_em_substituido():
    # Substituído não espelha: a etapa do antecessor continua editável.
    client, _calls, patches = _mk_client(pipe_rows=[
        {"et": "Pré-conversão", "st": "Em Andamento", "vinc_tipo": "Substituído",
         "sucessor": "Cobranças__Novo"}])
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 200, r.text
    finally:
        _stop(patches)


def test_recusa_auto_vinculo_e_nao_grava():
    """O pareamento SUGERE `X -> X` sozinho quando o egp_key de sas_egp_atualizados
    coincide com o projeto do corpus — 2 das 26 sugestões medidas em 02/10/2026. Os
    percorredores de cadeia sobrevivem ao ciclo, mas o dado é indefensável: o EGP vira
    extra e espelha a própria etapa."""
    client, calls, patches = _mk_client(projetos_corpus=("Cobranças__X",))
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X"})
        assert r.status_code == 409, r.text
        assert "si mesmo" in r.json()["detail"]
        gravado = " ".join(" ".join(calls["sql"]).split()).lower()
        assert "merge into" not in gravado and "update " not in gravado
    finally:
        _stop(patches)

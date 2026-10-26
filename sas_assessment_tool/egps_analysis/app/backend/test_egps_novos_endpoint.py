# -*- coding: utf-8 -*-
"""Testes do PATCH/GET /api/egps-novos (ticket 24). run_sql stubado — sem credencial, sem rede.

A 3ª perna do `extra` (`novo`) era a única que só existia como linha escrita por script no
warehouse. O que estes testes protegem não é o caminho feliz — é que as três RECUSAS do
ticket falhem alto e **não gravem nada**: declarar quem não existe cria um extra fantasma
que ninguém consegue rastrear até um clique.
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

LB = {"Cobranças__NaBase": "base"}


def _mk(declarados=(), corpus=("Cobranças__Fora",), vinc=None, cascas=()):
    calls = {"sql": []}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_app_config" in s:
            return [{"valor": json.dumps(list(declarados))}]
        if s.startswith("select") and "sas_lineage_nodes" in s:
            # honra o WHERE: devolver tudo faria a guarda do corpus passar sempre.
            if " where " in s:
                return [{"projeto": p} for p in corpus if p.lower() in s]
            return [{"projeto": p} for p in corpus]
        return []

    patches = [
        patch.object(m, "run_sql", side_effect=fake_run_sql),
        patch.object(m, "_require_gestao", lambda: None),
        patch.object(m, "_linha_base", lambda: dict(LB)),
        patch.object(m, "_vinculos_por_antecessor", lambda: dict(vinc or {})),
        patch.object(m, "_cascas", lambda: set(cascas)),
    ]
    for p in patches:
        p.start()
    return TestClient(m.app), calls, patches


def _stop(ps):
    for p in ps:
        p.stop()


def _gravou(calls):
    j = " ".join(" ".join(calls["sql"]).split()).lower()
    return "merge into" in j or "insert into" in j


# ---- caminho feliz -------------------------------------------------------------------

def test_declarar_grava_a_lista_e_audita():
    client, calls, ps = _mk()
    try:
        r = client.patch("/api/egps-novos",
                         json={"projeto": "Cobranças__Fora", "acao": "declarar"})
        assert r.status_code == 200, r.text
        assert r.json()["declarados"] == ["Cobranças__Fora"]
        j = " ".join(" ".join(calls["sql"]).split()).lower()
        assert "merge into" in j and "sas_app_config" in j
        assert "sas_pipeline_audit" in j and "'(config)'" in j
        assert "updated_by" in j and "updated_at" in j   # a dívida do seed de 29/09
    finally:
        _stop(ps)


def test_declarar_bumpa_a_geracao():
    """Sem bump, o contador '(+N extra)' seguiria servindo a geração anterior."""
    client, _, ps = _mk()
    try:
        antes = m._lineage_gen
        client.patch("/api/egps-novos", json={"projeto": "Cobranças__Fora"})
        assert m._lineage_gen > antes
    finally:
        _stop(ps)


def test_remover_tira_da_lista():
    client, calls, ps = _mk(declarados=["Cobranças__Fora"])
    try:
        r = client.patch("/api/egps-novos",
                         json={"projeto": "Cobranças__Fora", "acao": "remover"})
        assert r.status_code == 200, r.text
        assert r.json()["declarados"] == []
        assert _gravou(calls)
    finally:
        _stop(ps)


# ---- as três recusas do ticket, nenhuma grava ----------------------------------------

def test_recusa_fora_do_corpus_404_e_nao_grava():
    client, calls, ps = _mk(corpus=())
    try:
        r = client.patch("/api/egps-novos", json={"projeto": "Cobranças__Fantasma"})
        assert r.status_code == 404, r.text
        assert "não está no corpus" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_recusa_na_linha_base_409_e_nao_grava():
    """Hoje `_egps_novos` descartaria em silêncio na leitura; quem clicou merece saber."""
    client, calls, ps = _mk(corpus=("Cobranças__NaBase",))
    try:
        r = client.patch("/api/egps-novos", json={"projeto": "Cobranças__NaBase"})
        assert r.status_code == 409, r.text
        assert "linha de base" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_recusa_quem_ja_e_sucessor_409_e_nao_grava():
    """O vínculo vence a declaração, então declarar seria um no-op enganoso."""
    vinc = {"Cobranças__Velho": {"sucessor": "Cobranças__Fora", "tipo": "Atualizado"}}
    client, calls, ps = _mk(vinc=vinc)
    try:
        r = client.patch("/api/egps-novos", json={"projeto": "Cobranças__Fora"})
        assert r.status_code == 409, r.text
        assert "sucessor" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_recusa_casca_409():
    client, calls, ps = _mk(cascas=("Cobranças__Fora",))
    try:
        r = client.patch("/api/egps-novos", json={"projeto": "Cobranças__Fora"})
        assert r.status_code == 409, r.text
        assert "casca" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_recusa_declarar_duas_vezes():
    client, calls, ps = _mk(declarados=["Cobranças__Fora"])
    try:
        r = client.patch("/api/egps-novos", json={"projeto": "Cobranças__Fora"})
        assert r.status_code == 409 and "já está declarado" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_recusa_remover_o_que_nao_esta_declarado():
    client, calls, ps = _mk()
    try:
        r = client.patch("/api/egps-novos",
                         json={"projeto": "Cobranças__Fora", "acao": "remover"})
        assert r.status_code == 404 and "não está declarado" in r.json()["detail"]
        assert not _gravou(calls)
    finally:
        _stop(ps)


def test_acao_invalida_400():
    client, calls, ps = _mk()
    try:
        r = client.patch("/api/egps-novos",
                         json={"projeto": "Cobranças__Fora", "acao": "apagar"})
        assert r.status_code == 400
        assert not _gravou(calls)
    finally:
        _stop(ps)


# ---- leitura -------------------------------------------------------------------------

def test_get_marca_redundante_quando_o_egp_ganhou_vinculo():
    """A declaração vira letra morta quando o EGP passa a ser sucessor — a lista precisa
    dizer isso, senão vira depósito de declarações que ninguém sabe se ainda valem."""
    vinc = {"Cobranças__Velho": {"sucessor": "Cobranças__Fora", "tipo": "Atualizado"}}
    client, _, ps = _mk(declarados=["Cobranças__Fora"], vinc=vinc)
    try:
        r = client.get("/api/egps-novos")
        assert r.status_code == 200, r.text
        linha = r.json()["rows"][0]
        assert linha["redundante"] is True
        assert linha["motivo_sem_declaracao"] == "sucessor"
    finally:
        _stop(ps)


def test_get_nao_marca_redundante_quem_so_e_extra_pela_declaracao():
    client, _, ps = _mk(declarados=["Cobranças__Fora"])
    try:
        linha = client.get("/api/egps-novos").json()["rows"][0]
        assert linha["redundante"] is False
        assert linha["motivo_sem_declaracao"] is None
        assert linha["no_corpus"] is True
    finally:
        _stop(ps)


def test_raw_nao_filtra_linha_base_mas_a_leitura_filtra():
    """`_egps_novos` esconde quem entrou na linha de base; a lista EDITÁVEL não pode
    esconder, senão remover esse item seria um clique sem efeito."""
    client, _, ps = _mk(declarados=["Cobranças__NaBase", "Cobranças__Fora"])
    try:
        assert set(m._egps_novos_raw()) == {"Cobranças__NaBase", "Cobranças__Fora"}
        assert m._egps_novos() == {"Cobranças__Fora"}
    finally:
        _stop(ps)

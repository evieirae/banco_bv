# -*- coding: utf-8 -*-
"""Infra de leitura: cliente por token, cache compartilhado com single-flight e a prova
de leitura que substitui o token na chave.

Medido em prod (06/10/2026): ~1 s por statement, 0,4 s dele só de construir cliente e
abrir conexão; cache por (token, geração global) recalculando o mesmo frontier N vezes —
uma por usuário, e várias vezes por usuário quando o prefetch dispara ~20 GETs juntos.
run_sql/WorkspaceClient stubados, sem rede."""
import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import HTTPException
from backend import main as m


@pytest.fixture(autouse=True)
def _limpo():
    m._lineage_cache.clear()
    m._endpoint_cache.clear()
    m._sessoes.clear()
    m._clientes.clear()
    yield
    m._lineage_cache.clear()
    m._endpoint_cache.clear()
    m._sessoes.clear()
    m._clientes.clear()
    m._user_token.set(None)


# ---- cliente OBO reaproveitado por token -------------------------------------------
def test_mesmo_token_reusa_o_cliente_e_token_novo_cria_outro():
    criados = []

    class _Fake:
        def __init__(self, **kw):
            criados.append(kw["token"])

    class _SP:
        class config:
            host = "https://h"

    with patch.object(m, "WorkspaceClient", _Fake), patch.object(m, "_sp_client", lambda: _SP):
        a1 = m._user_client("tok-a")
        a2 = m._user_client("tok-a")
        b = m._user_client("tok-b")
    assert a1 is a2
    assert b is not a1
    assert criados == ["tok-a", "tok-b"]


# ---- single-flight -----------------------------------------------------------------
def test_requests_concorrentes_da_mesma_chave_produzem_uma_vez():
    chamadas = []
    liberar = threading.Event()

    def produz():
        chamadas.append(1)
        liberar.wait(2)
        return {"v": 1}

    res = []
    ts = [threading.Thread(target=lambda: res.append(m._cache_lineage(("k",), produz)))
          for _ in range(6)]
    for t in ts:
        t.start()
    time.sleep(0.2)
    liberar.set()
    for t in ts:
        t.join(3)
    assert len(chamadas) == 1
    assert res == [{"v": 1}] * 6


def test_quem_chega_depois_do_bump_nao_espera_calculo_antigo():
    """Leitura que começou ANTES de uma edição não pode ser servida a quem pediu DEPOIS."""
    iniciou, liberar = threading.Event(), threading.Event()

    def antigo():
        iniciou.set()
        liberar.wait(2)
        return "pre-edicao"

    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", m._cache_lineage(("k",), antigo)))
    t.start()
    iniciou.wait(2)
    m._bump_gen()
    out["b"] = m._cache_lineage(("k",), lambda: "pos-edicao")
    liberar.set()
    t.join(3)
    assert out["b"] == "pos-edicao"
    assert m._cache_lineage(("k",), lambda: "x") == "pos-edicao"


def test_falha_do_produtor_nao_fica_no_cache():
    def falha():
        raise HTTPException(502, "Falha SQL: timeout")

    with pytest.raises(HTTPException):
        m._cache_lineage(("k",), falha)
    assert m._cache_lineage(("k",), lambda: "ok") == "ok"


# ---- cache compartilhado + prova de leitura por token ------------------------------
def _sessao_sql(ok_tokens):
    def fake(stmt, want_rows=True):
        if "current_user()" in stmt and "sas_inputs_monitor" in stmt:
            tok = m._user_token.get()
            if tok not in ok_tokens:
                raise HTTPException(403, "Sem permissão para este recurso")
            return [{"u": f"{tok}@x", "g": "true", "a": "false", "leitura": "1"}]
        return []
    return fake


def test_dois_usuarios_compartilham_o_calculo():
    prod = []
    with patch.object(m, "run_sql", side_effect=_sessao_sql({"A", "B"})):
        m._user_token.set("A")
        v1 = m._cache_lineage(("k",), lambda: prod.append(1) or "v")
        m._user_token.set("B")
        v2 = m._cache_lineage(("k",), lambda: prod.append(1) or "v")
    assert v1 == v2 == "v"
    assert prod == [1]


def test_usuario_sem_leitura_no_schema_nao_recebe_o_cache():
    with patch.object(m, "run_sql", side_effect=_sessao_sql({"A"})):
        m._user_token.set("A")
        m._cache_lineage(("k",), lambda: "segredo")
        m._user_token.set("C")
        with pytest.raises(HTTPException) as e:
            m._cache_lineage(("k",), lambda: "segredo")
    assert e.value.status_code == 403


def test_sessao_e_uma_query_por_token_e_responde_grupos():
    sql = []

    def fake(stmt, want_rows=True):
        sql.append(stmt)
        return _sessao_sql({"A"})(stmt, want_rows)

    with patch.object(m, "run_sql", side_effect=fake):
        m._user_token.set("A")
        assert m._is_gestao() is True
        assert m._is_admin() is False
        assert m.me() == {"user": "A@x"}
    assert len(sql) == 1


# ---- eviction ----------------------------------------------------------------------
def test_eviction_tira_geracao_velha_antes_de_esvaziar():
    for i in range(m._CACHE_MAX):
        m._cache_lineage(("velho", i), lambda: i)
    m._bump_gen()
    m._cache_lineage(("novo",), lambda: "n")
    m._cache_lineage(("novo2",), lambda: "n2")
    assert ("novo",) in m._lineage_cache
    assert not any(k[0] == "velho" for k in m._lineage_cache)

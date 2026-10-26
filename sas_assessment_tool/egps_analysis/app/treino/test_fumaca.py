# -*- coding: utf-8 -*-
"""Fumaça: passa com o app saudável e aponta exatamente o que quebrou."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from treino import fumaca  # noqa: E402

SAUDAVEL = {
    ("GET", "/api/health"): (200, "{}"),
    ("GET", "/api/me"): (200, json.dumps({"user": "treino@indicium.ai", "papel": "gestao"})),
    ("GET", "/api/config"): (200, json.dumps({"somente_leitura": True, "sincronizado_em": "2026-10-15T12:00:00.000Z"})),
    ("PATCH", "/api/inputs"): (403, '{"detail": "Somente leitura."}'),
    ("GET", "/"): (200, "<!doctype html><html></html>"),
}


def _pede_de(respostas):
    return lambda base, caminho, metodo="GET": respostas[(metodo, caminho)]


def test_app_saudavel_passa_em_tudo():
    res = fumaca.verifica("http://x", "Treino@indicium.ai", pede=_pede_de(SAUDAVEL))
    assert all(ok for ok, _ in res) and len(res) == 5


def test_escrita_liberada_e_falha():
    r = dict(SAUDAVEL)
    r[("PATCH", "/api/inputs")] = (200, "{}")
    res = fumaca.verifica("http://x", pede=_pede_de(r))
    assert [ok for ok, _ in res] == [True, True, True, False, True]


def test_sem_sincronizacao_e_falha():
    r = dict(SAUDAVEL)
    r[("GET", "/api/config")] = (200, json.dumps({"somente_leitura": True, "sincronizado_em": None}))
    assert not fumaca.verifica("http://x", pede=_pede_de(r))[2][0]


def test_usuario_errado_e_falha():
    assert not fumaca.verifica("http://x", "outro@indicium.ai", pede=_pede_de(SAUDAVEL))[1][0]

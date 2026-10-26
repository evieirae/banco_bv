# -*- coding: utf-8 -*-
"""Login na AWS (IDENTIDADE=alb): o load balancer deixa tudo chegar ao app (allow) e só
/login/google força o Google. Sem login, a única coisa aberta é a página /login; logado,
ninguém mais é desviado para ela."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

LOGADO = {"x-amzn-oidc-data": "token-de-teste"}


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m, "IDENTIDADE", "alb")
    def email(token, signer):  # assinatura conferida em test_auth_alb; aqui só presença
        if not token:
            raise m.auth_alb.IdentidadeInvalida("cabeçalho x-amzn-oidc-data ausente")
        return "fulano@bv.com.br"
    monkeypatch.setattr(m.auth_alb, "email_do_cabecalho", email)
    m._sessoes.clear()

    def fake(stmt, want_rows=True, *, params=None):
        if "from cadastro.usuario" in " ".join(stmt.split()).lower():
            return [{"papel": "leitor"}]
        return []
    monkeypatch.setattr(m, "run_sql", fake)
    return TestClient(m.app, follow_redirects=False)


def _destino(r):
    assert r.status_code == 302, r.status_code
    return r.headers["location"]


def test_sem_login_a_raiz_vai_para_a_pagina_de_login(c):
    assert _destino(c.get("/")) == "/login?volta=%2F"


def test_sem_login_o_link_direto_volta_para_onde_ia(c):
    assert _destino(c.get("/egps/abc?aba=inputs")) == "/login?volta=%2Fegps%2Fabc%3Faba%3Dinputs"


def test_sem_login_o_front_nao_fica_publico(c):
    assert _destino(c.get("/assets/index-abc.js")).startswith("/login?")


def test_sem_login_a_api_responde_401_com_o_caminho_do_login(c):
    for rota in ("/api/inputs", "/api/me"):
        r = c.get(rota)
        assert r.status_code == 401, rota
        assert r.json()["entrar"] == "/login"


def test_health_segue_aberto_para_o_load_balancer(c):
    assert c.get("/api/health").status_code == 200


def test_pagina_de_login_tem_o_botao_que_leva_ao_google(c):
    r = c.get("/login?volta=/egps/abc")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'href="/login/google?volta=%2Fegps%2Fabc"' in r.text
    assert "Entrar com Google" in r.text


def test_logado_nao_ve_mais_a_pagina_de_login(c):
    assert _destino(c.get("/login?volta=/egps/abc", headers=LOGADO)) == "/egps/abc"


def test_depois_do_google_volta_para_onde_ia(c):
    assert _destino(c.get("/login/google?volta=/egps/abc", headers=LOGADO)) == "/egps/abc"


@pytest.mark.parametrize("volta", ["//evil.com", "https://evil.com", "/\\evil.com", "/\t/evil.com",
                                   "/login", "/login/google", "", "egps"])
def test_volta_para_fora_do_app_cai_na_raiz(c, volta):
    assert _destino(c.get("/login/google", params={"volta": volta}, headers=LOGADO)) == "/"


def test_login_google_sem_sessao_volta_para_a_pagina_de_login(c):
    # sem a regra do load balancer em /login/google o pedido chega sem login: não entra em laço
    assert _destino(c.get("/login/google?volta=/egps/abc")) == "/login?volta=%2Fegps%2Fabc"


def test_logado_navega_sem_desvio(c):
    assert c.get("/", headers=LOGADO).status_code == 200
    assert c.get("/api/me", headers=LOGADO).json() == {"user": "fulano@bv.com.br", "papel": "leitor"}


def test_fora_do_modo_alb_nada_muda(c, monkeypatch):
    monkeypatch.setattr(m, "IDENTIDADE", "dev")
    monkeypatch.setattr(m, "DEV_USUARIO", "fulano@bv.com.br")
    assert c.get("/").status_code == 200

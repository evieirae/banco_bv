# -*- coding: utf-8 -*-
"""Comparador de leituras: normaliza forma, nunca conteúdo; ordem continua contando."""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paridade import compara as c  # noqa: E402


def test_forma_nao_e_diferenca():
    antigo = {"n": "12", "vazio": "", "ts": "2026-10-14T15:04:05.123Z", "flag": "true"}
    novo = {"n": "12.0", "vazio": None, "ts": "2026-10-14 15:04:05+00:00", "flag": "true"}
    assert c.diferencas(c.normaliza(antigo), c.normaliza(novo)) == []


def test_conteudo_e_diferenca():
    dif = c.diferencas(c.normaliza({"n": "12"}), c.normaliza({"n": "13"}))
    assert dif == [("$.n", 12.0, 13.0)]


def test_identificador_com_zero_a_esquerda_continua_texto():
    assert c.normaliza("0012") == "0012"


def test_ordem_diferente_e_diferenca_marcada_como_so_ordem():
    a, b = [{"x": 1}, {"x": 2}], [{"x": 2}, {"x": 1}]
    assert c.diferencas(c.normaliza(a), c.normaliza(b))
    assert c.so_ordem(c.normaliza(a), c.normaliza(b))


def test_compara_registra_erro_de_rota_sem_parar():
    def busca(base, rota):
        if rota == "/api/quebra":
            raise RuntimeError("502")
        return {"ok": True}
    rel = c.compara("http://a", "http://b", ["/api/ok", "/api/quebra"], busca=busca)
    assert rel["/api/ok"]["igual"] and "erro" in rel["/api/quebra"]


def test_rotas_get_ignora_parametro_de_caminho_e_metodo_de_escrita():
    app = NS(routes=[NS(path="/api/a", methods={"GET"}), NS(path="/api/b/{id}", methods={"GET"}),
                     NS(path="/api/c", methods={"PATCH"}), NS(path="/static", methods={"GET"})])
    assert c.rotas_get(app) == ["/api/a"]


def test_lista_sem_ordem_na_origem_compara_como_multiconjunto():
    livres = (("$.blocked", "set"),)
    assert c.diferencas({"blocked": ["a", "b"]}, {"blocked": ["b", "a"]}, livres=livres) == []
    assert c.diferencas({"blocked": ["a", "b"]}, {"blocked": ["b", "c"]}, livres=livres) \
        == [("$.blocked[multiconjunto]", 2, 2)]
    assert c.diferencas({"outra": ["a", "b"]}, {"outra": ["b", "a"]}, livres=livres) != []


def test_diferenca_por_desenho_sai_a_parte_e_rota_fora_nao_e_buscada():
    vistos = []

    def busca(base, rota):
        vistos.append(rota)
        return {"table": base, "ok": True}

    rel = c.compara("http://antigo", "http://novo", ["/api/health", "/api/prioridades"], busca=busca)
    assert rel["/api/health"]["igual"] and rel["/api/health"]["aceitas"][0][0] == "$.table"
    assert rel["/api/prioridades"]["fora"] and "/api/prioridades" not in vistos


def test_mesmo_erro_http_nos_dois_lados_e_igual_e_erro_de_um_lado_so_nao():
    import urllib.error

    def busca(base, rota):
        if rota == "/api/precisa-param" or base == "http://novo":
            raise urllib.error.HTTPError(base + rota, 422 if rota == "/api/precisa-param" else 502,
                                         "x", {}, None)
        return {"ok": True}

    rel = c.compara("http://antigo", "http://novo", ["/api/precisa-param", "/api/so-novo-quebra"], busca=busca)
    assert rel["/api/precisa-param"] == {"igual": True, "mesmo_erro": 422}
    assert "erro" in rel["/api/so-novo-quebra"]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profundidade INGERIDA + avisos da família — ticket 08.

Os avisos são informativos por decisão de desenho (Q13): campo manual esquecido não pode
virar bloqueio. Os testes fixam isso — nenhum aviso muda etapa/status/contagem — e cobrem a
régua de "carga rasa", que compara FATO (ingerida) com PEDIDO (necessária).
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as M  # noqa: E402


def _par(pj, tipo, valor=None, esparso=False):
    return {"projeto": pj, "tipo": tipo, "valor": valor, "esparso": esparso,
            "piso": M._periodo_piso(tipo, valor)}


# ---------------------------------------------------------------- carga rasa

def test_rasa_lista_quem_a_carga_nao_alcanca():
    pares = [_par("fundo", "desde", "202301"), _par("medio", "desde", "202401"),
             _par("raso", "desde", "202506")]
    av = M._avisos_familia(pares, None, {"desde": "202404"})
    assert av["rasa"]["n"] == 2 and av["rasa"]["de"] == 3
    assert av["rasa"]["mais_fundo"] == "fundo"
    assert av["rasa"]["precisa"] == "202301"
    assert set(av["rasa"]["projetos"]) == {"fundo", "medio"}


def test_sem_ingerida_nao_ha_aviso_de_rasa():
    """Vazio é estado NORMAL: sem registro não há o que comparar, e inventar default
    seria pior que não avisar."""
    pares = [_par("A", "desde", "202301")]
    assert "rasa" not in M._avisos_familia(pares, None, None)
    assert "rasa" not in M._avisos_familia(pares, None, {"desde": None})


def test_carga_que_alcanca_todos_nao_avisa():
    pares = [_par("A", "desde", "202401"), _par("B", "desde", "202501")]
    assert "rasa" not in M._avisos_familia(pares, None, {"desde": "202301"})


def test_rasa_ignora_consumidor_morto():
    """Quem está fora do recorte vivo não puxa carga e não gera aviso."""
    pares = [_par("morto", "desde", "201712"), _par("vivo", "desde", "202501")]
    av = M._avisos_familia(pares, {"vivo"}, {"desde": "202401"})
    assert "rasa" not in av


def test_consumidor_que_precisa_de_TODAS_torna_qualquer_carga_rasa():
    pares = [_par("A", "todas")]
    av = M._avisos_familia(pares, None, {"desde": "200001"})
    assert av["rasa"]["precisa"] == "todas as safras"


# ---------------------------------------------------------------- dispersão e esparsidade

def test_dispersao_traz_a_faixa_pedida():
    pares = [_par("A", "rolling", "3"), _par("B", "rolling", "36")]
    d = M._avisos_familia(pares, None, None)["dispersao"]
    assert (d["min_meses"], d["max_meses"]) == (3, 36)
    assert d["n_consumidores"] == 2 and d["mais_fundo"] == "B"


def test_dispersao_conta_de_hoje_para_o_desde():
    pares = [_par("A", "desde", M._ym_para_texto(M._ym_hoje()))]
    d = M._avisos_familia(pares, None, None)["dispersao"]
    assert d["min_meses"] == 1        # a safra deste mês = 1 mês de passado


def test_esparsos_listados():
    pares = [_par("A", "desde", "202401", esparso=True),
             _par("B", "desde", "202401"),
             _par("C", "desde", "202401", esparso=True)]
    assert M._avisos_familia(pares, None, None)["esparsos"] == ["A", "C"]


def test_avisos_funcionam_sem_o_campo_interno_piso():
    """Regressão: o detalhe limpava `piso` antes de calcular os avisos e o endpoint
    quebrava com KeyError (pego rodando contra o dev, não pelos unitários)."""
    pares = [{"projeto": "A", "tipo": "desde", "valor": "202301"},
             {"projeto": "B", "tipo": "desde", "valor": "202506", "esparso": True}]
    av = M._avisos_familia(pares, None, {"desde": "202404"})
    assert av["rasa"]["mais_fundo"] == "A" and av["rasa"]["n"] == 1
    assert av["dispersao"]["max_meses"] > av["dispersao"]["min_meses"]
    assert av["esparsos"] == ["B"]


def test_avisos_de_familia_sem_par_sao_vazios():
    av = M._avisos_familia([], None, {"desde": "202401"})
    assert av == {"esparsos": []}


# ---------------------------------------------------------------- PATCH da ingerida

def _cli(atual=None):
    ps = [patch.object(M, "_ensure_ingestao_tables", lambda: True),
          patch.object(M, "run_sql", lambda *a, **k: []),
          patch.object(M, "_ingestao_map",
                       lambda: ({("tabela", "LIB.X"): atual} if atual else {})),
          patch.object(M, "_bump_gen", lambda: None)]
    for p in ps:
        p.start()
    return TestClient(M.app), ps


def _stop(ps):
    for p in ps:
        p.stop()


def test_registro_nao_exige_gestao():
    """É FATO consumado, não pedido: travar atrás da gestão só garantiria que ninguém
    registrasse (a necessária, que é pedido, essa sim é restrita)."""
    cli, ps = _cli()
    try:
        with patch.object(M, "_is_gestao", lambda: False):
            r = cli.patch("/api/familia-ingestao",
                          json={"categoria": "tabela", "familia": "LIB.X", "desde": "202401"})
        assert r.status_code == 200, r.text
        assert r.json()["desde"] == "202401"
    finally:
        _stop(ps)


@pytest.mark.parametrize("body,trecho", [
    ({"desde": "2024"}, "AAAAMM"),
    ({"desde": "202413"}, "AAAAMM"),
    ({"desde": "abcdef"}, "AAAAMM"),
    ({"desde": "202401", "ingerida_em": "01/2024"}, "AAAA-MM-DD"),
    ({"desde": "202401", "ingerida_em": "2024-13-01"}, "AAAA-MM-DD"),
])
def test_validacao(body, trecho):
    cli, ps = _cli()
    try:
        r = cli.patch("/api/familia-ingestao",
                      json={"categoria": "tabela", "familia": "LIB.X", **body})
        assert r.status_code == 400 and trecho in r.text
    finally:
        _stop(ps)


def test_apagar_e_idempotente():
    cli, ps = _cli()
    try:
        r = cli.patch("/api/familia-ingestao",
                      json={"categoria": "tabela", "familia": "LIB.X", "desde": ""})
        assert r.status_code == 200 and r.json()["desde"] is None
    finally:
        _stop(ps)


def _cli_captura(atual=None):
    """Como `_cli`, mas guarda os statements emitidos (para checar a forma da escrita)."""
    reg = []
    ps = [patch.object(M, "_ensure_ingestao_tables", lambda: True),
          patch.object(M, "run_sql", lambda s, *a, **k: (reg.append(s), [])[1]),
          patch.object(M, "_ingestao_map",
                       lambda: ({("tabela", "LIB.X"): atual} if atual else {})),
          patch.object(M, "_bump_gen", lambda: None)]
    for p in ps:
        p.start()
    return TestClient(M.app), reg, ps


def test_gravar_usa_merge_e_nunca_apaga_antes():
    """Regressão: era DELETE+INSERT. Entre os dois a linha não existia, e um timeout do
    warehouse ali (run_sql espera até 50s) apagava a profundidade declarada — o PATCH só
    carrega o valor NOVO, então nada no request dizia o que tinha sido perdido."""
    cli, reg, ps = _cli_captura(atual={"desde": "202401"})
    try:
        r = cli.patch("/api/familia-ingestao",
                      json={"categoria": "tabela", "familia": "LIB.X", "desde": "202403"})
    finally:
        _stop(ps)
    assert r.status_code == 200, r.text
    escritas = [s for s in reg if "sas_familia_ingestao" in s.lower()
                or "MERGE INTO" in s or "DELETE FROM" in s]
    assert any(s.lstrip().startswith("MERGE INTO") for s in escritas), escritas
    assert not any("DELETE FROM" in s for s in escritas), \
        "gravar um valor não pode apagar a linha antes"


def test_apagar_continua_sendo_delete():
    """Apagar de fato é uma operação só — não vira MERGE."""
    cli, reg, ps = _cli_captura(atual={"desde": "202401"})
    try:
        r = cli.patch("/api/familia-ingestao",
                      json={"categoria": "tabela", "familia": "LIB.X", "desde": ""})
    finally:
        _stop(ps)
    assert r.status_code == 200, r.text
    assert any("DELETE FROM" in s for s in reg)
    assert not any(s.lstrip().startswith("MERGE INTO") for s in reg)


def test_mesmo_valor_da_400():
    cli, ps = _cli(atual={"desde": "202401"})
    try:
        r = cli.patch("/api/familia-ingestao",
                      json={"categoria": "tabela", "familia": "LIB.X", "desde": "202401"})
        assert r.status_code == 400 and "idêntico" in r.text
    finally:
        _stop(ps)

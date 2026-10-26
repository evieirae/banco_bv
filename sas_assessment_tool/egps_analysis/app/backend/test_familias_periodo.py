#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profundidade NECESSÁRIA por (EGP, família) — ticket 07.

Cobre o que é regra (piso comparável, máximo entre vivos, precedência declarado > derivado)
e a validação do PATCH. `run_sql` stubado — não depende de warehouse.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as M  # noqa: E402


# ---------------------------------------------------------------- piso comparável

def test_piso_todas_e_o_mais_fundo():
    assert M._periodo_piso("todas", None) == float("-inf")


def test_piso_desde_usa_a_safra():
    assert M._periodo_piso("desde", "202401") == 2024 * 12 + 0
    assert M._periodo_piso("desde", "202412") == 2024 * 12 + 11
    # mais antigo = mais fundo = piso MENOR
    assert M._periodo_piso("desde", "202301") < M._periodo_piso("desde", "202401")


def test_piso_rolling_resolve_contra_hoje():
    """`rolling` é a única forma relativa: precisa de âncora, e a âncora é a data corrente."""
    assert M._periodo_piso("rolling", "12") == M._ym_hoje() - 11
    assert M._periodo_piso("rolling", "3") > M._periodo_piso("rolling", "12")


def test_piso_de_tipo_desconhecido_nao_puxa_carga():
    assert M._periodo_piso("qualquer", None) == float("inf")


@pytest.mark.parametrize("tok,esperado", [
    ("202401", 2024 * 12 + 0),
    ("20240115", 2024 * 12 + 0),
    ("2024", 2024 * 12),          # ano solto -> janeiro (conservador: pode precisar do ano)
    ("xx", None), ("", None),
])
def test_ym_de_safra(tok, esperado):
    assert M._ym_de_safra(tok) == esperado


# ---------------------------------------------------------------- máximo entre vivos

def _par(pj, tipo, valor=None):
    return {"projeto": pj, "tipo": tipo, "valor": valor,
            "piso": M._periodo_piso(tipo, valor)}


def test_maximo_e_o_mais_fundo():
    pares = [_par("A", "desde", "202501"), _par("B", "desde", "202301"),
             _par("C", "desde", "202412")]
    alvo, pj = M._periodo_maximo(pares)
    assert pj == "B" and alvo["valor"] == "202301"


def test_maximo_ignora_quem_nao_esta_vivo():
    """Consumidor fora do recorte vivo aparece na lista, mas não puxa a carga."""
    pares = [_par("morto", "desde", "201712"), _par("vivo", "desde", "202401")]
    alvo, pj = M._periodo_maximo(pares, vivos={"vivo"})
    assert pj == "vivo" and alvo["valor"] == "202401"


def test_sem_consumidor_vivo_nao_ha_maximo():
    pares = [_par("morto", "desde", "201712")]
    alvo, pj = M._periodo_maximo(pares, vivos={"outro"})
    assert alvo is None and pj is None


def test_todas_vence_qualquer_desde():
    pares = [_par("A", "desde", "201001"), _par("B", "todas")]
    _alvo, pj = M._periodo_maximo(pares)
    assert pj == "B"


# ---------------------------------------------------------------- precedência

def test_declarado_vence_derivado_e_preserva_o_derivado_ao_lado():
    der = {("EGP", "tabela", "LIB.X"): {"tipo": "desde", "valor": "202501",
                                        "origem": "derivado", "n_safras_lidas": 3}}
    dec = {("EGP", "tabela", "LIB.X"): {"tipo": "rolling", "valor": "12",
                                        "origem": "declarado"}}
    with patch.object(M, "_periodo_derivado", lambda: der), \
         patch.object(M, "_periodo_declarado", lambda: dec):
        pares = M._periodo_pares("tabela", "LIB.X")
    assert len(pares) == 1
    p = pares[0]
    assert (p["tipo"], p["valor"], p["origem"]) == ("rolling", "12", "declarado")
    # o derivado continua visível: é ele que volta a valer se a declaração for apagada
    assert (p["derivado_tipo"], p["derivado_valor"]) == ("desde", "202501")
    assert p["n_safras_lidas"] == 3     # evidência do corpus não é perdida pela declaração


def test_par_sem_declaracao_fica_derivado():
    der = {("EGP", "tabela", "LIB.X"): {"tipo": "desde", "valor": "202501", "origem": "derivado"}}
    with patch.object(M, "_periodo_derivado", lambda: der), \
         patch.object(M, "_periodo_declarado", lambda: {}):
        p = M._periodo_pares("tabela", "LIB.X")[0]
    assert p["origem"] == "derivado" and p["valor"] == "202501"


def test_declaracao_para_par_que_o_corpus_nao_tem_mais_continua_visivel():
    """EGP deixou de ler a família (ou o vínculo foi quebrado): a declaração não desaparece
    em silêncio — sai da carga só quando a gestão apagar."""
    dec = {("EGP", "tabela", "LIB.X"): {"tipo": "desde", "valor": "202001", "origem": "declarado"}}
    with patch.object(M, "_periodo_derivado", lambda: {}), \
         patch.object(M, "_periodo_declarado", lambda: dec):
        pares = M._periodo_pares("tabela", "LIB.X")
    assert [p["projeto"] for p in pares] == ["EGP"]


# ---------------------------------------------------------------- PATCH

def _cli():
    ps = [patch.object(M, "_ensure_periodo_tables", lambda: True),
          patch.object(M, "run_sql", lambda *a, **k: []),
          patch.object(M, "_periodo_declarado", lambda: {}),
          patch.object(M, "_bump_gen", lambda: None),
          patch.object(M, "_is_gestao", lambda: True)]
    for p in ps:
        p.start()
    return TestClient(M.app), ps


def _stop(ps):
    for p in ps:
        p.stop()


def _body(**kw):
    b = {"projeto": "EGP", "categoria": "tabela", "familia": "LIB.X", "tipo": "desde",
         "valor": "202401"}
    b.update(kw)
    return b


def _cli_captura(declarado=None):
    """Como `_cli`, mas guarda os statements emitidos (para checar a forma da escrita)."""
    reg = []
    ps = [patch.object(M, "_ensure_periodo_tables", lambda: True),
          patch.object(M, "run_sql", lambda s, *a, **k: (reg.append(s), [])[1]),
          patch.object(M, "_periodo_declarado", lambda: declarado or {}),
          patch.object(M, "_bump_gen", lambda: None),
          patch.object(M, "_is_gestao", lambda: True)]
    for p in ps:
        p.start()
    return TestClient(M.app), reg, ps


def test_declarar_usa_merge_e_nunca_apaga_antes():
    """Regressão: era DELETE+INSERT. Um timeout entre os dois deixava o par (EGP, família)
    sem linha — e "sem linha" é indistinguível de "nunca declarado" (volta a
    origem:'derivado'), então a perda não aparecia em lugar nenhum."""
    declarado = {("EGP", "tabela", "LIB.X"): {"tipo": "rolling", "valor": "12"}}
    cli, reg, ps = _cli_captura(declarado)
    try:
        r = cli.patch("/api/familia-periodo", json=_body(tipo="desde", valor="202401"))
    finally:
        _stop(ps)
    assert r.status_code == 200, r.text
    assert any(s.lstrip().startswith("MERGE INTO") for s in reg), reg
    assert not any("DELETE FROM" in s for s in reg), \
        "declarar um período não pode apagar a linha antes"


def test_voltar_ao_derivado_continua_sendo_delete():
    """Limpar a declaração é uma operação só — segue DELETE."""
    declarado = {("EGP", "tabela", "LIB.X"): {"tipo": "desde", "valor": "202401"}}
    cli, reg, ps = _cli_captura(declarado)
    try:
        r = cli.patch("/api/familia-periodo", json=_body(tipo="", valor=None))
    finally:
        _stop(ps)
    assert r.status_code == 200, r.text
    assert any("DELETE FROM" in s for s in reg)
    assert not any(s.lstrip().startswith("MERGE INTO") for s in reg)


def test_patch_exige_gestao():
    cli, ps = _cli()
    try:
        with patch.object(M, "_is_gestao", lambda: False):
            r = cli.patch("/api/familia-periodo", json=_body())
        assert r.status_code == 403
    finally:
        _stop(ps)


@pytest.mark.parametrize("body,trecho", [
    (_body(tipo="qualquer"), "tipo inválido"),
    (_body(tipo="desde", valor="2024"), "AAAAMM"),
    (_body(tipo="desde", valor="202413"), "AAAAMM"),
    (_body(tipo="desde", valor=None), "AAAAMM"),
    (_body(tipo="rolling", valor="zero"), "número de meses"),
    (_body(tipo="rolling", valor="0"), "faixa"),
    (_body(tipo="rolling", valor="601"), "faixa"),
])
def test_patch_valida_a_entrada(body, trecho):
    cli, ps = _cli()
    try:
        r = cli.patch("/api/familia-periodo", json=body)
        assert r.status_code == 400
        assert trecho in r.text
    finally:
        _stop(ps)


@pytest.mark.parametrize("body,esperado", [
    (_body(tipo="desde", valor="202401"), ("desde", "202401")),
    (_body(tipo="rolling", valor="12"), ("rolling", "12")),
    (_body(tipo="todas", valor="ignorado"), ("todas", None)),
    (_body(tipo="", valor=None), (None, None)),          # volta ao derivado
])
def test_patch_aceita_as_formas_validas(body, esperado):
    cli, ps = _cli()
    try:
        r = cli.patch("/api/familia-periodo", json=body)
        assert r.status_code == 200, r.text
        j = r.json()
        assert (j["tipo"], j["valor"]) == esperado
        assert j["origem"] == ("declarado" if esperado[0] else "derivado")
    finally:
        _stop(ps)


def test_patch_sem_mudanca_real_da_400():
    cli, ps = _cli()
    try:
        with patch.object(M, "_periodo_declarado",
                          lambda: {("EGP", "tabela", "LIB.X"): {"tipo": "desde",
                                                                "valor": "202401"}}):
            r = cli.patch("/api/familia-periodo", json=_body(tipo="desde", valor="202401"))
        assert r.status_code == 400 and "idêntico" in r.text
    finally:
        _stop(ps)

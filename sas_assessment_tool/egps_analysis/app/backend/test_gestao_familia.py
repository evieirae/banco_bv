#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aba Gestão (entity="input") no grão FAMÍLIA.

A Gestão lia `sas_inputs_monitor` por conta própria e ficou no grão antigo: 1.608 cards
onde há 754 unidades (medido em prod, 18/09/2026). Agora passa pela mesma régua do resto
do app (`_agrega_familias`).

A parte delicada não é a lista, é a ANOTAÇÃO: 442 datas e 940 comentários já foram
escritos na chave da SAFRA, antes da família existir. A decisão (17/09) é não migrar
nada: a família herda o que está nas safras na LEITURA e passa a gravar na própria
chave. `_gestao_anota` é essa regra, e é o que estes testes pinam.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402

FAM_NOME = "CARNEIRO.BASE_3040"
FAM = f"familia::tabela::{FAM_NOME}"
S1, S2 = f"tabela::{FAM_NOME}_202501", f"tabela::{FAM_NOME}_202502"
SOLTO = "tabela::B_GERAL.DIAS_UTEIS"


# ---------------------------------------------------------------- anotação

def test_familia_herda_datas_da_safra_mais_recente():
    datas = {S1: {"inicio": "2026-08-01", "fim_conversao": None, "fim": None,
                  "updated_at": "2026-08-01 10:00"},
             S2: {"inicio": "2026-09-01", "fim_conversao": "2026-09-10", "fim": None,
                  "updated_at": "2026-09-02 10:00"}}
    d, _u, _ev = M._gestao_anota(FAM, [S1, S2], datas, {}, {})
    assert d["inicio"] == "2026-09-01", "vence a safra atualizada por último"
    assert d["fim_conversao"] == "2026-09-10"


def test_data_escrita_na_familia_manda():
    datas = {FAM: {"inicio": "2026-09-15", "fim_conversao": None, "fim": None,
                   "updated_at": "2026-09-15 09:00"},
             S1: {"inicio": "2026-08-01", "fim_conversao": "2026-08-20", "fim": None,
                  "updated_at": "2026-08-01 10:00"}}
    d, _u, _ev = M._gestao_anota(FAM, [S1], datas, {}, {})
    assert d["inicio"] == "2026-09-15"
    assert d["fim_conversao"] == "2026-08-20", "campo vazio na família ainda herda"


def test_ultimo_status_e_o_mais_recente_entre_familia_e_safras():
    ultimos = {FAM: {"texto": "na família", "data": "2026-09-05"},
               S1: {"texto": "na safra", "data": "2026-09-12"}}
    _d, u, _ev = M._gestao_anota(FAM, [S1], {}, ultimos, {})
    assert u["texto"] == "na safra"


def test_eventos_bv_sao_unidos_e_ordenados():
    bv = {FAM: [{"id": "a", "comBv": True, "data": "2026-09-10", "autor": None}],
          S1: [{"id": "b", "comBv": False, "data": "2026-09-01", "autor": None}]}
    _d, _u, ev = M._gestao_anota(FAM, [S1], {}, {}, bv)
    assert [e["id"] for e in ev] == ["b", "a"]


def test_linha_sem_familia_nao_muda():
    datas = {SOLTO: {"inicio": "2026-08-01", "fim_conversao": None, "fim": None,
                     "updated_at": "2026-08-01 10:00"}}
    d, u, ev = M._gestao_anota(SOLTO, [], datas, {}, {})
    assert d["inicio"] == "2026-08-01" and u == {} and ev == []


# ---------------------------------------------------------------- lista

@pytest.fixture
def gestao(monkeypatch):
    """Stub do que bate no banco; devolve o payload de /api/gestao/rows?entity=input."""
    def rodar(flag=True):
        membros = [f"{FAM_NOME}_202501", f"{FAM_NOME}_202502"]
        chave = {("tabela", a): FAM_NOME for a in membros}
        chave[("tabela", "B_GERAL.DIAS_UTEIS")] = "B_GERAL.DIAS_UTEIS"
        corpus = {"chave": chave,
                  "membros": {("tabela", FAM_NOME): membros,
                              ("tabela", "B_GERAL.DIAS_UTEIS"): ["B_GERAL.DIAS_UTEIS"]}}
        monkeypatch.setattr(M, "FAMILIAS_ON", flag)
        monkeypatch.setattr(M, "_familias_corpus", lambda: corpus)
        monkeypatch.setattr(M, "_familia_egp_counts", lambda: {})
        monkeypatch.setattr(M, "_frontier_egps", lambda *a, **k: ({"Cob__A", "Cob__B"}, {"Cob__A"}))
        monkeypatch.setattr(M, "_ex_deps_contab", lambda *a, **k: set())
        monkeypatch.setattr(M, "_ensure_input_pipeline_cols", lambda *a, **k: None)
        monkeypatch.setattr(M, "_gestao_extras", lambda e: ({}, {}, {}))

        def fake_run_sql(sql, want_rows=True, **kw):
            s = sql.lower()
            if "sas_egp_inputs" in s and "chave_canonica as ch" in s:
                return [{"ch": S1, "pj": "Cob__A"}, {"ch": S2, "pj": "Cob__B"},
                        {"ch": SOLTO, "pj": "Cob__A"}]
            if "sas_inputs_monitor" in s:
                base = {"categoria": "tabela", "areas": "Cobranças", "responsavel": None,
                        "etapa": None, "status": None, "modernizada_auto": "A ingerir"}
                return [dict(base, chave_canonica=S1, artifact=f"{FAM_NOME}_202501"),
                        dict(base, chave_canonica=S2, artifact=f"{FAM_NOME}_202502"),
                        dict(base, chave_canonica=SOLTO, artifact="B_GERAL.DIAS_UTEIS")]
            return []
        monkeypatch.setattr(M, "run_sql", fake_run_sql)
        return M._gestao_rows_uncached("input")["rows"]
    return rodar


def test_lista_colapsa_as_safras_num_card(gestao):
    rows = gestao(flag=True)
    ids = {r["id"] for r in rows}
    assert ids == {FAM, SOLTO}, "duas safras da mesma tabela viram um card"
    fam = next(r for r in rows if r["id"] == FAM)
    assert fam["nome"] == f"{FAM_NOME}_{{SAFRA}}"
    assert fam["egps"] == ["Cob__A", "Cob__B"], "consumidores são a união das safras"
    assert fam["etapa"] == "A Receber" and fam["status"] == "A Iniciar"


def test_flag_desligada_mantem_o_comportamento_antigo(gestao):
    rows = gestao(flag=False)
    assert {r["id"] for r in rows} == {S1, S2, SOLTO}

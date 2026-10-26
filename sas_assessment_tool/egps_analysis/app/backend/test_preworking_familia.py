#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checklist de pré-working na linha de FAMÍLIA (`_pwk_herdadas`).

O checklist é config de INGESTÃO — uma por família, não uma por carga (é o mesmo
arquivo, a mesma frequência, o mesmo horário). Com a aba Inputs no grão família, a
linha passou a procurar o checklist pela chave `familia::...` e os que já tinham sido
preenchidos numa safra (22 dos 75 em prod, medido em 18/09/2026) sumiam da tela, com
risco de alguém refazer o trabalho.

A herança é só de LEITURA: a gravação continua indo para a chave que o drawer manda
(a da família), e a partir daí a família tem linha própria e para de herdar.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402

FAM = "familia::tabela::GRIMALDI.CARGA_MASSIFICADOS"
S1, S2 = "tabela::GRIMALDI.CARGA_MASSIFICADOS_202501", "tabela::GRIMALDI.CARGA_MASSIFICADOS_202502"
SOLTO = "tabela::B_GERAL.DIAS_UTEIS"
DE = {S1: FAM, S2: FAM}


def _row(ch, updated_at, **kw):
    r = {"chave_canonica": ch, "origem_arquivo": "N:/base.csv", "frequencia": "Mensal",
         "horario": None, "tipo_carga": None, "pos_processamento": None,
         "dados_sensiveis": None, "recebido": None, "data_recebimento": None,
         "modernizado_bv": None, "data_modernizado_bv": None,
         "updated_by": "alguem@bv", "updated_at": updated_at,
         "iniciado_em": None, "concluido_em": None}
    r.update(kw)
    return r


def test_familia_herda_o_checklist_da_safra():
    novas = M._pwk_herdadas([_row(S1, "2026-09-01 10:00")], DE)
    assert [r["chave_canonica"] for r in novas] == [FAM]
    assert novas[0]["herdado_de"] == S1
    assert novas[0]["frequencia"] == "Mensal"


def test_entre_duas_safras_vence_a_mais_recente():
    rows = [_row(S1, "2026-09-01 10:00", frequencia="Mensal"),
            _row(S2, "2026-09-10 08:00", frequencia="Diária")]
    novas = M._pwk_herdadas(rows, DE)
    assert len(novas) == 1 and novas[0]["herdado_de"] == S2
    assert novas[0]["frequencia"] == "Diária"


def test_checklist_proprio_da_familia_manda():
    rows = [_row(FAM, "2026-09-01 10:00", frequencia="Semanal"),
            _row(S2, "2026-09-10 08:00", frequencia="Diária")]
    assert M._pwk_herdadas(rows, DE) == [], "a família já tem o seu; herdar sobrescreveria"


def test_input_sem_familia_nao_gera_linha():
    assert M._pwk_herdadas([_row(SOLTO, "2026-09-01 10:00")], {}) == []


def test_empate_de_data_e_deterministico():
    rows = [_row(S2, "2026-09-01 10:00"), _row(S1, "2026-09-01 10:00")]
    a = M._pwk_herdadas(rows, DE)
    b = M._pwk_herdadas(list(reversed(rows)), DE)
    assert a[0]["herdado_de"] == b[0]["herdado_de"]

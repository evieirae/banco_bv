#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Série semanal (/api/inputs-recebidos-serie) no grão FAMÍLIA.

O endpoint era inteiramente por safra: sanitizar uma família de 47 safras escrevia 47
linhas de auditoria no mesmo instante (fan-out do `_patch_familia`) e a barra subia 47
para uma decisão que toda outra superfície conta como 1 — e `universo_total` citava ~2,4k
ao lado de um Resumo dizendo ~1,4k. Havia ainda um segundo furo: o `LEFT JOIN` do
checklist é por chave de safra, então a linha gravada NA chave da família (onde
`preworking_patch` grava) era invisível e família nenhuma contava em `recebidos` /
`modernizados_bv`.

`_serie_unidades` é função pura — testada direto, sem warehouse.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402

FAM = "LIB.SAFRA"
ARTS = ["LIB.SAFRA_202501", "LIB.SAFRA_202502", "LIB.SAFRA_202503"]
CH = [f"tabela::{a}" for a in ARTS]
CH_FAM = "familia::tabela::LIB.SAFRA"


def _row(art, **kw):
    r = {"chave_canonica": f"tabela::{art}", "categoria": "tabela", "artifact": art,
         "eff_status": None, "modernizado_bv": None, "data_modernizado_bv": None,
         "recebido": None, "data_recebimento": None}
    r.update(kw)
    return r


@pytest.fixture
def corpus():
    """Instala um corpus onde ARTS é uma família e qualquer outro artefato é solto."""
    mapa = {("tabela", a): FAM for a in ARTS}
    with patch.object(M, "FAMILIAS_ON", True), \
         patch.object(M, "_familias_corpus", lambda: {"chave": mapa, "membros": {}}):
        yield


# ---------------------------------------------------------------- colapso e universo

def test_familia_sanitizada_conta_uma_vez_na_data_da_ultima(corpus):
    """3 safras sanitizadas em dias diferentes = 1 evento, na data da ÚLTIMA (é a safra
    menos avançada que segura a família)."""
    rows = [_row(a, eff_status="Sanitizado") for a in ARTS]
    san = {CH[0]: "2026-07-10", CH[1]: "2026-07-24", CH[2]: "2026-07-17"}
    un = M._serie_unidades(rows, san, {})
    assert len(un) == 1
    assert un[0]["chave_canonica"] == CH_FAM
    assert un[0]["eff_status"] == "Sanitizado"
    assert un[0]["_san"] == "2026-07-24"


def test_familia_com_safra_viva_nao_conta_como_sanitizada(corpus):
    rows = [_row(ARTS[0], eff_status="Sanitizado"),
            _row(ARTS[1], eff_status="Sanitizado"),
            _row(ARTS[2])]
    un = M._serie_unidades(rows, {CH[0]: "2026-07-10", CH[1]: "2026-07-17"}, {})
    assert len(un) == 1
    assert un[0]["eff_status"] is None, "família com safra viva entrou como sanitizada"


def test_sem_data_em_alguma_safra_cai_no_bucket_pre(corpus):
    """Data faltando em qualquer membro = não dá para datar a família (bucket `pre`)."""
    rows = [_row(a, eff_status="Sanitizado") for a in ARTS]
    un = M._serie_unidades(rows, {CH[0]: "2026-07-10", CH[1]: "2026-07-17"}, {})
    assert un[0]["_san"] is None


def test_input_solto_passa_reta(corpus):
    rows = [_row("OUTRA.TABELA", eff_status="Sanitizado")]
    un = M._serie_unidades(rows, {"tabela::OUTRA.TABELA": "2026-08-01"}, {})
    assert len(un) == 1
    assert un[0]["chave_canonica"] == "tabela::OUTRA.TABELA"
    assert un[0]["_san"] == "2026-08-01"


def test_flag_desligada_nao_colapsa_nada():
    rows = [_row(a) for a in ARTS]
    with patch.object(M, "FAMILIAS_ON", False):
        un = M._serie_unidades(rows, {}, {})
    assert len(un) == 3


# ---------------------------------------------------------------- checklist da família

def test_checklist_da_chave_de_familia_manda(corpus):
    """A linha gravada na chave da família não saía do JOIN (que é por safra): família
    nenhuma contava em `recebidos`. Agora ela manda, mesmo com as safras em branco."""
    rows = [_row(a) for a in ARTS]
    pwk_fam = {CH_FAM: {"chave_canonica": CH_FAM, "recebido": "true",
                        "data_recebimento": "2026-08-05", "modernizado_bv": None,
                        "data_modernizado_bv": None}}
    un = M._serie_unidades(rows, {}, pwk_fam)
    assert un[0]["recebido"] == "true"
    assert un[0]["data_recebimento"] == "2026-08-05"


def test_sem_linha_na_familia_herda_so_se_TODAS_as_safras_tem(corpus):
    rows = [_row(a, recebido="true", data_recebimento=d)
            for a, d in zip(ARTS, ["2026-08-01", "2026-08-12", "2026-08-07"])]
    un = M._serie_unidades(rows, {}, {})
    assert un[0]["recebido"] == "true"
    assert un[0]["data_recebimento"] == "2026-08-12", "data tem de ser a da última safra"


def test_safra_faltando_a_flag_segura_a_familia(corpus):
    rows = [_row(ARTS[0], recebido="true", data_recebimento="2026-08-01"),
            _row(ARTS[1], recebido="true", data_recebimento="2026-08-02"),
            _row(ARTS[2])]
    un = M._serie_unidades(rows, {}, {})
    assert un[0]["recebido"] is None


def test_modernizado_bv_segue_a_mesma_regra(corpus):
    rows = [_row(a, modernizado_bv="true", data_modernizado_bv=d)
            for a, d in zip(ARTS, ["2026-09-01", "2026-09-03", "2026-09-02"])]
    un = M._serie_unidades(rows, {}, {})
    assert un[0]["modernizado_bv"] == "true"
    assert un[0]["data_modernizado_bv"] == "2026-09-03"


# ---------------------------------------------------------------- prioridade das 3 séries

def test_prioridade_continua_mutuamente_exclusiva(corpus):
    """Família sanitizada E com recebido marcado conta SÓ em sanitizados (a prioridade
    é aplicada no laço do endpoint sobre a unidade já colapsada)."""
    rows = [_row(a, eff_status="Sanitizado", recebido="true",
                 data_recebimento="2026-08-01") for a in ARTS]
    san = {c: "2026-07-20" for c in CH}
    un = M._serie_unidades(rows, san, {})
    assert un[0]["eff_status"] == "Sanitizado" and un[0]["recebido"] == "true"
    # o laço decide por prioridade: eff_status vence
    assert [u for u in un if u["eff_status"] == "Sanitizado"] == un

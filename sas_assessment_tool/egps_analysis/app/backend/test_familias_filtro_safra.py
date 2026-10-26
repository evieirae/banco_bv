#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Marcador `de_safra` (filtro "só safras" da aba Inputs): `_marca_safra` do main.py.

Marcador INFORMATIVO, não unidade de contagem: roda nos dois estados da flag e não muda
nenhum total. Com FAMILIAS_SAFRA=1 a linha já é a família; desligada, cada safra datada
vem marcada — é isso que permite o filtro sem reimplementar o regex de data no frontend
(a regra de nome vive só em familias.py).

Não bate no warehouse: `_familias_corpus` é substituído por um mapa sintético.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402


def _row(art, cat="tabela"):
    return {"chave_canonica": f"{cat}::{art}", "artifact": art, "categoria": cat}


@pytest.fixture
def corpus(monkeypatch):
    def instalar(familias_map):
        chave, membros = {}, {}
        for fam, arts in familias_map.items():
            for a in arts:
                eff = fam if len(arts) > 1 else a
                chave[("tabela", a)] = eff
                membros.setdefault(("tabela", eff), []).append(a)
        monkeypatch.setattr(M, "_familias_corpus",
                            lambda: {"chave": chave, "membros": membros})
    return instalar


def test_safra_datada_e_marcada(corpus):
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    rows = M._marca_safra([_row("GRIM.CARGA_202505"), _row("GRIM.CARGA_202506")])
    assert [r["de_safra"] for r in rows] == [True, True]


def test_input_solto_nao_e_marcado(corpus):
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"],
            "OUTRA.TABELA": ["OUTRA.TABELA"]})
    rows = M._marca_safra([_row("OUTRA.TABELA")])
    assert rows[0]["de_safra"] is False


def test_identidade_vem_do_corpus_nao_do_recorte(corpus):
    """Uma única safra da família no recorte continua sendo safra (invariante 3)."""
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506", "GRIM.CARGA_202507"]})
    rows = M._marca_safra([_row("GRIM.CARGA_202506")])
    assert rows[0]["de_safra"] is True


def test_linha_de_familia_agregada_e_marcada(corpus):
    """Com a flag ligada, a linha agregada (artifact = chave da família) também marca."""
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    fam = {"chave_canonica": "familia::tabela::GRIM.CARGA", "artifact": "GRIM.CARGA",
           "categoria": "tabela", "is_familia": True, "n_safras": 2}
    rows = M._marca_safra([fam])
    assert rows[0]["de_safra"] is True


def test_arquivo_nunca_marca(corpus):
    """Fase 1 só colapsa `tabela`; arquivo datado não é família (paths_fisicos vazio)."""
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    rows = M._marca_safra([_row("BASE_202505.CSV", cat="arquivo")])
    assert rows[0]["de_safra"] is False


def test_case_do_artifact_nao_importa(corpus):
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    rows = M._marca_safra([_row("grim.carga_202505")])
    assert rows[0]["de_safra"] is True


def test_nao_mexe_nos_outros_campos(corpus):
    corpus({"GRIM.CARGA": ["GRIM.CARGA_202505", "GRIM.CARGA_202506"]})
    r = _row("GRIM.CARGA_202505")
    r["qtd_projetos"] = 7
    out = M._marca_safra([r])
    assert out[0]["qtd_projetos"] == 7 and out[0]["chave_canonica"] == "tabela::GRIM.CARGA_202505"


def test_lista_vazia_nao_consulta_corpus(monkeypatch):
    def _boom():
        raise AssertionError("não deveria consultar o corpus para lista vazia")
    monkeypatch.setattr(M, "_familias_corpus", _boom)
    assert M._marca_safra([]) == []

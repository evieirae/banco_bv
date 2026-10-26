#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drawer do EGP (/api/egp) no grão FAMÍLIA — roll-up do vínculo quebrado.

O painel do EGP já contava por família no cabeçalho (n_faltam vem de /api/egp-readiness)
e listava as safras uma a uma embaixo: a mesma tela dizia "45 de 69" e mostrava 87
linhas. A lista passou a usar `_agrega_familias` (a régua do CORPUS, igual à aba Inputs).

O que este teste pina é o campo que só existe nesta superfície: `link_broken` é por
(EGP, safra) e só pode subir para a família quando TODAS as safras estão quebradas —
com `any`, uma safra desvinculada apagaria da tela o trabalho vivo das outras.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402

FAM = "GRIMALDI.CARGA_MASSIFICADOS"
SAFRAS = [f"{FAM}_202501", f"{FAM}_202502", f"{FAM}_202503"]


def _linha_drawer(art, **kw):
    """Linha como o SELECT do drawer devolve (grão safra)."""
    r = {"chave_canonica": f"tabela::{art}", "artifact": art, "categoria": "tabela",
         "source_types": "table_in", "modernizada_auto": "A ingerir",
         "origem": "SAS/Local (externo)", "etapa": None, "status": None,
         "responsavel": None, "observacao": None, "paths_fisicos": "",
         "n_paths_fisicos": 0, "link_broken": False}
    r.update(kw)
    return r


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
        monkeypatch.setattr(M, "_familia_egp_counts", lambda: {})
    return instalar


def _agrega(linhas):
    return {r["artifact"]: r for r in M._agrega_familias(linhas)}


def test_uma_safra_quebrada_nao_quebra_a_familia(corpus):
    corpus({FAM: SAFRAS})
    linhas = [_linha_drawer(SAFRAS[0], link_broken=True),
              _linha_drawer(SAFRAS[1]), _linha_drawer(SAFRAS[2])]
    fam = _agrega(linhas)[FAM]
    assert fam["is_familia"] is True
    assert fam["link_broken"] is False, "any() esconderia as 2 safras ainda vivas"
    assert fam["n_safras_no_recorte"] == 3


def test_todas_quebradas_quebram_a_familia(corpus):
    corpus({FAM: SAFRAS})
    linhas = [_linha_drawer(a, link_broken=True) for a in SAFRAS]
    assert _agrega(linhas)[FAM]["link_broken"] is True


def test_nenhuma_quebrada(corpus):
    corpus({FAM: SAFRAS})
    assert _agrega([_linha_drawer(a) for a in SAFRAS])[FAM]["link_broken"] is False


def test_input_solto_preserva_o_proprio_vinculo(corpus):
    corpus({FAM: SAFRAS, "B_GERAL.DIAS_UTEIS": ["B_GERAL.DIAS_UTEIS"]})
    linhas = [_linha_drawer(a) for a in SAFRAS] + [
        _linha_drawer("B_GERAL.DIAS_UTEIS", link_broken=True)]
    out = _agrega(linhas)
    assert out["B_GERAL.DIAS_UTEIS"]["link_broken"] is True
    assert out["B_GERAL.DIAS_UTEIS"].get("is_familia") is not True


def test_nome_de_exibicao_marca_a_safra(corpus):
    corpus({FAM: SAFRAS})
    fam = _agrega([_linha_drawer(a) for a in SAFRAS])[FAM]
    assert fam["nome_exibicao"] == f"{FAM}_{{SAFRA}}"

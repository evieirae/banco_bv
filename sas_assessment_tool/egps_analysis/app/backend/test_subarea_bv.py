# -*- coding: utf-8 -*-
"""Testes da chave canônica do Responsável BV. Não bate no warehouse."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.main import _norm_nome_bv  # noqa: E402


def test_caixa_e_espacos_nao_separam_a_pessoa():
    assert _norm_nome_bv("  Joao  Carneiro ") == _norm_nome_bv("joao carneiro")


def test_acento_nao_separa_a_pessoa():
    # o BV digita ora com ora sem acento; é a mesma pessoa
    assert _norm_nome_bv("Letícia Domingos Duarte") == _norm_nome_bv("Leticia Domingos Duarte")


def test_nomes_diferentes_nao_colidem():
    assert _norm_nome_bv("Cristiano") != _norm_nome_bv("Cristiane")


def test_vazio_e_none_viram_string_vazia():
    assert _norm_nome_bv(None) == ""
    assert _norm_nome_bv("   ") == ""


def test_invisiveis_nas_pontas_nao_criam_pessoa_nova():
    """BOM (CSV do Excel), NEL e separadores de registro (export de mainframe) chegam
    colados no nome ao copiar/colar. O JS os come no trim(); se o Python não comesse, a
    mesma pessoa viraria duas linhas no cadastro (nome_key é a chave do MERGE)."""
    esperado = _norm_nome_bv("Joao Carneiro")
    for invisivel in ("\ufeff", "\u0085", "\u001c", "\u001f", "\u200b", "\u00a0"):
        assert _norm_nome_bv(invisivel + "Joao Carneiro") == esperado, repr(invisivel)
        assert _norm_nome_bv("Joao Carneiro" + invisivel) == esperado, repr(invisivel)


def test_invisiveis_no_meio_viram_um_espaco():
    assert _norm_nome_bv("Joao\u0085Carneiro") == "joao carneiro"
    assert _norm_nome_bv("Joao\u001cCarneiro") == "joao carneiro"


def test_marca_de_classe_zero_e_removida_como_no_js():
    """Filtro por categoria (\\p{M}), não por combining()!=0: U+0E31 é marca mas tem
    combining 0, e o JS (\\p{M}) a removeria — as duas implementações discordariam."""
    assert _norm_nome_bv("a\u0e31b") == "ab"

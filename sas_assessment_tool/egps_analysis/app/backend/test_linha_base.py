# -*- coding: utf-8 -*-
"""A LINHA DE BASE CONGELADA (decisão da gestão, 29/09/2026).

O total de EGPs deixou de ser calculado: é uma LISTA de 193 projetos, versionada em
`egps_analysis/src/linha_base_congelada_2026-09-29.csv`. Este arquivo trava as duas
propriedades que fazem a régua valer a pena:

1. a lista é **dado**, lida do CSV — e **arquivo ausente explode**, não vira lista vazia.
   Sem a linha de base o total é um número inventado, e um zero silencioso seria pior do
   que um 500;
2. a decomposição exibida (base / dependência / ex-dependência) sai da **classe gravada**,
   nunca de um cálculo vivo sobre o grafo.

A data está no NOME do arquivo de propósito: trocar a linha de base tem de ser um ato
deliberado (novo arquivo, nova constante), não efeito colateral de um republish.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linha_base as lb


CSV_OK = "projeto,classe\nCobranças__A,base\nCobranças__B,dependencia\nRiscos__C,ex_dependencia\n"


def test_parse_devolve_projeto_para_classe_com_acento_intacto():
    mapa = lb.parse(CSV_OK)
    assert mapa == {"Cobranças__A": "base", "Cobranças__B": "dependencia",
                    "Riscos__C": "ex_dependencia"}


def test_parse_recusa_classe_desconhecida():
    with pytest.raises(lb.LinhaBaseInvalida):
        lb.parse("projeto,classe\nCobranças__A,extra\n")


def test_parse_recusa_projeto_duplicado():
    with pytest.raises(lb.LinhaBaseInvalida):
        lb.parse("projeto,classe\nCobranças__A,base\nCobranças__A,dependencia\n")


def test_parse_recusa_lista_vazia():
    """Linha de base vazia = total zero. É exatamente a falha silenciosa a evitar."""
    with pytest.raises(lb.LinhaBaseInvalida):
        lb.parse("projeto,classe\n")


def test_carrega_arquivo_ausente_falha_barulhento():
    with pytest.raises(lb.LinhaBaseAusente):
        lb.carrega("/nao/existe/linha_base.csv")


def test_decomposicao_vem_da_classe_gravada():
    mapa = lb.parse(CSV_OK)
    assert lb.decomposicao(mapa) == {"base": 1, "dependencia": 1, "ex_dependencia": 1}
    assert lb.total(mapa) == 3
    assert lb.projetos(mapa) == {"Cobranças__A", "Cobranças__B", "Riscos__C"}
    assert lb.por_classe(mapa)["base"] == {"Cobranças__A"}


def test_o_arquivo_versionado_e_a_foto_de_29_09_2026():
    """193 = 168 base + 11 dependências + 14 ex-dependências. Se este teste cair, ou o
    arquivo foi editado à mão ou a linha de base foi trocada — e trocar é decisão de
    gestão, com arquivo novo e data nova no nome."""
    mapa = lb.carrega()
    assert lb.total(mapa) == 193
    assert lb.decomposicao(mapa) == {"base": 168, "dependencia": 11, "ex_dependencia": 14}
    assert lb.ARQUIVO == "linha_base_congelada_2026-09-29.csv"


def test_carrega_e_cacheado_mas_limpavel():
    a = lb.carrega()
    assert lb.carrega() is a
    lb.limpa_cache()
    assert lb.carrega() == a


def test_arquivo_vive_dentro_do_deploy():
    """A linha de base tem de viajar com o app.

    O deploy sincroniza SÓ `egps_analysis/app/`. Em 29/09 o arquivo morava em
    `egps_analysis/src/` e o app publicado deu 500 na aba EGPs — o guard de falha
    barulhenta fez o certo, mas o dado não estava lá. Este teste impede o retorno."""
    raiz_deploy = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    assert os.path.exists(lb.CAMINHO), f"arquivo ausente: {lb.CAMINHO}"
    dentro = os.path.normpath(lb.CAMINHO).startswith(raiz_deploy + os.sep)
    assert dentro, (
        f"a linha de base está FORA da raiz do deploy ({raiz_deploy}): "
        f"{lb.CAMINHO}. O app publicado não a enxergaria.")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Path físico de input `arquivo`/`script` no publish (`path_de_arquivo`).

Para essas categorias o caminho vem pronto na coluna `path` do relatório 06 — o artifact é
o basename dele. Tabela NÃO passa por aqui: continua resolvendo libref->diretório pelo
libmap, porque para table_in a coluna `path` é o diretório do libname e tem outra semântica.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_to_databricks as pub  # noqa: E402


def test_path_de_rede_passa_inteiro():
    p = r"\\bvnet\global\DCCR\Planejamento\base.csv"
    assert pub.path_de_arquivo(p) == p


def test_desescapa_entidade_html():
    """O extrator escreve `&amp;` no relatório; publicar isso mostraria um caminho falso."""
    assert pub.path_de_arquivo("/&amp;Modo_Exec./riscosmercado/job.sas") \
        == "/&Modo_Exec./riscosmercado/job.sas"


def test_macro_nao_resolvida_e_publicada():
    """Caminho que depende de macro é informação de ingestão, não erro — não descartar."""
    assert pub.path_de_arquivo("/&Modo_Exec./bin/sas/00-Include.sas").startswith("/&Modo_Exec.")


def test_vazio_vira_none():
    for v in ("", "   ", None):
        assert pub.path_de_arquivo(v) is None


def test_espacos_nas_pontas_saem():
    assert pub.path_de_arquivo("  N:/DVMD/base.csv  ") == "N:/DVMD/base.csv"


def test_sufixo_de_planilha_preservado():
    """`[SHEET=...]` faz parte da chave do input (o extrator separa por aba) — o path acompanha."""
    p = r"\\bvnet\global\Pauta.xlsx[SHEET='IV_CA']"
    assert pub.path_de_arquivo(p) == p

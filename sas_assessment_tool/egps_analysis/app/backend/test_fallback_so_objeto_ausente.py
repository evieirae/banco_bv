# -*- coding: utf-8 -*-
"""Leitura que falha não vira conjunto vazio cacheado.

Os helpers do recorte (fora do backlog, vínculos, cascas, escolhas de produtor...) e as
leituras internas da aba EGPs engoliam QUALQUER HTTPException e devolviam vazio — e o
vazio ia para o cache por 5 min. Um timeout em `_egps_fora_backlog` fazia os
despriorizados voltarem a puxar dependências e o frontier inchar sem erro nenhum; um
timeout no funil deixava a aba EGPs inteira sem etapa/status. O fallback existe para
"tabela/coluna ainda não publicada" (app rodando antes do 1º publish) — só isso vira
vazio; o resto sobe. run_sql stubado, sem rede."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import HTTPException
from backend import main as m


def _falha(detail):
    def fake(stmt, want_rows=True):
        raise HTTPException(502, detail)
    return fake


@pytest.fixture(autouse=True)
def _cache_limpo():
    m._lineage_cache.clear()
    m._endpoint_cache.clear()
    yield
    m._lineage_cache.clear()
    m._endpoint_cache.clear()


def test_objeto_ausente_reconhece_so_tabela_e_coluna():
    assert m._objeto_ausente(HTTPException(502, "Falha SQL: [TABLE_OR_VIEW_NOT_FOUND] x"))
    assert m._objeto_ausente(HTTPException(502, "Falha SQL: [UNRESOLVED_COLUMN.WITH_SUGGESTION] y"))
    assert not m._objeto_ausente(HTTPException(502, "Falha SQL: TimeoutError: read timed out"))
    assert not m._objeto_ausente(HTTPException(403, "Sem permissão para este recurso"))


@pytest.mark.parametrize("fn", ["_egps_fora_backlog", "_vinculos_por_antecessor", "_cascas",
                                "_producer_choices", "_vias_resolvidas", "_egps_novos"])
def test_timeout_sobe_e_nao_fica_no_cache(fn):
    with patch.object(m, "run_sql", side_effect=_falha("Falha SQL: TimeoutError")):
        with pytest.raises(HTTPException):
            getattr(m, fn)()
    # nada de "vazio" cacheado: a próxima leitura tenta de novo
    assert not m._lineage_cache


@pytest.mark.parametrize("fn", ["_egps_fora_backlog", "_vinculos_por_antecessor", "_cascas"])
def test_tabela_ausente_continua_vazio(fn):
    with patch.object(m, "run_sql",
                      side_effect=_falha("Falha SQL: [TABLE_OR_VIEW_NOT_FOUND] t")):
        assert not getattr(m, fn)()

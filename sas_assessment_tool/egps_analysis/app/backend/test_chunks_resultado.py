#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materialização do resultado: seguir `next_chunk_index` até o fim.

Com `disposition=INLINE` o PRIMEIRO chunk vem na resposta do statement e o resto só sai
pelo endpoint de chunk. `run_sql`/`_run_sp` liam só `r.result.data_array`, então todo
resultado que não coubesse num chunk era truncado EM SILÊNCIO — sem erro, sem aviso, e o
app exibia um recorte achando que era o todo. Morde exatamente nas superfícies que
carregam o dataset inteiro do escopo (~11k linhas).

Sem warehouse: um cliente falso devolve chunks encadeados.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402


def _manifest(*nomes):
    return SimpleNamespace(schema=SimpleNamespace(
        columns=[SimpleNamespace(name=n) for n in nomes]))


def _chunk(linhas, prox=None):
    return SimpleNamespace(data_array=linhas, next_chunk_index=prox)


class _ClienteFalso:
    """Devolve os chunks 1..N; registra quais foram pedidos."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.pedidos = []
        self.statement_execution = self

    def get_statement_result_chunk_n(self, sid, n):
        self.pedidos.append((sid, n))
        return self._chunks[n]


def test_um_chunk_so_nao_pede_nada_a_mais():
    w = _ClienteFalso({})
    r = SimpleNamespace(manifest=_manifest("a", "b"),
                        result=_chunk([["1", "x"], ["2", "y"]]))
    assert M._materializa_linhas(w, "sid", r) == [{"a": "1", "b": "x"},
                                                  {"a": "2", "b": "y"}]
    assert w.pedidos == []


def test_segue_a_cadeia_ate_o_fim():
    """3 chunks: o comportamento antigo devolvia 1 linha e perdia 4 sem dizer nada."""
    w = _ClienteFalso({1: _chunk([["2"], ["3"]], prox=2),
                       2: _chunk([["4"], ["5"]], prox=None)})
    r = SimpleNamespace(manifest=_manifest("n"), result=_chunk([["1"]], prox=1))
    linhas = M._materializa_linhas(w, "sid", r)
    assert [x["n"] for x in linhas] == ["1", "2", "3", "4", "5"]
    assert w.pedidos == [("sid", 1), ("sid", 2)]


def test_chunk_vazio_no_meio_nao_interrompe():
    w = _ClienteFalso({1: _chunk([], prox=2),
                       2: _chunk([["3"]], prox=None)})
    r = SimpleNamespace(manifest=_manifest("n"), result=_chunk([["1"]], prox=1))
    assert [x["n"] for x in M._materializa_linhas(w, "sid", r)] == ["1", "3"]


def test_resultado_sem_linhas():
    w = _ClienteFalso({})
    r = SimpleNamespace(manifest=_manifest("n"), result=_chunk(None))
    assert M._materializa_linhas(w, "sid", r) == []


def test_sem_result_nem_manifest_nao_explode():
    """DDL e afins: `want_rows=False` nem chega aqui, mas o helper tem de aguentar."""
    w = _ClienteFalso({})
    r = SimpleNamespace(manifest=None, result=None)
    assert M._materializa_linhas(w, "sid", r) == []


def test_chunk_sem_o_atributo_next_para_a_leitura():
    """SDK antigo/objeto sem `next_chunk_index`: para no primeiro, sem AttributeError."""
    w = _ClienteFalso({})
    r = SimpleNamespace(manifest=_manifest("n"),
                        result=SimpleNamespace(data_array=[["1"]]))
    assert [x["n"] for x in M._materializa_linhas(w, "sid", r)] == ["1"]

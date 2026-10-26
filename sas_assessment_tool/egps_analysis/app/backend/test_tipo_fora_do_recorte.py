# -*- coding: utf-8 -*-
"""`tipo` é propriedade do EGP, não do recorte pedido.

O recorte `base` forçava `dep_nivel = 0` em toda linha, e o `tipo` saía `escopo` para o
corpus INTEIRO — 1.250 linhas em prod (07/10/2026), 1.007 delas fora do escopo Indicium. O
drawer do EGP (`EgpDetailPanel`) pede `base` fixo, então ele exibia o badge "escopo" para
qualquer EGP que você abrisse, e a coluna Tipo do recorte "escopo: todos" tinha um valor só.

4º valor: `fora_do_recorte` — está no corpus e fora de tudo. Chamá-lo de escopo era a
mentira; não ter rótulo nenhum seria a seguinte.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import HTTPException
from backend import main as m

# 4 EGPs, um de cada classe contra o recorte Indicium.
LINHAS = [
    {"projeto": "Cob__ESC", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cob__DEP", "area": "Cobrança", "escopo_indi": False},
    {"projeto": "Cob__EX", "area": "Cobrança", "escopo_indi": False},
    {"projeto": "Cob__FORA", "area": "Cobrança", "escopo_indi": False},
]
BASE_INDI = {"Cob__ESC"}
FRONTIER = {"Cob__ESC", "Cob__DEP"}
EX = {"Cob__EX"}


def _stub(r):
    """Uma linha de readiness com os campos que o restante da função toca."""
    return {**r, "onda": "", "ciclo_id": 0, "n_inputs": 0, "n_disp": 0, "n_faltam": 0,
            "n_links_broken": 0, "pct": 100, "n_deps": 0, "n_deps_indi": 0, "n_deps_ext": 0,
            "deps": [], "status": "", "etapa": "", "bloqueado_dep": False,
            "responsavel": None, "n_outputs": 0, "n_outputs_disp": 0, "preworking": False}


def _rows(scope, frontier_falha=None):
    def _frontier(*a, **k):
        if frontier_falha is not None:
            raise frontier_falha
        return set(FRONTIER), set(BASE_INDI)

    patches = [
        patch.object(m, "_egp_readiness_rows",
                     lambda sc: [_stub(r) for r in LINHAS
                                 if sc == "base" or r["escopo_indi"]]),
        patch.object(m, "_frontier_egps", _frontier),
        patch.object(m, "_ex_deps", lambda *a, **k: (set(EX), {"Cob__EX": "resolvida por ingestão"},
                                                     {"Cob__EX": 2})),
        patch.object(m, "_sem_fonte_by_proj", lambda *a, **k: {}),
        patch.object(m, "_readiness_inputs_header", lambda *a, **k: (0, 0, 0, 0)),
        patch.object(m, "_linha_base", lambda: {"Cob__ESC": "base", "Cob__DEP": "dependencia"}),
        patch.object(m, "_cascas", lambda: set()),
        patch.object(m, "_egps_novos", lambda: set()),
        patch.object(m, "_vinculos_por_antecessor", lambda: {}),
        patch.object(m, "_extras", lambda *a, **k: set()),
        patch.object(m, "run_sql", side_effect=lambda *a, **k: []),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
        patch.object(m, "_ensure_gestao_tables", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        return {r["projeto"]: r for r in m._egp_readiness_uncached(scope)["rows"]}
    finally:
        for p in patches:
            p.stop()


def test_base_classifica_as_quatro_classes():
    r = _rows("base")
    assert r["Cob__ESC"]["tipo"] == "escopo"
    assert r["Cob__DEP"]["tipo"] == "dependencia"
    assert r["Cob__EX"]["tipo"] == "ex_dependencia"
    assert r["Cob__FORA"]["tipo"] == "fora_do_recorte"


def test_base_nao_chama_mais_tudo_de_escopo():
    """A regressão exata: era `escopo` para o corpus inteiro."""
    r = _rows("base")
    assert [x["tipo"] for x in r.values()].count("escopo") == 1


def test_ex_dependencia_do_base_traz_motivo_e_nivel():
    """Mesma hidratação do indi_deps: sem o motivo, o badge não explica por que saiu."""
    r = _rows("base")["Cob__EX"]
    assert r["ex_dependencia"] is True
    assert r["ex_motivo"] == "resolvida por ingestão"
    assert r["dep_nivel"] == 2


def test_fora_do_recorte_nao_vira_ex_dependencia():
    """`fora` nunca esteve no recorte; ex-dependência esteve. Não são o mesmo estado."""
    r = _rows("base")["Cob__FORA"]
    assert r["tipo"] == "fora_do_recorte"
    assert not r.get("ex_dependencia")
    assert r.get("ex_motivo") is None


def test_indi_segue_so_escopo():
    """No recorte Indicium toda linha é escopo por construção — nada a reclassificar."""
    r = _rows("indi")
    assert set(r) == {"Cob__ESC"}
    assert r["Cob__ESC"]["tipo"] == "escopo"


def test_timeout_ao_classificar_o_base_sobe_em_vez_de_rotular_tudo_fora():
    """Falha do frontier no meio da classificação NÃO vira conjunto vazio: com tudo vazio,
    o corpus inteiro sairia `fora_do_recorte` — e esse payload vai para o cache
    compartilhado por 5 min. Só "grafo ainda não publicado" pode cair no fallback."""
    with pytest.raises(HTTPException) as e:
        _rows("base", frontier_falha=HTTPException(502, "Falha SQL: TimeoutError"))
    assert e.value.status_code == 502


def test_grafo_nao_publicado_continua_no_fallback():
    r = _rows("base", frontier_falha=HTTPException(
        502, "Falha SQL: [TABLE_OR_VIEW_NOT_FOUND] sas_lineage_nodes cannot be found"))
    assert set(r) == {x["projeto"] for x in LINHAS}

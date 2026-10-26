#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Métricas na unidade FAMÍLIA DE SAFRAS no publish (ticket 06).

O plano previa uma SEGUNDA cópia da regra aqui, com nota de sincronia. Não foi preciso: o
publish importa `app/backend/familias.py` (módulo puro, mesmo repo), então existe uma regra
num lugar só — e o primeiro teste abaixo trava isso, que é o que a nota de sincronia tentava
proteger. Roda como script:
    egps_analysis/venv/bin/python -m pytest egps_analysis/test_fam_metrics.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_to_databricks as pub  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "backend"))
import familias  # noqa: E402


def _in(art, cat="tabela", auto="A ingerir"):
    return {"artifact": art, "categoria": cat, "modernizada_auto": auto}


def test_publish_usa_a_MESMA_regra_do_app_nao_uma_copia():
    """Uma regra, um lugar: o módulo importado pelo publish é o mesmo arquivo do app."""
    assert pub.familias.__file__ == familias.__file__
    assert pub.familias.familia_candidata is familias.familia_candidata


def test_colapsa_safras_e_preserva_solitarios():
    m = pub._fam_metrics([
        _in("LIB.X_202501"), _in("LIB.X_202502"), _in("LIB.X_202503"),
        _in("LIB.SOZINHA"),
    ])
    assert m["inputs_familias"] == 2          # a família + a tabela sem safra
    assert m["inputs_pendentes_familia"] == 2


def test_familia_pendente_se_QUALQUER_safra_esta_a_ingerir():
    m = pub._fam_metrics([
        _in("LIB.X_202501", auto="Disponível"),
        _in("LIB.X_202502", auto="Disponível"),
        _in("LIB.X_202503", auto="A ingerir"),
    ])
    assert m["inputs_familias"] == 1
    assert m["inputs_pendentes_familia"] == 1   # 1 safra pendente segura a família


def test_familia_resolvida_so_quando_TODAS_as_safras_estao():
    m = pub._fam_metrics([_in("LIB.X_202501", auto="Disponível"),
                          _in("LIB.X_202502", auto="Disponível")])
    assert m["inputs_familias"] == 1
    assert m["inputs_pendentes_familia"] == 0


def test_arquivo_e_script_nao_colapsam_na_fase_1():
    rows = [_in("EXCECOES_20250902.CSV", cat="arquivo"),
            _in("EXCECOES_20251110.CSV", cat="arquivo"),
            _in("MACRO_202501.SAS", cat="script"),
            _in("MACRO_202502.SAS", cat="script")]
    m = pub._fam_metrics(rows)
    assert m["inputs_familias"] == 4           # nenhum colapso


def test_lista_vazia_nao_explode():
    assert pub._fam_metrics([]) == {"inputs_familias": 0, "inputs_pendentes_familia": 0}


def test_metricas_antigas_seguem_no_dicionario():
    """A métrica nova é PARALELA: as antigas continuam existindo com o mesmo nome."""
    src = pub._fam_metrics([_in("LIB.X_202501")])
    assert set(src) == {"inputs_familias", "inputs_pendentes_familia"}

# -*- coding: utf-8 -*-
"""Etapas renomeadas (24–25/08/2026) na trilha de auditoria da aba Tempo por Etapa.

A auditoria guarda os nomes antigos; _canon_etapa_rows os traduz e funde permanências
consecutivas. Lógica pura: sem DB, sem FastAPI.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main


def _r(p, et, ts):
    return {"projeto": p, "etapa": et, "ts": ts}


def test_nome_antigo_vira_o_atual():
    out = main._canon_etapa_rows([_r("A", "Pré-Working", "2026-07-01"),
                                  _r("A", "Aprv. PR", "2026-08-01"),
                                  _r("A", "Artefatos de GOV.", "2026-08-10")])
    assert [r["etapa"] for r in out] == ["Pré-Working + Outputs",
                                         "Aprv. PR + Validação Governança", "Aplicação de Grant"]


def test_permanencia_que_cruzou_o_rename_nao_vira_dois_intervalos():
    out = main._canon_etapa_rows([_r("A", "Pré-Working", "2026-07-01"),
                                  _r("A", "Pré-Working + Outputs", "2026-08-24"),
                                  _r("A", "Conversão do Código", "2026-09-01")])
    assert [(r["etapa"], r["ts"]) for r in out] == [("Pré-Working + Outputs", "2026-07-01"),
                                                    ("Conversão do Código", "2026-09-01")]


def test_fusao_nao_atravessa_projetos():
    out = main._canon_etapa_rows([_r("A", "Pré-Working", "2026-07-01"),
                                  _r("B", "Pré-Working + Outputs", "2026-07-02")])
    assert len(out) == 2


def test_etapa_fora_do_mapa_e_entrada_intacta():
    rows = [_r("A", "Conversão do Código", "2026-07-01")]
    assert main._canon_etapa_rows(rows) == rows


def test_funil_de_inputs_nao_e_tocado():
    assert "Pré-Working" in main.PIPELINE_INPUT
    assert not set(main.ETAPAS_RENOMEADAS_MIGRACAO) & set(main.PIPELINE_PROJETO["migracao"])

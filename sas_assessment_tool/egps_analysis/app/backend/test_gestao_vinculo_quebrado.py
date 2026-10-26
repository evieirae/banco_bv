#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gestão de inputs (/api/gestao/rows?entity=input) respeita o vínculo quebrado.

Todas as outras superfícies tiram o input cujos vínculos com o recorte estão TODOS
quebrados (`_ch_vinculo_ativo`, decisão de 30/07/2026); a Gestão — e o Kanban do
Acompanhamento, mesmo endpoint — lia `sas_egp_inputs` direto e seguia mostrando. Medido
em prod 08/10/2026: 62 cards (61 na coluna A Receber) que nenhum EGP do recorte usa mais,
e 53 cards listando EGP desvinculado (o que também mexe no filtro de Mês, herdado de
`egps`). Catálogo de divergências, item 12.

O stub aplica o filtro de vínculo só quando o SQL o pede — como o banco faria.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as M  # noqa: E402

QUEBRADO = "tabela::B.SO_VINCULO_QUEBRADO"   # único vínculo do recorte quebrado
PARCIAL = "tabela::B.UM_QUEBRADO_UM_ATIVO"   # quebrado com Cob__A, ativo com Cob__B
ATIVO = "tabela::B.VINCULO_ATIVO"
VINCULOS = [(QUEBRADO, "Cob__A", True), (PARCIAL, "Cob__A", True),
            (PARCIAL, "Cob__B", False), (ATIVO, "Cob__A", False)]
FILTRO_ATIVO = "not coalesce(l.link_broken, false)"


@pytest.fixture
def gestao(monkeypatch):
    monkeypatch.setattr(M, "FAMILIAS_ON", False)
    monkeypatch.setattr(M, "_frontier_egps", lambda *a, **k: ({"Cob__A", "Cob__B"}, {"Cob__A"}))
    monkeypatch.setattr(M, "_ex_deps_contab", lambda *a, **k: set())
    monkeypatch.setattr(M, "_ensure_input_pipeline_cols", lambda *a, **k: None)
    monkeypatch.setattr(M, "_gestao_extras", lambda e: ({}, {}, {}))

    def fake_run_sql(sql, want_rows=True, **kw):
        s = " ".join(sql.lower().split())
        filtra = "sas_egp_input_link" in s and FILTRO_ATIVO in s
        pares = [(ch, pj) for ch, pj, quebrado in VINCULOS if not (filtra and quebrado)]
        if "sas_egp_inputs" in s and "chave_canonica as ch" in s:
            return [{"ch": ch, "pj": pj} for ch, pj in pares]
        if "sas_inputs_monitor" in s:
            vivas = {ch for ch, _ in pares}
            base = {"categoria": "tabela", "areas": "Cobranças", "responsavel": None,
                    "etapa": None, "status": None, "modernizada_auto": "A ingerir"}
            return [dict(base, chave_canonica=ch, artifact=ch.split("::")[1])
                    for ch in (QUEBRADO, PARCIAL, ATIVO) if ch in vivas]
        return []
    monkeypatch.setattr(M, "run_sql", fake_run_sql)
    return {r["id"]: r for r in M._gestao_rows_uncached("input")["rows"]}


def test_input_com_todos_os_vinculos_quebrados_sai_da_gestao(gestao):
    assert QUEBRADO not in gestao
    assert set(gestao) == {PARCIAL, ATIVO}


def test_card_nao_lista_egp_desvinculado(gestao):
    assert gestao[PARCIAL]["egps"] == ["Cob__B"], "Cob__A quebrou o vínculo: não consome mais"
    assert gestao[ATIVO]["egps"] == ["Cob__A"]

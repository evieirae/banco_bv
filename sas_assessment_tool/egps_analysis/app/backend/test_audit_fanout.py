#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GET /api/audit colapsa o fan-out da família — uma edição, uma linha.

Editar etapa/status numa família grava uma linha de auditoria POR SAFRA, todas no mesmo
instante (`_patch_familia`). Sem colapsar, um clique da analista virava 20 linhas iguais
no histórico do input; pior, na aba Histórico essas 20 comiam o LIMIT e empurravam o
resto do dia para fora da tela — o histórico ficava ilegível justamente no dia em que
alguém trabalhou.

O colapso é de EXIBIÇÃO: as linhas continuam gravadas por safra (é onde o estado mora,
ADR 0002). A régua do agrupamento é a chave de família, não o instante sozinho: edição em
lote sobre tabelas DIFERENTES no mesmo segundo continua uma linha por tabela, que é o que
o auditor precisa ver.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402


def _client(rows):
    """TestClient com run_sql registrando o SQL e devolvendo `rows` para a auditoria."""
    reg = {"sql": []}

    def fake_run_sql(stmt, want_rows=True, **kw):
        reg["sql"].append(stmt)
        if "sas_inputs_audit" in stmt.lower():
            return list(rows)
        return []

    ps = [patch.object(m, "run_sql", side_effect=fake_run_sql),
          patch.object(m, "_chaves_para_leitura", lambda ch: [ch])]
    for p in ps:
        p.start()
    return TestClient(m.app), reg, ps


def _stop(ps):
    for p in ps:
        p.stop()


def _sql_do_monitor(reg):
    return [s for s in reg["sql"] if "sas_inputs_audit" in s.lower()][0]


def test_agrupa_por_familia_campo_valores_autor_e_instante():
    """O GROUP BY tem que conter os cinco eixos — tirar qualquer um funde ações distintas."""
    cli, reg, ps = _client([])
    try:
        cli.get("/api/audit")
    finally:
        _stop(ps)
    sql = _sql_do_monitor(reg).lower()
    assert "group by" in sql
    grupo = sql.split("group by", 1)[1]
    for eixo in ("campo", "valor_antigo", "valor_novo", "updated_by", "updated_at"):
        assert eixo in grupo, f"{eixo} fora do GROUP BY: ações distintas iriam colapsar"


def test_chave_de_familia_entra_no_agrupamento():
    """Sem a chave de família no GROUP BY, duas TABELAS distintas editadas no mesmo
    instante (edição em lote) virariam uma linha só e o histórico mentiria."""
    cli, reg, ps = _client([])
    try:
        cli.get("/api/audit")
    finally:
        _stop(ps)
    sql = _sql_do_monitor(reg)
    # a expressão da regra de família remove o token de data do nome do artefato
    assert "regexp_replace" in sql.lower()
    assert "chave_canonica" in sql


def test_devolve_n_safras_por_linha():
    """A contagem é o que substitui as N linhas: sem ela o colapso esconderia tamanho."""
    cli, reg, ps = _client([{
        "chave_canonica": "tabela::CARNEIRO.BASE_3040_202412", "campo": "etapa",
        "valor_antigo": "A Receber", "valor_novo": "Modernizado",
        "updated_by": "fulana@indicium.ai", "updated_at": "2026-09-21 19:41:39",
        "n_safras": 19}])
    try:
        r = cli.get("/api/audit")
    finally:
        _stop(ps)
    assert r.status_code == 200
    linha = r.json()["rows"][0]
    assert linha["n_safras"] == 19
    assert linha["fonte"] == "Monitoramento"


def test_limite_e_aplicado_depois_do_agrupamento():
    """O LIMIT tem que vir DEPOIS do GROUP BY: era esse o bug da aba Histórico — 20 linhas
    de uma edição consumiam o limite e escondiam o resto."""
    cli, reg, ps = _client([])
    try:
        cli.get("/api/audit?limit=50")
    finally:
        _stop(ps)
    sql = _sql_do_monitor(reg).lower()
    assert sql.index("group by") < sql.index("limit 50")


def test_historico_de_um_input_tambem_colapsa():
    """O drawer do input usa o mesmo caminho — é onde a analista viu o problema."""
    cli, reg, ps = _client([{
        "chave_canonica": "tabela::CARNEIRO.BASE_3040_202412", "campo": "status",
        "valor_antigo": "A Iniciar", "valor_novo": "Concluído",
        "updated_by": "fulana@indicium.ai", "updated_at": "2026-09-21 19:41:53",
        "n_safras": 19}])
    try:
        r = cli.get("/api/audit?chave=familia::tabela::CARNEIRO.BASE_3040")
    finally:
        _stop(ps)
    assert r.status_code == 200
    assert r.json()["rows"][0]["n_safras"] == 19
    assert "group by" in _sql_do_monitor(reg).lower()


def test_input_sem_familia_nao_ganha_contagem_enganosa():
    """Input solto: uma linha, n_safras = 1 — a UI não deve mostrar sufixo nenhum."""
    cli, reg, ps = _client([{
        "chave_canonica": "tabela::ACRIS.BASE_UNICA", "campo": "responsavel",
        "valor_antigo": "", "valor_novo": "fulana@indicium.ai",
        "updated_by": "fulana@indicium.ai", "updated_at": "2026-09-20 10:00:00",
        "n_safras": 1}])
    try:
        r = cli.get("/api/audit?chave=tabela::ACRIS.BASE_UNICA")
    finally:
        _stop(ps)
    assert r.json()["rows"][0]["n_safras"] == 1

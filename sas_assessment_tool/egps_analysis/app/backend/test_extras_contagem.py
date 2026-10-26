# -*- coding: utf-8 -*-
"""Prova, NO MESMO PROCESSO, que a categoria `extra` não mexe no total base.

Método (o mesmo que validou a régua anterior): injeta vínculos/cascas FALSOS na fonte
única (sas_egp_pipeline / sas_escopo), roda os mesmos endpoints antes e depois e compara
os contadores. Comparar contra snapshot gravado dá falso positivo (a prod deriva sozinha)
e falso negativo (sem vínculo em prod o conjunto é vazio e um ponto de contagem esquecido
passa batido).

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

# Corpus mínimo: 2 EGPs de escopo + 1 dependência transitiva (C produz para B).
NODES = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__B", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__C", "area": "Cobrança", "escopo_indi": False},
]
EDGES = [{"projeto_alvo": "Cobranças__B", "depende_do": "Cobranças__C", "via_tabelas": ""}]


def _fake_db(pipe_rows, escopo_rows, nodes=NODES):
    """run_sql de mentira: despacha pela tabela citada no statement."""
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if not want_rows:
            return []
        if "sas_lineage_edges" in s:
            return [dict(e) for e in EDGES]
        if "sas_lineage_nodes" in s:
            rows = [n for n in nodes if "escopo_indi = true" not in s or n["escopo_indi"]]
            if "count(*)" in s:
                return [{"n": len(rows)}]
            return [dict(r) for r in rows]
        if "sas_egp_pipeline" in s:
            return [dict(r) for r in pipe_rows]
        if "sas_escopo" in s:
            rows = escopo_rows
            if "origem = 'casca'" in s:
                rows = [r for r in rows if r.get("origem") == "casca"]
            if "count(*)" in s:
                return [{"n": len(rows)}]
            return [dict(r) for r in rows]
        return []
    return fake_run_sql


# Linha de base congelada DESTE corpus (régua de 29/09/2026): A, B e C contam; o que o
# teste injetar depois (sucessor, casca) é extra por não estar aqui. Sem injetar isto o CSV
# real (193 projetos de prod) entraria em cena e o corpus inteiro viraria `extra`.
LB = {"Cobranças__A": "base", "Cobranças__B": "base", "Cobranças__C": "dependencia"}


def _client(pipe_rows, escopo_rows, nodes=NODES):
    m._lineage_cache.clear()          # cache é por geração: limpar entre "antes" e "depois"
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(pipe_rows, escopo_rows, nodes)),
        patch.object(m, "_linha_base", lambda: dict(LB)),
        patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    return TestClient(m.app), patches


def _stop(patches):
    for p in patches:
        p.stop()


def _scope_egps(pipe_rows, escopo_rows, nodes=NODES):
    client, patches = _client(pipe_rows, escopo_rows, nodes)
    try:
        r = client.get("/api/scope-egps", params={"scope": "indi_deps"})
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        _stop(patches)


ESCOPO_BASE = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": "Cobranças__B", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
]
PIPE_BASE = [{"projeto": "Cobranças__A", "etapa_migracao": "Conversão do Código",
              "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""}]


def test_sucessor_de_substituido_nao_mexe_no_total_base():
    antes = _scope_egps(PIPE_BASE, ESCOPO_BASE)
    assert (antes["n_egps"], antes["n_base"], antes["n_extra"]) == (3, 2, 0)

    # injeção: o EGP novo entra no corpus e vira sucessor de um Substituído — o caso que
    # a régua anterior somava no denominador.
    nodes = NODES + [{"projeto": "Cobranças__A__ATU20260928", "area": "Cobrança",
                      "escopo_indi": False}]
    pipe = [dict(PIPE_BASE[0], egp_vinculo_tipo="Substituído",
                 egp_sucessor="Cobranças__A__ATU20260928")]
    depois = _scope_egps(pipe, ESCOPO_BASE, nodes)
    assert depois["n_egps"] == antes["n_egps"]      # total base NÃO se mexe
    assert depois["n_base"] == antes["n_base"]
    assert depois["n_extra"] == 1                   # o contador próprio sobe


def test_casca_nao_mexe_no_total_base():
    antes = _scope_egps(PIPE_BASE, ESCOPO_BASE)
    # a casca nasce no publish: nó com escopo_indi=True + 1 linha em sas_escopo
    # (origem='casca'), que serve à VISIBILIDADE e nunca à contagem (§3.6.24).
    nodes = NODES + [{"projeto": "Cobranças__casca", "area": "Cobrança", "escopo_indi": True}]
    escopo = ESCOPO_BASE + [{"projeto": "Cobranças__casca", "area": "Cobrança",
                             "origem": "casca", "ativo": True, "status_extracao": "exato"}]
    depois = _scope_egps(PIPE_BASE, escopo, nodes)
    assert depois["n_egps"] == antes["n_egps"]
    assert depois["n_base"] == antes["n_base"]
    assert depois["n_extra"] == 1


def test_funil_por_area_nao_conta_casca():
    """O recompute recria sas_funil_area a partir de sas_escopo. Sem a guarda, a linha da
    casca (status_extracao='exato') faria a Cobrança subir +1 por casca."""
    stmts = []

    def exec_fn(sql, want_rows=True):
        stmts.append(" ".join(sql.split()))
        return []

    with patch.object(m, "_recompute_area_principal", lambda *a, **k: None), \
            patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None), \
            patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True):
        m.recompute_escopo(exec_fn=exec_fn)
    insert = [s for s in stmts if "INSERT INTO" in s and "sas_funil_area" in s]
    assert len(insert) == 1, stmts
    assert "origem" in insert[0] and m.vinculos.ORIGEM_CASCA in insert[0], insert[0]

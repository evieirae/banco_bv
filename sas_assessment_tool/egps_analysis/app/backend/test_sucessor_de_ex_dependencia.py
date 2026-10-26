# -*- coding: utf-8 -*-
"""O sucessor de uma ex-dependência continua no recorte.

A ex-dependência é RETIDA com badge para "o esforço não sumir" (`_ex_deps`). A versão nova
dela não era: a cadeia de sucessores era semeada só com o fecho PODADO, então no instante
em que a via do antecessor entrava no lake o antecessor virava ex-dependência (certo) e o
sucessor dele sumia de TODAS as telas (errado — ninguém desfez trabalho nenhum).

Medido em prod 07/10/2026: `PAGOSCBR.PAGOS_CYBER_202603` virou Modernizado em 06/10 19:35;
era a única via que puxava o `Performance_Saldo_COLORE_…_Lite_V5`, e o `…__ATU20260901`
(21 inputs no recorte) saiu junto. O contador de extras caiu de 33 para 32 sem que EGP
algum tivesse sido resolvido.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m

# A --(via T)--> DEP: a aresta existe no grafo BRUTO. DEP tem um sucessor, DEP_NOVO.
NODES = [
    {"projeto": "Cob__A", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cob__DEP", "area": "Cobrança", "escopo_indi": False},
    {"projeto": "Cob__DEP_NOVO", "area": "Cobrança", "escopo_indi": False},
]
EDGES = [{"projeto_alvo": "Cob__A", "depende_do": "Cob__DEP", "via_tabelas": "LIB.T"}]
PIPE = [
    {"projeto": "Cob__A", "etapa_migracao": "Conversão do Código",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
    {"projeto": "Cob__DEP", "etapa_migracao": "Pré-conversão", "status_migracao": "A Iniciar",
     "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "Cob__DEP_NOVO"},
]
ESCOPO = [{"projeto": "Cob__A", "area": "Cobrança", "origem": "dor1", "ativo": True,
           "status_extracao": "exato"}]


def _fake_db(via_resolvida):
    """`via_resolvida`: a aresta sobrevive à poda? False = LIB.T entrou no lake."""
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if not want_rows:
            return []
        if "sas_lineage_edges" in s:
            return [dict(e) for e in EDGES]
        if "sas_lineage_nodes" in s:
            rows = [n for n in NODES if "escopo_indi = true" not in s or n["escopo_indi"]]
            return [{"n": len(rows)}] if "count(*)" in s else [dict(r) for r in rows]
        if "sas_egp_pipeline" in s:
            return [dict(r) for r in PIPE]
        if "sas_escopo" in s:
            return [{"n": len(ESCOPO)}] if "count(*)" in s else [dict(r) for r in ESCOPO]
        return []
    return fake_run_sql


def _frontier(via_resolvida):
    m._lineage_cache.clear()
    # a poda é o que a resolução da via faz: sem ela, a aresta some do grafo PODADO
    podadas = [] if via_resolvida else list(EDGES)
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(via_resolvida)),
        patch.object(m, "_edges_pruned", lambda: [dict(e) for e in podadas]),
        patch.object(m, "_egps_fora_backlog", lambda: set()),
        patch.object(m, "_cascas", lambda: set()),
        patch.object(m, "_egps_novos", lambda: set()),
        patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        return m._frontier_egps("indi_deps", [])[0]
    finally:
        for p in patches:
            p.stop()
        m._lineage_cache.clear()


def test_com_a_via_viva_o_sucessor_entra_pelo_antecessor():
    f = _frontier(via_resolvida=False)
    assert "Cob__DEP" in f and "Cob__DEP_NOVO" in f


def test_via_ingerida_tira_o_antecessor_mas_NAO_o_sucessor():
    """O coração do caso: o antecessor sai do frontier (vira ex-dependência, retida com
    badge por `_ex_deps`) e a versão nova dele CONTINUA no recorte."""
    f = _frontier(via_resolvida=True)
    assert "Cob__DEP" not in f, "antecessor deve virar ex-dependência"
    assert "Cob__DEP_NOVO" in f, "a versão nova não pode sumir junto"


def test_retidos_e_o_fecho_bruto_nao_o_podado():
    """`_retidos` ignora a poda de propósito — é a mesma pergunta que `_ex_deps` faz."""
    m._lineage_cache.clear()
    with patch.object(m, "run_sql", side_effect=_fake_db(True)):
        assert m._retidos({"Cob__A"}) == {"Cob__A", "Cob__DEP"}
    m._lineage_cache.clear()


def test_sucessor_que_tambem_esta_no_fecho_bruto_nao_e_engolido():
    """A semente é subtraída do retorno de `cadeia_de_sucessores`; quem está nos dois
    conjuntos tem de voltar. Na 1ª versão desta correção, 5 sucessores sumiram por isso."""
    nodes = NODES + [{"projeto": "Cob__B", "area": "Cobrança", "escopo_indi": True}]
    edges = EDGES + [{"projeto_alvo": "Cob__B", "depende_do": "Cob__DEP_NOVO",
                      "via_tabelas": "LIB.U"}]
    m._lineage_cache.clear()
    patches = [
        patch.object(m, "run_sql", side_effect=lambda stmt, want_rows=True: (
            [dict(e) for e in edges] if "sas_lineage_edges" in " ".join(stmt.split()).lower()
            else [dict(n) for n in nodes if n["escopo_indi"]]
            if "sas_lineage_nodes" in " ".join(stmt.split()).lower()
            else [dict(r) for r in PIPE]
            if "sas_egp_pipeline" in " ".join(stmt.split()).lower() else [])),
        patch.object(m, "_edges_pruned", lambda: []),      # tudo podado
        patch.object(m, "_egps_fora_backlog", lambda: set()),
        patch.object(m, "_cascas", lambda: set()),
        patch.object(m, "_egps_novos", lambda: set()),
    ]
    for p in patches:
        p.start()
    try:
        f = m._frontier_egps("indi_deps", [])[0]
    finally:
        for p in patches:
            p.stop()
        m._lineage_cache.clear()
    assert "Cob__DEP_NOVO" in f, "sucessor que também está no fecho bruto foi engolido"


def test_sucessor_cujo_antecessor_nao_esta_retido_nao_entra_pelo_fecho_bruto():
    """A volta do sucessor que está no fecho bruto vale só para sucessor de quem está na
    semente. O EGP alcançado pelo grafo bruto cuja versão ANTIGA não está retida em lugar
    nenhum é ex-dependência como qualquer outro: "sucessor entra por regra" exige o
    antecessor no recorte (spec §3.1.2). Antes, `_ret & sucessores(_vinc)` o trazia para o
    recorte — contado como extra — só por ser sucessor de alguém. Sem caso em prod em
    08/10/2026 (27 sucessores pelas duas regras); o teste fixa a regra para quando houver."""
    nodes = [{"projeto": "Cob__A2", "area": "Cobrança", "escopo_indi": True},
             {"projeto": "Cob__ANT", "area": "Cobrança", "escopo_indi": False},
             {"projeto": "Cob__SUC", "area": "Cobrança", "escopo_indi": False}]
    edges = [{"projeto_alvo": "Cob__A2", "depende_do": "Cob__SUC", "via_tabelas": "LIB.V"}]
    pipe = [{"projeto": "Cob__ANT", "etapa_migracao": "Pré-conversão",
             "status_migracao": "A Iniciar", "egp_vinculo_tipo": "Atualizado",
             "egp_sucessor": "Cob__SUC"}]

    def fake(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if "sas_lineage_edges" in s:
            return [dict(e) for e in edges]
        if "sas_lineage_nodes" in s:
            return [dict(n) for n in nodes if n["escopo_indi"]]
        if "sas_egp_pipeline" in s:
            return [dict(r) for r in pipe]
        return []

    m._lineage_cache.clear()
    patches = [
        patch.object(m, "run_sql", side_effect=fake),
        patch.object(m, "_edges_pruned", lambda: []),      # via LIB.V já no lake
        patch.object(m, "_egps_fora_backlog", lambda: set()),
        patch.object(m, "_cascas", lambda: set()),
        patch.object(m, "_egps_novos", lambda: set()),
    ]
    for p in patches:
        p.start()
    try:
        f = m._frontier_egps("indi_deps", [])[0]
    finally:
        for p in patches:
            p.stop()
        m._lineage_cache.clear()
    assert "Cob__SUC" not in f, "sucessor sem antecessor retido entrou no recorte pelo fecho bruto"

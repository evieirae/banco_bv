# -*- coding: utf-8 -*-
"""A régua CONGELADA nos ENDPOINTS (decisão da gestão, 29/09/2026).

O total de EGPs deixou de ser calculado: é o tamanho de uma LISTA versionada. Este arquivo
prova, no mesmo processo e sem rede, as quatro consequências que a decisão tem de ter:

1. **o total não se mexe.** O corpus cresce (versão nova, casca, dependência inédita) e
   `total_egps` continua sendo o tamanho da lista — em landing, funis e scope-egps;
2. **fora da lista = fora do total**, inclusive quem o grafo classificaria como
   DEPENDÊNCIA. Ela conta à parte, como `extra` (decisão de 13/10/2026: "os 193 estão
   fechados; dependência que vier vira extra"; ver `test_extra_enumeracao.py`);
3. **congelado nos dois lados**: quem sai do escopo continua no denominador, e o
   `Despriorizado e Contabilizado` segue dentro;
4. **denominador congelado, numerador VIVO**: mudar a etapa de um dos contáveis muda a
   distribuição do funil e não muda o total. Congelar demais seria tão errado quanto não
   congelar.

run_sql stubado e `_linha_base` injetado — sem credencial, sem rede, sem CSV real.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

# Corpus: 2 EGPs de escopo (A, B) + 1 dependência transitiva (C produz para B).
NODES = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__B", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__C", "area": "Cobrança", "escopo_indi": False},
]
EDGES = [{"projeto_alvo": "Cobranças__B", "depende_do": "Cobranças__C", "via_tabelas": ""}]
ESCOPO = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": "Cobranças__B", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
]
PIPE = [
    {"projeto": "Cobranças__A", "etapa_migracao": "Conversão do Código",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
    {"projeto": "Cobranças__B", "etapa_migracao": "Validação em DES",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
]
# A linha de base congelada deste corpus: A e B contam como base, C como dependência.
LB = {"Cobranças__A": "base", "Cobranças__B": "base", "Cobranças__C": "dependencia"}


def _fake_db(pipe_rows, escopo_rows, nodes, edges):
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if not want_rows:
            return []
        if "sas_lineage_edges" in s:
            return [dict(e) for e in edges]
        if "sas_lineage_nodes" in s:
            rows = [n for n in nodes if "escopo_indi = true" not in s or n["escopo_indi"]]
            if "count(*)" in s:
                return [{"n": len(rows)}]
            return [dict(r) for r in rows]
        if "sas_egp_pipeline" in s:
            rows = pipe_rows
            if "despriorizado e contabilizado" in s:
                rows = [r for r in rows
                        if r.get("status_migracao") == "Despriorizado e Contabilizado"]
            return [dict(r) for r in rows]
        if "sas_escopo" in s:
            rows = escopo_rows
            if "origem = 'casca'" in s:
                rows = [r for r in rows if r.get("origem") == m.vinculos.ORIGEM_CASCA]
            elif m.SQL_ESC_NAO_EXTRA.lower() in s:
                rows = [r for r in rows if r.get("origem") != m.vinculos.ORIGEM_CASCA]
            if "count(*)" in s:
                return [{"n": len(rows)}]
            return [dict(r) for r in rows]
        # inputs: fora do assunto deste arquivo (a régua é de EGP), mas a landing agrega
        # sobre eles — devolve zeros em vez de [] p/ não estourar no [0]["n"].
        if "count(" in s:
            return [{"n": 0, "tot": 0, "aing": 0}]
        return []
    return fake_run_sql


def _get(rota, params=None, *, pipe=PIPE, escopo=ESCOPO, nodes=NODES, edges=EDGES,
         linha_base=LB):
    m._lineage_cache.clear()      # cache é por geração: limpar entre "antes" e "depois"
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(pipe, escopo, nodes, edges)),
        patch.object(m, "_linha_base", lambda: dict(linha_base)),
        patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        r = TestClient(m.app).get(rota, params=params or {})
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        for p in patches:
            p.stop()


def _corpus_maior():
    """O corpus cresce por TRÊS portas ao mesmo tempo: uma versão nova (sucessor), uma
    casca e uma dependência INÉDITA — esta última é o caso que a régua anterior somava
    calada no denominador."""
    nodes = NODES + [
        {"projeto": "Cobranças__A__ATU20260929", "area": "Cobrança", "escopo_indi": False},
        {"projeto": "Cobranças__casca", "area": "Cobrança", "escopo_indi": True},
        {"projeto": "Cobranças__D", "area": "Cobrança", "escopo_indi": False},
    ]
    edges = EDGES + [{"projeto_alvo": "Cobranças__A", "depende_do": "Cobranças__D",
                      "via_tabelas": ""}]
    escopo = ESCOPO + [{"projeto": "Cobranças__casca", "area": "Cobrança",
                        "origem": m.vinculos.ORIGEM_CASCA, "ativo": True,
                        "status_extracao": "exato"}]
    pipe = [dict(PIPE[0], egp_vinculo_tipo="Substituído",
                 egp_sucessor="Cobranças__A__ATU20260929"), dict(PIPE[1])]
    return dict(nodes=nodes, edges=edges, escopo=escopo, pipe=pipe)


# ---- 1. o total é a lista -----------------------------------------------------

def test_total_e_o_tamanho_da_lista_venha_o_que_vier_no_corpus():
    antes = _get("/api/scope-egps", {"scope": "indi_deps"})
    assert antes["n_egps"] == 3 and antes["n_extra"] == 0
    depois = _get("/api/scope-egps", {"scope": "indi_deps"}, **_corpus_maior())
    assert depois["n_egps"] == 3, "o corpus cresceu e o total foi junto"
    # 3 extras (sucessor + casca + a dependência inédita D) — todos fora do total.
    assert depois["n_extra"] == 3, depois


def test_dependencia_inedita_nao_conta_mas_vira_extra():
    """`Cobranças__D` é dependência pelo GRAFO (A depende de D) e não está na lista: não
    entra no total, e conta à parte como extra (decisão da gestão, 13/10/2026).

    *(Até ali ficava sem rótulo — herança da correção de 29/09/2026, quando a régua
    "extra = recorte − lista" foi trocada pela enumeração para parar de rotular as 16
    ex-dependências. A dependência nova agora é uma perna NOMEADA da enumeração; a
    ex-dependência continua vetada.)*"""
    extras = _get("/api/egps-extras", **_corpus_maior())
    assert "Cobranças__D" in extras["projetos"], extras
    motivos = {x["projeto"]: x["motivo"] for x in extras["rows"]}
    assert motivos["Cobranças__D"] == "dependencia"
    # e continua fora do denominador: o total não se mexeu
    assert _get("/api/landing", **_corpus_maior())["total_egps"] == 3


def test_landing_total_egps_e_a_lista():
    assert _get("/api/landing")["total_egps"] == 3
    assert _get("/api/landing", **_corpus_maior())["total_egps"] == 3


def test_decomposicao_vem_da_classe_gravada_no_csv():
    """base / dependências / ex-dependências saem da CLASSE do CSV, não do grafo vivo:
    aqui C é `dependencia` na lista e o grafo concorda, mas quem manda é a lista."""
    lb = dict(LB, **{"Cobranças__EX": "ex_dependencia"})
    r = _get("/api/scope-egps", {"scope": "indi_deps"}, linha_base=lb)
    assert (r["n_base"], r["n_deps"], r["n_ex"]) == (2, 1, 1)
    assert r["n_egps"] == 4
    lg = _get("/api/landing", linha_base=lb)
    assert (lg["egps_escopo"], lg["deps"], lg["deps_ex"]) == (2, 1, 1)
    assert lg["total_egps"] == 4


# ---- 2/3. congelado nos dois lados --------------------------------------------

def test_quem_sai_do_escopo_continua_no_denominador():
    """O escopo encolhe (B sai de sas_escopo e do nó) e o total não se mexe."""
    nodes = [n for n in NODES if n["projeto"] != "Cobranças__B"]
    escopo = [e for e in ESCOPO if e["projeto"] != "Cobranças__B"]
    r = _get("/api/scope-egps", {"scope": "indi_deps"}, nodes=nodes, escopo=escopo,
             edges=[])
    assert r["n_egps"] == 3
    assert _get("/api/landing", nodes=nodes, escopo=escopo, edges=[])["total_egps"] == 3


def test_despriorizado_continua_dentro_dos_contaveis():
    pipe = [dict(PIPE[0], status_migracao="Despriorizado e Contabilizado"), dict(PIPE[1])]
    r = _get("/api/scope-egps", {"scope": "indi_deps"}, pipe=pipe)
    assert r["n_egps"] == 3 and r["n_base"] == 2
    f = _get("/api/funis", pipe=pipe)
    assert f["migracao_deps"]["total"] == 3


# ---- 4. denominador congelado, numerador VIVO ---------------------------------

def _dist(funil):
    """Como os EGPs se distribuem nas barras (cumulativas) — a parte VIVA do funil."""
    return {b["etapa"]: dict(b["seg"]) for b in funil["bars"]}


def test_o_funil_continua_vivo_com_o_denominador_parado():
    """Mudar a etapa de um contável tem de mexer a distribuição e NÃO mexer o total. Se a
    distribuição não mudar, congelou-se demais."""
    antes = _get("/api/funis")["migracao_deps"]
    pipe = [dict(PIPE[0], etapa_migracao="Validação em DES"), dict(PIPE[1])]
    depois = _get("/api/funis", pipe=pipe)["migracao_deps"]
    assert antes["total"] == depois["total"] == 3
    assert _dist(antes) != _dist(depois), "a distribuição do funil congelou junto"


def test_migrados_continua_vivo():
    pipe = [dict(PIPE[0], status_migracao="Migrado"), dict(PIPE[1])]
    antes = _get("/api/funis")["migracao_deps"]
    depois = _get("/api/funis", pipe=pipe)["migracao_deps"]
    assert depois["migrados"] == antes["migrados"] + 1
    assert depois["total"] == antes["total"] == 3


def test_extra_nao_entra_no_coorte_dos_dois_funis_antigos():
    """O extra segue no funil PRÓPRIO; os dois antigos não somam por causa dele."""
    antes = _get("/api/funis")
    depois = _get("/api/funis", **_corpus_maior())
    assert depois["migracao"] == antes["migracao"]
    assert depois["migracao_deps"]["total"] == antes["migracao_deps"]["total"]


# ---- 5. o contador de extras diz quantos E quais ------------------------------

def test_endpoint_de_extras_lista_quais_sao():
    r = _get("/api/egps-extras", **_corpus_maior())
    assert r["n"] == 3
    assert {x["projeto"] for x in r["rows"]} == {
        "Cobranças__A__ATU20260929", "Cobranças__casca", "Cobranças__D"}
    motivos = {x["projeto"]: x["motivo"] for x in r["rows"]}
    assert motivos["Cobranças__A__ATU20260929"] == "sucessor"
    assert motivos["Cobranças__casca"] == "casca"


def test_sem_extras_o_endpoint_vem_vazio():
    r = _get("/api/egps-extras")
    assert r["n"] == 0 and r["rows"] == []

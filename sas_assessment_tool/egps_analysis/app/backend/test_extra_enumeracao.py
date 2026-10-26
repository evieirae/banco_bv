# -*- coding: utf-8 -*-
"""`extra` é uma ENUMERAÇÃO, não "todo o resto do corpus" (correção de 29/09/2026).

O ticket 19 trocou a régua de extra de enumeração (sucessores ∪ cascas) para definição
(recorte − linha de base). Ficou mais simples e varreu junto uma 3ª categoria que ninguém
pretendia: a **ex-dependência que não entra na contagem**. Em produção isso marcou 16
ex-dependências como `extra · novo` — um rótulo que afirma "chegou depois do
congelamento" sobre EGPs que estão no corpus desde junho.

O que este arquivo tranca, com o endpoint inteiro (fake DB, sem rede):

1. extra é uma lista de quem chegou depois do congelamento e foi NOMEADO: o sucessor
   apontado por um vínculo, a casca e — desde 13/10/2026 — a DEPENDÊNCIA nova que o grafo
   puxou ("os 193 estão fechados; dependência que vier vira extra");
2. **ex-dependência nunca é extra** — o badge de ex-dependência já basta;
3. a **TELA e o CONTADOR concordam**: o conjunto de linhas com `e_extra` é exatamente o
   `extra_count` do card (o defeito media 37 × 18);
4. o **total continua congelado** na linha de base — o que mudou foi só quem se chama
   extra, nunca o denominador.
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

ANTE = "Cobranças__A"
OUTRO = "Cobranças__B"
SUC = "Cobranças__A__ATU20260928"      # versão nova: extra por SUCESSOR
CASCA = "Cobranças__casca"             # antecessor sem inventário: extra por CASCA
NOVO = "Cobranças__D"                  # dependência INÉDITA: fora da lista -> extra (13/10/2026)
EXDEP = "Cobranças__EX"                # ex-dependência fora da lista: NUNCA é extra

NODES = [
    {"projeto": ANTE, "area": "Cobrança", "escopo_indi": True},
    {"projeto": OUTRO, "area": "Cobrança", "escopo_indi": True},
    {"projeto": SUC, "area": "Cobrança", "escopo_indi": False},
    {"projeto": CASCA, "area": "Cobrança", "escopo_indi": True},
    {"projeto": NOVO, "area": "Cobrança", "escopo_indi": False},
    {"projeto": EXDEP, "area": "Cobrança", "escopo_indi": False},
]
# NOVO produz para ANTE -> entra no recorte como dependência transitiva pelo GRAFO.
EDGES = [{"projeto_alvo": ANTE, "depende_do": NOVO, "via_tabelas": ""}]
ESCOPO = [
    {"projeto": ANTE, "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": OUTRO, "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": CASCA, "area": "Cobrança", "origem": m.vinculos.ORIGEM_CASCA,
     "ativo": True, "status_extracao": "exato"},
]
PIPE = [
    {"projeto": ANTE, "etapa_migracao": "Conversão do Código",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "Atualizado",
     "egp_sucessor": SUC},
    {"projeto": OUTRO, "etapa_migracao": "Conversão do Código",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
    {"projeto": SUC, "etapa_migracao": "Validação em DES",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
]
# A linha de base congelada DESTE corpus: SUC, CASCA, NOVO e EXDEP ficam de fora.
LB = {ANTE: "base", OUTRO: "base"}


def _fake_db(stmt, want_rows=True):
    s = " ".join(stmt.split()).lower()
    if not want_rows:
        return []
    if "sas_app_config" in s and "ex_deps_manuais" in s:
        # retenção manual: é o jeito determinístico de fabricar uma ex-dependência sem
        # depender da poda de arestas (§_ex_deps, 'retida manualmente').
        return [{"valor": json.dumps([EXDEP])}]
    if "sas_lineage_edges" in s:
        return [dict(e) for e in EDGES]
    if "as n_inputs" in s:
        return [{"projeto": n["projeto"], "area": n["area"], "onda": "", "ciclo_id": 0,
                 "escopo_indi": n["escopo_indi"], "n_inputs": 0, "n_faltam": 0,
                 "n_links_broken": 0}
                for n in NODES
                if "e.escopo_indi = true" not in s or n["escopo_indi"]]
    if "sas_lineage_nodes" in s:
        rows = [n for n in NODES if "escopo_indi = true" not in s or n["escopo_indi"]]
        if "count(*)" in s:
            return [{"n": len(rows)}]
        return [dict(r) for r in rows]
    if "sas_egp_pipeline" in s:
        rows = [dict(r) for r in PIPE]
        if "despriorizado e contabilizado" in s:
            rows = [r for r in rows
                    if r.get("status_migracao") == "Despriorizado e Contabilizado"]
        return rows
    if "sas_escopo" in s:
        rows = ESCOPO
        if "origem = 'casca'" in s:
            rows = [r for r in rows if r.get("origem") == m.vinculos.ORIGEM_CASCA]
        elif m.SQL_ESC_NAO_EXTRA.lower() in s:
            rows = [r for r in rows if r.get("origem") != m.vinculos.ORIGEM_CASCA]
        if "count(*)" in s:
            return [{"n": len(rows)}]
        return [dict(r) for r in rows]
    if "count(" in s and "sas_inputs_monitor" in s and "group by" not in s:
        # inputs: fora do assunto deste arquivo (a régua é de EGP), mas a landing agrega
        # sobre eles — devolve zeros em vez de [] p/ não estourar no [0]["n"].
        return [{"n": 0, "tot": 0, "aing": 0}]
    return []


def _get(rota, params=None, linha_base=LB):
    m._lineage_cache.clear()
    m._endpoint_cache.clear()
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db),
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


def _readiness():
    pay = _get("/api/egp-readiness", {"scope": "indi_deps"})
    return pay, {r["projeto"]: r for r in pay["rows"]}


# ---- 1. extra é enumeração ----------------------------------------------------

def test_extra_e_sucessor_casca_e_dependencia_nova():
    _pay, by = _readiness()
    extras = {p for p, r in by.items() if r["e_extra"]}
    assert extras == {SUC, CASCA, NOVO}, extras
    assert by[SUC]["extra_motivo"] == "sucessor"
    assert by[CASCA]["extra_motivo"] == "casca"
    assert by[NOVO]["extra_motivo"] == "dependencia"


def test_dependencia_inedita_vira_extra():
    """`NOVO` é dependência pelo grafo e está FORA da linha de base. Até 13/10/2026 ficava
    fora de tudo como EGP enquanto os inputs dele entravam no card de dependências — 11
    dependências na tela e os inputs de 12. Decisão da gestão: os 193 estão fechados, a
    dependência que vier vira extra. Continua fora do total; o que muda é o rótulo e o
    balde dos inputs. O `tipo` (posição no grafo) não muda: ela É uma dependência."""
    _pay, by = _readiness()
    assert by[NOVO]["e_extra"] is True
    assert by[NOVO]["extra_motivo"] == "dependencia"
    assert by[NOVO]["extra_tipos"] == ["dependencia"]
    assert by[NOVO]["tipo"] == "dependencia"


# ---- 2. ex-dependência nunca é extra ------------------------------------------

def test_ex_dependencia_nunca_e_extra():
    """O badge de ex-dependência já basta; ela não recebe um segundo rótulo. Em produção
    eram 16 ex-dependências marcadas `extra · novo` — nenhuma chegou depois de nada."""
    _pay, by = _readiness()
    assert by[EXDEP]["tipo"] == "ex_dependencia"
    assert by[EXDEP]["e_extra"] is False
    assert by[EXDEP]["extra_motivo"] is None
    assert not any(r["e_extra"] for r in by.values() if r["tipo"] == "ex_dependencia")


# ---- 3. a tela e o contador concordam -----------------------------------------

def test_tela_e_contador_falam_do_mesmo_conjunto():
    """O defeito media 37 na tela × 18 no contador: a ex-dependência não está no frontier
    (por definição deixou de ser dependência), mas era listada e marcada `e_extra`."""
    pay, by = _readiness()
    tela = {p for p, r in by.items() if r["e_extra"]}
    assert pay["extra_count"] == len(tela) == 3, (pay["extra_count"], tela)


def test_endpoint_de_extras_lista_os_mesmos():
    """`/api/egps-extras` (tooltip do Resumo) e a aba EGPs não podem divergir."""
    r = _get("/api/egps-extras")
    assert r["n"] == 3
    assert set(r["projetos"]) == {SUC, CASCA, NOVO}
    assert {x["motivo"] for x in r["rows"]} == {"sucessor", "casca", "dependencia"}


# ---- 4. o denominador não se mexeu --------------------------------------------

def test_total_continua_congelado_na_linha_de_base():
    pay, by = _readiness()
    assert pay["total"] == len(LB) == 2
    assert _get("/api/landing")["total_egps"] == 2
    assert _get("/api/scope-egps", {"scope": "indi_deps"})["n_extra"] == 3


def test_linha_diz_se_conta_no_total():
    """`na_linha_base` é o critério de contagem servido POR LINHA: com ele o front para de
    reaplicar o critério "189" sobre a etapa viva (que deriva) e passa a ler a mesma lista
    congelada do card. Sem o campo, a lista da aba e o card divergem por drift de etapa."""
    _pay, by = _readiness()
    assert by[ANTE]["na_linha_base"] is True
    assert by[OUTRO]["na_linha_base"] is True
    for p in (SUC, CASCA, NOVO, EXDEP):
        assert by[p]["na_linha_base"] is False, p


def test_o_recorte_indi_deps_mostra_exatamente_a_linha_de_base():
    """Critério de aceite da gestão: tirando os extras e as linhas fora da lista (o chip
    de retenção), "Indicium + dependências" mostra exatamente os EGPs que contam."""
    _pay, by = _readiness()
    visiveis = {p for p, r in by.items() if not r["e_extra"] and r["na_linha_base"]}
    assert visiveis == set(LB), visiveis


def test_contavel_que_sumiu_do_corpus_continua_listado():
    """Congelado nos DOIS lados: um EGP da lista que saiu do grafo continua no
    denominador, logo precisa continuar NA LISTA — senão a tabela diz 192 e o card 193 e
    ninguém sabe qual EGP faltou. A linha vem vazia, que é o estado honesto."""
    sumido = "Cobranças__SUMIU"
    pay = _get("/api/egp-readiness", {"scope": "indi_deps"},
               linha_base=dict(LB, **{sumido: "base"}))
    by = {r["projeto"]: r for r in pay["rows"]}
    assert sumido in by, sorted(by)
    assert by[sumido]["na_linha_base"] is True
    assert by[sumido]["e_extra"] is False
    assert pay["total"] == 3

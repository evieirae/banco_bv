# -*- coding: utf-8 -*-
"""O terceiro funil do Resumo: os EXTRAS (spec §3.1.3).

Recorte, não entidade nova: mesmas 9 etapas de migração, mesma `proj_funnel`, só muda o
universo — os EGPs que entraram no corpus DEPOIS da linha de base (sucessores de qualquer
tipo de vínculo + cascas, exatamente o `vinculos.extras()`).

O que este arquivo TRAVA, na ordem em que os critérios foram pedidos:

1. o funil existe e fala o mesmo vocabulário de etapas dos outros dois;
2. **os dois funis existentes não mudam um número** quando um extra chega — provado por
   igualdade do dicionário inteiro (`migracao` e `migracao_deps` antes × depois), não por
   snapshot gravado: snapshot dá falso positivo (a prod deriva sozinha) e falso negativo
   (sem extra em prod o conjunto é vazio e um ponto esquecido passa batido);
3. extra SEM etapa aparece no funil (no denominador) sem entrar no coorte — o estado
   honesto do §3.1.3;
4. sem nenhum extra, e sem grafo publicado, o funil vem VAZIO em vez de quebrar.

O caso do vínculo `Substituído` é o que isola a mudança: ele NÃO espelha (§3.2), então o
antecessor fica byte a byte igual e qualquer diferença nos dois funis antigos só pode ter
vindo do terceiro.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import main as m

ETAPAS = m.PIPELINE_PROJETO["migracao"]

# Corpus mínimo: 2 EGPs de escopo + 1 dependência transitiva (C produz para B).
NODES = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__B", "area": "Cobrança", "escopo_indi": True},
    {"projeto": "Cobranças__C", "area": "Cobrança", "escopo_indi": False},
]
EDGES = [{"projeto_alvo": "Cobranças__B", "depende_do": "Cobranças__C", "via_tabelas": ""}]

ESCOPO_BASE = [
    {"projeto": "Cobranças__A", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": "Cobranças__B", "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
]
PIPE_BASE = [
    {"projeto": "Cobranças__A", "etapa_migracao": "Conversão do Código",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
    {"projeto": "Cobranças__B", "etapa_migracao": "Validação em DES",
     "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
]


def _fake_db(pipe_rows, escopo_rows, nodes, boom=()):
    """run_sql de mentira: despacha pela tabela citada no statement.

    `boom` = nomes de tabela que levantam HTTPException (simula grafo não publicado)."""
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        for t in boom:
            if t in s:
                raise HTTPException(502, f"Falha SQL: [TABLE_OR_VIEW_NOT_FOUND] The table or view `{t}` cannot be found.")
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
        return []
    return fake_run_sql


# Linha de base congelada DESTE corpus (régua de 29/09/2026): A, B e C contam; tudo que o
# teste injetar depois (sucessor, casca) é extra por não estar aqui. Sem injetar isto, o
# CSV real (193 projetos de prod) entraria em cena e o corpus inteiro viraria `extra`.
LB = {"Cobranças__A": "base", "Cobranças__B": "base", "Cobranças__C": "dependencia"}


def _funis(pipe_rows, escopo_rows, nodes=NODES, boom=()):
    m._lineage_cache.clear()      # cache é por geração: limpar entre "antes" e "depois"
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(pipe_rows, escopo_rows, nodes, boom)),
        patch.object(m, "_linha_base", lambda: dict(LB)),
        patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        r = TestClient(m.app).get("/api/funis")
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        for p in patches:
            p.stop()


def _casca(projeto="Cobranças__casca"):
    """Casca (§3.6): nó com escopo_indi=True + 1 linha em sas_escopo com origem='casca'."""
    return ({"projeto": projeto, "area": "Cobrança", "escopo_indi": True},
            {"projeto": projeto, "area": "Cobrança", "origem": m.vinculos.ORIGEM_CASCA,
             "ativo": True, "status_extracao": "exato"})


def test_funil_de_extras_existe_com_o_mesmo_vocabulario():
    f = _funis(PIPE_BASE, ESCOPO_BASE)
    assert "migracao_extras" in f, sorted(f)
    assert f["migracao_extras"]["stages"] == ETAPAS == f["migracao"]["stages"]


def test_sem_extra_o_funil_vem_vazio_em_vez_de_quebrar():
    ex = _funis(PIPE_BASE, ESCOPO_BASE)["migracao_extras"]
    assert (ex["coorte"], ex["migrados"], ex["total"]) == (0, 0, 0)
    assert [b["etapa"] for b in ex["bars"]] == ETAPAS
    assert all(not b["seg"] for b in ex["bars"]), ex["bars"]


def test_sem_grafo_publicado_o_funil_de_extras_vem_vazio():
    """Antes do 1º publish não há nós/arestas: o endpoint já degrada os outros funis e o
    terceiro não pode ser o que derruba a página."""
    f = _funis(PIPE_BASE, ESCOPO_BASE, boom=("sas_lineage_nodes", "sas_lineage_edges"))
    assert f["migracao_extras"]["coorte"] == 0
    assert f["migracao_extras"]["total"] == 0


def test_sucessor_entra_no_funil_de_extras_e_nao_nos_dois_antigos():
    """`Substituído` não espelha (§3.2), então o antecessor fica intacto: qualquer
    diferença nos dois funis antigos seria culpa do terceiro."""
    antes = _funis(PIPE_BASE, ESCOPO_BASE)
    suc = "Cobranças__A__ATU20260928"
    nodes = NODES + [{"projeto": suc, "area": "Cobrança", "escopo_indi": False}]
    pipe = [dict(PIPE_BASE[0], egp_vinculo_tipo="Substituído", egp_sucessor=suc),
            PIPE_BASE[1],
            {"projeto": suc, "etapa_migracao": "Implant. em PRD",
             "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""}]
    depois = _funis(pipe, ESCOPO_BASE, nodes)

    assert depois["migracao"] == antes["migracao"]
    assert depois["migracao_deps"] == antes["migracao_deps"]

    ex = depois["migracao_extras"]
    assert (ex["coorte"], ex["total"]) == (1, 1)
    seg = {b["etapa"]: b["seg"] for b in ex["bars"]}
    assert seg["Implant. em PRD"] == {"Em Andamento": 1}, ex["bars"]
    # cumulativo como nos outros funis: quem chegou em "Implant. em PRD" já passou por
    # "Conversão do Código"
    assert seg["Conversão do Código"] == {"Concluído": 1}, ex["bars"]
    # e ainda não chegou em "Migrado": lá ele aparece como "A Iniciar", a mesma convenção
    # dos outros dois funis (toda barra soma o coorte)
    assert seg["Migrado"] == {"A Iniciar": 1}, ex["bars"]


def test_casca_entra_no_funil_de_extras_e_nao_nos_dois_antigos():
    antes = _funis(PIPE_BASE, ESCOPO_BASE)
    no, esc = _casca()
    pipe = PIPE_BASE + [{"projeto": no["projeto"], "etapa_migracao": "Migrado",
                         "status_migracao": "Migrado", "egp_vinculo_tipo": "",
                         "egp_sucessor": ""}]
    depois = _funis(pipe, ESCOPO_BASE + [esc], NODES + [no])

    assert depois["migracao"] == antes["migracao"]
    assert depois["migracao_deps"] == antes["migracao_deps"]
    ex = depois["migracao_extras"]
    assert (ex["coorte"], ex["migrados"], ex["total"]) == (1, 1, 1)


def test_extra_sem_etapa_aparece_no_funil_sem_etapa():
    """§3.1.3: extra sem vínculo (logo, sem linha no funil) conta no denominador e fica
    fora do coorte — não some, e também não finge uma etapa que ninguém gravou."""
    no, esc = _casca()
    ex = _funis(PIPE_BASE, ESCOPO_BASE + [esc], NODES + [no])["migracao_extras"]
    assert (ex["coorte"], ex["migrados"], ex["total"]) == (0, 0, 1)
    assert all(not b["seg"] for b in ex["bars"]), ex["bars"]

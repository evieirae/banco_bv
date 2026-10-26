# -*- coding: utf-8 -*-
"""A etapa espelhada (§3.2.7) tem de ser a MESMA em toda superfície que exibe andamento.

O defeito que este arquivo tranca: `vinculos.anexa_vinculo()` era chamado num lugar só
(/api/egp-readiness), então a aba EGPs mostrava a etapa espelhada do antecessor e o Resumo
mostrava a etapa VELHA do mesmo EGP. A régua fechada com a gestão diz o contrário — "a
etapa irá correr junto com o EGP atualizado, e isso será visto nas tabelas de resumo dos
funis atuais".

E o contra-exemplo, igualmente importante: quem pergunta pelo ESTADO GRAVADO de gestão
(quem está despriorizado) continua lendo o status REAL. `Desatualizado` é derivado e o
status verdadeiro segue por baixo (§3.2.6/§3.2.9).

run_sql stubado — sem credencial, sem rede. Mesmo método de test_extras_contagem.py.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

ANTE = "Cobranças__A"
SUC = "Cobranças__A__ATU20260928"
OUTRO = "Cobranças__B"

NODES = [
    {"projeto": ANTE, "area": "Cobrança", "escopo_indi": True},
    {"projeto": OUTRO, "area": "Cobrança", "escopo_indi": True},
    {"projeto": SUC, "area": "Cobrança", "escopo_indi": False},
]
ESCOPO = [
    {"projeto": ANTE, "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
    {"projeto": OUTRO, "area": "Cobrança", "origem": "dor1", "ativo": True,
     "status_extracao": "exato"},
]


def _pipe(status_ante="Em Andamento", etapa_suc="Validação em DES", tipo="Atualizado"):
    return [
        {"projeto": ANTE, "etapa_migracao": "Conversão do Código",
         "status_migracao": status_ante, "egp_vinculo_tipo": tipo, "egp_sucessor": SUC},
        {"projeto": OUTRO, "etapa_migracao": "Conversão do Código",
         "status_migracao": "Em Andamento", "egp_vinculo_tipo": "", "egp_sucessor": ""},
        {"projeto": SUC, "etapa_migracao": etapa_suc, "status_migracao": "Em Andamento",
         "egp_vinculo_tipo": "", "egp_sucessor": ""},
    ]


def _fake_db(pipe_rows):
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if not want_rows:
            return []
        if "sas_lineage_edges" in s:
            return []
        if "as n_inputs" in s:
            # prontidão por EGP: 1 linha por projeto, sem input pendente (o que este
            # arquivo mede é etapa/status, não a fila de ingestão).
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
            rows = [dict(r) for r in pipe_rows]
            if "status_migracao = 'despriorizado e contabilizado'" in s:
                rows = [r for r in rows
                        if r.get("status_migracao") == "Despriorizado e Contabilizado"]
            return rows
        if "sas_escopo" in s:
            rows = [r for r in ESCOPO if r.get("origem") == "casca"] \
                if "origem = 'casca'" in s else ESCOPO
            if "count(*)" in s:
                return [{"n": len(rows)}]
            return [dict(r) for r in rows]
        return []
    return fake_run_sql


def _client(pipe_rows):
    m._lineage_cache.clear()
    m._endpoint_cache.clear()
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(pipe_rows)),
        # Linha de base congelada deste corpus (régua de 29/09/2026): ANTE e OUTRO contam,
        # SUC não — ele chegou depois. Sem injetar isto o CSV real (193 projetos de prod)
        # entraria em cena e o corpus inteiro deste arquivo viraria `extra`.
        patch.object(m, "_linha_base", lambda: {ANTE: "base", OUTRO: "base"}),
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


def _funis(pipe_rows):
    client, patches = _client(pipe_rows)
    try:
        r = client.get("/api/funis")
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        _stop(patches)


def _readiness(pipe_rows, scope="indi_deps"):
    client, patches = _client(pipe_rows)
    try:
        r = client.get("/api/egp-readiness", params={"scope": scope})
        assert r.status_code == 200, r.text
        return {x["projeto"]: x for x in r.json()["rows"]}
    finally:
        _stop(patches)


def _coluna(funil, etapa):
    """Segmentos da coluna `etapa` do funil (dict status -> n)."""
    for b in funil["bars"]:
        if b["etapa"] == etapa:
            return b["seg"]
    raise AssertionError(f"etapa {etapa} não está no funil: {[b['etapa'] for b in funil['bars']]}")


def test_funil_do_resumo_usa_a_etapa_espelhada():
    """O antecessor tem etapa gravada "Conversão do Código" e sucessor em "Validação em
    DES": o funil do Resumo tem de contá-lo na coluna do SUCESSOR, como a aba EGPs já faz."""
    f = _funis(_pipe())["migracao"]
    # na coluna do sucessor ele aparece com o status derivado; na coluna anterior, como
    # "Concluído" (já passou) — nunca como "Em Andamento" na etapa velha.
    # `Desatualizado` NÃO é banda (não está em BANDS): fosse, entraria em `migrados`.
    assert _coluna(f, "Validação em DES").get("Desatualizado") == 1, _coluna(f, "Validação em DES")
    # e a etapa VELHA passa a contar como já percorrida, não como "Em Andamento" ali
    assert _coluna(f, "Conversão do Código").get("Concluído") == 1


def test_aba_egps_e_resumo_nao_discordam():
    """Mesma etapa nas duas superfícies — é o sintoma que o ticket descreve."""
    rows = _readiness(_pipe())
    f = _funis(_pipe())["migracao"]
    assert rows[ANTE]["etapa"] == "Validação em DES"
    assert rows[ANTE]["status"] == "Desatualizado"
    # o funil colocou exatamente 1 EGP na etapa que a aba EGPs exibe
    assert _coluna(f, "Validação em DES").get("Desatualizado") == 1


def test_desatualizado_nunca_conta_como_migrado():
    """Sucessor em "Migrado" espelha a ETAPA, nunca o status: o antecessor segue
    `Desatualizado` e fica fora do KPI de migrados (§3.2.5/§3.2.8)."""
    f = _funis(_pipe(etapa_suc="Migrado"))["migracao"]
    assert _coluna(f, "Migrado").get("Desatualizado") == 1
    assert f["migrados"] == 0


def test_quem_esta_despriorizado_vem_do_status_real():
    """Antecessor JÁ despriorizado + vínculo: Despriorizado VENCE (§3.2.9). Ele continua
    no conjunto "fora do backlog" (que é o que recorta dependências app-wide) e nenhuma
    superfície troca o status dele por `Desatualizado`."""
    pipe = _pipe(status_ante="Despriorizado e Contabilizado")
    client, patches = _client(pipe)
    try:
        assert m._egps_fora_backlog() == {ANTE}
    finally:
        _stop(patches)
    rows = _readiness(pipe)
    assert rows[ANTE]["status"] == "Despriorizado e Contabilizado"
    assert rows[ANTE]["etapa"] == "Validação em DES"      # a ETAPA segue espelhada
    f = _funis(pipe)["migracao"]
    assert _coluna(f, "Validação em DES").get("Despriorizado e Contabilizado") == 1


def test_substituido_nao_espelha_etapa_em_superficie_nenhuma():
    """No Substituído as trajetórias são independentes (§3.2): o antecessor mantém a
    etapa e o status REAIS, na aba EGPs e no funil."""
    pipe = _pipe(tipo="Substituído")
    rows = _readiness(pipe)
    assert rows[ANTE]["etapa"] == "Conversão do Código"
    assert rows[ANTE]["status"] == "Em Andamento"
    f = _funis(pipe)["migracao"]
    assert _coluna(f, "Conversão do Código").get("Em Andamento") == 2   # ANTE + OUTRO


def test_drawer_do_egp_mostra_a_mesma_etapa_da_linha():
    """`/api/egp` alimenta o painel que abre em cima da própria linha da aba EGPs — os
    dois discordarem é o mesmo defeito, um clique adiante."""
    client, patches = _client(_pipe())
    try:
        r = client.get("/api/egp", params={"projeto": ANTE})
        assert r.status_code == 200, r.text
        mig = r.json()["pipeline"]["migracao"]
    finally:
        _stop(patches)
    assert mig["etapa"] == "Validação em DES"
    assert mig["status"] == "Desatualizado"


def test_a_linha_carrega_a_etapa_gravada_ao_lado_da_exibida():
    """`etapa` é a EXIBIDA e `etapa_real` é a GRAVADA. O front conta ex-dependência por
    `etapa_real` (contaNoTotalEgp) exatamente como o back (_ex_deps_contab): sem o campo,
    os dois lados usariam etapas diferentes para o MESMO denominador."""
    rows = _readiness(_pipe())
    assert rows[ANTE]["etapa"] == "Validação em DES"
    assert rows[ANTE]["etapa_real"] == "Conversão do Código"
    # sem vínculo as duas coincidem — nenhuma linha fica sem o campo
    assert rows[OUTRO]["etapa_real"] == rows[OUTRO]["etapa"] == "Conversão do Código"

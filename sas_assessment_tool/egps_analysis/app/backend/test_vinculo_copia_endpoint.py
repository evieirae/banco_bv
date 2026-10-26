# -*- coding: utf-8 -*-
"""Testes da CÓPIA do trabalho de gestão no ato do vínculo (ticket 07, spec §3.3.11).

run_sql stubado — sem credencial, sem rede. Diferente de test_vinculo_endpoint.py, aqui o
stub precisa distinguir a linha do ANTECESSOR da do SUCESSOR: é justamente o que a cópia
compara (só copia o que o sucessor ainda não tem).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

ANTECESSOR = "Cobranças__X"
SUCESSOR = "Cobranças__X__ATU20260923"
# o que o antecessor tem hoje no funil (o "trabalho de gestão" que precisa ir junto)
PIPE_ANTECESSOR = {"et": "Validação em DES", "st": "Em Andamento", "resp": "alguem@indicium.tech",
                   "resp_bv": None, "jira": "UDAA-4825", "pw": "false", "pw_data": None,
                   "atu_key": None, "vinc_tipo": None, "sucessor": None, "mes": 3,
                   "etapa": "Validação em DES", "mes_prioridade": 3, "jira_id": "UDAA-4825",
                   "responsavel": "alguem@indicium.tech"}


def _mk_client(sucessor_row=None, antecessor_row=None):
    """`sucessor_row` é a linha de sas_egp_pipeline do SUCESSOR (None = ainda sem linha)."""
    calls = {"sql": []}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = " ".join(stmt.split())
        low = s.lower()
        if low.startswith("select") and "sas_egp_pipeline" in low and " limit 0" not in low:
            if f"'{SUCESSOR}'" in s:
                return [dict(sucessor_row)] if sucessor_row else []
            if f"'{ANTECESSOR}'" in s:
                row = PIPE_ANTECESSOR if antecessor_row is None else antecessor_row
                return [dict(row)] if row else []
            return []
        if low.startswith("select") and "sas_lineage_nodes" in low:
            return [{"projeto": SUCESSOR}] if f"'{SUCESSOR}'" in s else []
        return []

    patches = [
        patch.object(m, "run_sql", side_effect=fake_run_sql),
        patch.object(m, "_require_gestao", lambda: None),
        patch.object(m, "_ensure_pipe_table", lambda: True),
    ]
    for p in patches:
        p.start()
    return TestClient(m.app), calls, patches


def _stop(patches):
    for p in patches:
        p.stop()


def _escritas_no_sucessor(calls):
    """Statements de escrita cuja LINHA ALVO é o sucessor.

    Casar só pelo nome não serve: o MERGE do ANTECESSOR também cita o sucessor (é ele que
    grava `egp_sucessor`). O alvo é o `USING (SELECT '<projeto>' ...)` do MERGE e o 2º
    valor do INSERT de auditoria.
    """
    alvo_merge = f"USING (SELECT '{SUCESSOR}' AS projeto)"
    alvo_audit = f", '{SUCESSOR}', 'migracao'"
    out = []
    for c in calls["sql"]:
        s = " ".join(c.split())
        if s.lower().startswith("merge") and alvo_merge in s:
            out.append(s)
        elif s.lower().startswith("insert") and alvo_audit in s:
            out.append(s)
    return out


def _vincula(client, tipo="Atualizado"):
    return client.patch("/api/egp-pipeline", json={
        "projeto": ANTECESSOR, "egp_vinculo_tipo": tipo, "egp_sucessor": SUCESSOR})


def test_vinculo_copia_etapa_mes_jira_e_responsavel_para_o_sucessor():
    client, calls, patches = _mk_client()
    try:
        assert _vincula(client).status_code == 200
        merge = [s for s in _escritas_no_sucessor(calls) if s.lower().startswith("merge")]
        assert len(merge) == 1, merge
        sql = merge[0]
        assert "etapa_migracao = 'Validação em DES'" in sql
        assert "mes_prioridade = 3" in sql          # coluna INT: literal sem aspas
        assert "jira_id = 'UDAA-4825'" in sql
        assert "responsavel = 'alguem@indicium.tech'" in sql
    finally:
        _stop(patches)


def test_copia_nao_leva_status_do_antecessor():
    """Nenhum status é alterado sem alguém ter clicado (§3.5.21)."""
    client, calls, patches = _mk_client()
    try:
        assert _vincula(client, "Substituído").status_code == 200
        for sql in _escritas_no_sucessor(calls):
            assert "status_migracao" not in sql, sql
            assert "Despriorizado" not in sql, sql
    finally:
        _stop(patches)


def test_copia_nao_sobrescreve_o_que_o_sucessor_ja_tem():
    client, calls, patches = _mk_client(sucessor_row={
        "etapa": "Conversão do Código", "mes_prioridade": 7, "jira_id": None,
        "responsavel": None, "vinc_tipo": None, "sucessor": None})
    try:
        assert _vincula(client).status_code == 200
        merge = [s for s in _escritas_no_sucessor(calls) if s.lower().startswith("merge")]
        assert len(merge) == 1, merge
        sql = merge[0]
        assert "etapa_migracao" not in sql and "mes_prioridade" not in sql
        assert "jira_id = 'UDAA-4825'" in sql
        assert "responsavel = 'alguem@indicium.tech'" in sql
    finally:
        _stop(patches)


def test_resalvar_a_mesma_classificacao_nao_recopia():
    """A cópia é um evento do ato do vínculo, não uma sincronização contínua."""
    ja_vinculado = dict(PIPE_ANTECESSOR, vinc_tipo="Substituído", sucessor=SUCESSOR)
    client, calls, patches = _mk_client(antecessor_row=ja_vinculado)
    try:
        assert _vincula(client, "Substituído").status_code == 200
        assert _escritas_no_sucessor(calls) == []
    finally:
        _stop(patches)


def test_editar_so_a_etapa_nao_toca_no_sucessor():
    """Depois do ato, cada um segue sozinho: escrita no antecessor fica no antecessor."""
    ja_vinculado = dict(PIPE_ANTECESSOR, vinc_tipo="Substituído", sucessor=SUCESSOR)
    client, calls, patches = _mk_client(antecessor_row=ja_vinculado)
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": ANTECESSOR, "etapa": "Conversão do Código"})
        assert r.status_code == 200, r.text
        assert _escritas_no_sucessor(calls) == []
    finally:
        _stop(patches)


def test_copia_respeita_a_guarda_da_etapa_espelhada_em_cadeia():
    """Cadeia v1 -> v2 -> v3: a etapa do v2 já é espelho do v3 e o servidor recusa
    escrevê-la (§3.2.7) — a cópia não fura a própria guarda."""
    client, calls, patches = _mk_client(sucessor_row={
        "etapa": None, "mes_prioridade": None, "jira_id": None, "responsavel": None,
        "vinc_tipo": "Atualizado", "sucessor": "Cobranças__X__ATU20261231"})
    try:
        assert _vincula(client).status_code == 200
        merge = [s for s in _escritas_no_sucessor(calls) if s.lower().startswith("merge")]
        assert len(merge) == 1, merge
        assert "etapa_migracao" not in merge[0]
        assert "jira_id = 'UDAA-4825'" in merge[0]
    finally:
        _stop(patches)


def test_copia_e_auditada_na_linha_do_sucessor():
    client, calls, patches = _mk_client()
    try:
        assert _vincula(client).status_code == 200
        aud = [s for s in _escritas_no_sucessor(calls) if s.lower().startswith("insert")]
        campos = {c for c in ("etapa_migracao", "mes_prioridade", "jira_id", "responsavel")
                  if any(f"'{c}'" in s for s in aud)}
        assert campos == {"etapa_migracao", "mes_prioridade", "jira_id", "responsavel"}, aud
    finally:
        _stop(patches)

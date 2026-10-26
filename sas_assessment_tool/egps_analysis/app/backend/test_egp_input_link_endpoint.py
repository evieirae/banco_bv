"""Testes do endpoint PATCH /api/egp-input-link. Usa FastAPI TestClient e stub
das dependências que batem no warehouse (run_sql, _require_gestao) — não
depende de credenciais nem de rede."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m


def _mk_client(gestao=True, existing_broken=None):
    """Cria um TestClient com run_sql/_require_gestao stubados. `existing_broken`
    controla o SELECT que verifica o valor anterior no state table."""
    calls = {"sql": [], "gen_before": m._lineage_gen}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = stmt.strip().lower()
        if s.startswith("select") and "from" in s and "sas_egp_input_link" in s and "audit" not in s:
            # simula o SELECT que lê o estado atual (para o valor_antigo do audit)
            if existing_broken is None:
                return []
            return [{"link_broken": existing_broken}]
        return []

    def fake_require_gestao():
        if not gestao:
            from fastapi import HTTPException
            raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")

    patch_a = patch.object(m, "run_sql", side_effect=fake_run_sql)
    patch_b = patch.object(m, "_require_gestao", side_effect=fake_require_gestao)
    patch_c = patch.object(m, "_ensure_link_tables", lambda: True)
    patch_a.start(); patch_b.start(); patch_c.start()
    client = TestClient(m.app)
    return client, calls, (patch_a, patch_b, patch_c)


def _stop(patches):
    for p in patches:
        p.stop()


def test_gestao_break_link_writes_state_and_audit_and_bumps_gen():
    c, calls, ps = _mk_client(gestao=True, existing_broken=None)
    try:
        gen0 = m._lineage_gen
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "Cobrancas__Foo", "chave_canonica": "tabela::T1",
                          "link_broken": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"ok": True, "projeto": "Cobrancas__Foo",
                        "chave_canonica": "tabela::T1", "link_broken": True}
        # 3 statements: SELECT estado atual + MERGE/INSERT em T_LINK + INSERT audit
        stmts = [s.lower() for s in calls["sql"]]
        assert any("select" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert any("sas_egp_input_link" in s and ("merge" in s or "insert into" in s and "audit" not in s) for s in stmts)
        assert any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
        assert m._lineage_gen == gen0 + 1
    finally:
        _stop(ps)


def test_restore_link_deletes_state_row_and_audits():
    """link_broken=false quando a linha existia → DELETE + audit."""
    c, calls, ps = _mk_client(gestao=True, existing_broken=True)
    try:
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": False})
        assert r.status_code == 200, r.text
        stmts = [s.lower() for s in calls["sql"]]
        assert any("delete from" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
    finally:
        _stop(ps)


def test_no_change_returns_ok_but_skips_audit():
    """link_broken já é o valor atual → não escreve audit (mesmo padrão de patch_input)."""
    c, calls, ps = _mk_client(gestao=True, existing_broken=True)
    try:
        gen0 = m._lineage_gen
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": True})
        assert r.status_code == 200
        stmts = [s.lower() for s in calls["sql"]]
        # SELECT rodou; audit não
        assert any("select" in s and "sas_egp_input_link" in s and "audit" not in s for s in stmts)
        assert not any("sas_egp_input_link_audit" in s and "insert" in s for s in stmts)
        # nada mudou → cache não bumpa
        assert m._lineage_gen == gen0
    finally:
        _stop(ps)


def test_non_gestao_gets_403():
    c, _calls, ps = _mk_client(gestao=False)
    try:
        r = c.patch("/api/egp-input-link",
                    json={"projeto": "P", "chave_canonica": "K", "link_broken": True})
        assert r.status_code == 403, r.text
    finally:
        _stop(ps)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")

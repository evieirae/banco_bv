#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duas falhas que degradavam para o lugar errado.

1. `familias.OverridesInvalidos` é `ValueError`, então escapava de todo
   `except HTTPException` do app e virava 500 genérico em QUALQUER rota que toque
   família — sem dizer que o culpado é um arquivo curado à mão.
2. `/api/audit?chave=...` promete `{"rows": []}` quando a auditoria não dá para ser lida,
   mas `_chaves_para_leitura` (que também consulta o warehouse) era chamado FORA do try —
   uma falha de permissão ali escapava como 403/502 em vez da lista vazia.
"""
import os
import sys
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402
import familias  # noqa: E402


def test_overrides_invalidos_viram_erro_com_nome_do_arquivo():
    cli = TestClient(m.app, raise_server_exceptions=False)
    with patch.object(m, "_ensure_gestao_tables", lambda: None), \
         patch.object(m, "_chaves_para_leitura",
                      lambda _c: (_ for _ in ()).throw(
                          familias.OverridesInvalidos("membros duplicados em LIB.X"))):
        r = cli.get("/api/gestao/status", params={"entity": "input", "id": "tabela::LIB.X"})
    assert r.status_code == 500
    corpo = r.json().get("detail", "")
    assert "familias_overrides.json" in corpo, corpo
    assert "membros duplicados em LIB.X" in corpo, corpo


def test_audit_devolve_lista_vazia_quando_a_resolucao_de_familia_falha():
    cli = TestClient(m.app, raise_server_exceptions=False)
    with patch.object(m, "_chaves_para_leitura",
                      lambda _c: (_ for _ in ()).throw(
                          HTTPException(403, "sem permissão em sas_inputs_monitor"))):
        r = cli.get("/api/audit", params={"chave": "tabela::LIB.X"})
    assert r.status_code == 200, r.text
    assert r.json() == {"rows": []}


def test_audit_normal_continua_funcionando():
    cli = TestClient(m.app, raise_server_exceptions=False)
    linhas = [{"chave_canonica": "tabela::LIB.X", "campo": "etapa", "valor_antigo": None,
               "valor_novo": "Recebido", "updated_by": "a@b.c", "updated_at": "2026-09-01"}]
    with patch.object(m, "_chaves_para_leitura", lambda c: [c]), \
         patch.object(m, "run_sql", lambda *a, **k: linhas):
        r = cli.get("/api/audit", params={"chave": "tabela::LIB.X"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert len(rows) == 1 and rows[0]["fonte"] == "Monitoramento"

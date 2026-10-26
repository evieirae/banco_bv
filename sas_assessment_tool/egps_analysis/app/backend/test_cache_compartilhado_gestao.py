# -*- coding: utf-8 -*-
"""Cache compartilhado NÃO abre o que é restrito ao grupo de gestão (bv_users).

A chave do cache deixou de levar a identidade (2026-10). Isso só é seguro se (1) nenhum
cálculo cacheado depender de QUEM pede — gate de grupo, `current_user()`, `is_member` — e
(2) os endpoints restritos checarem o grupo no handler, ANTES de qualquer leitura de cache.
Os testes provam os dois com usuários diferentes passando pelo middleware OBO de verdade,
e o guarda estrutural quebra se alguém puser um gate dentro de um produtor cacheado.
run_sql stubado, sem rede."""
import ast
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import main as m

GESTAO = {"tok-gestor"}


def _fake(stmt, want_rows=True):
    s = " ".join(stmt.split())
    if "current_user()" in s and "sas_inputs_monitor" in s:          # _sessao
        tok = m._user_token.get()
        return [{"u": f"{tok}@x", "g": str(tok in GESTAO).lower(), "a": "false", "leitura": "1"}]
    if "sas_app_config" in s and "egps_novos" in s:
        return [{"valor": '["Area__NOVO"]'}]
    return []


@pytest.fixture(autouse=True)
def _limpo():
    for d in (m._lineage_cache, m._endpoint_cache, m._sessoes):
        d.clear()
    yield
    for d in (m._lineage_cache, m._endpoint_cache, m._sessoes):
        d.clear()


def test_quem_nao_e_gestao_leva_403_mesmo_com_o_cache_aquecido_por_um_gestor():
    with patch.object(m, "run_sql", side_effect=_fake), \
            patch.object(m, "_linha_base", lambda: {}):
        c = TestClient(m.app)
        r_gestor = c.get("/api/egps-novos", headers={"X-Forwarded-Access-Token": "tok-gestor"})
        assert r_gestor.status_code == 200, r_gestor.text
        assert m._lineage_cache, "o gestor devia ter aquecido os helpers cacheados"
        r_outro = c.get("/api/egps-novos", headers={"X-Forwarded-Access-Token": "tok-leitor"})
    assert r_outro.status_code == 403


def test_grupo_e_por_token_nunca_compartilhado():
    with patch.object(m, "run_sql", side_effect=_fake):
        m._user_token.set("tok-gestor")
        assert m._is_gestao() is True
        m._user_token.set("tok-leitor")
        assert m._is_gestao() is False
        with pytest.raises(HTTPException) as e:
            m._require_gestao()
    m._user_token.set(None)
    assert e.value.status_code == 403


# ---- guarda estrutural ---------------------------------------------------------------
CACHE = {"_cache_lineage", "_cache_endpoint", "_cache_scope_dataset"}
POR_USUARIO = {"_require_gestao", "_require_admin", "_is_gestao", "_is_admin"}
SQL_POR_USUARIO = ("is_member(", "is_account_group_member(")
# Maquinaria de autenticação (escolhe a credencial/prova a leitura — é O QUE protege o
# cache) e escrita que só carimba o autor (`updated_by = current_user()`).
PERMITIDOS = {"_sessao", "_autoriza_leitura", "_client", "_log_san_contadores"}


def test_nenhum_produtor_cacheado_depende_de_quem_pede():
    src = open(os.path.join(os.path.dirname(__file__), "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    funcs = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(n.name, n)

    def chama(node):
        return {x.func.id for x in ast.walk(node)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)} | \
               {x.id for x in ast.walk(node) if isinstance(x, ast.Name) and x.id in funcs}

    raizes = []
    for top in ast.walk(tree):
        if not isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        locais = {n.name: n for n in ast.walk(top)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not top}
        for n in ast.walk(top):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in CACHE:
                arg = n.args[1]
                no = arg if isinstance(arg, ast.Lambda) else (
                    locais.get(arg.id) or funcs.get(arg.id) if isinstance(arg, ast.Name) else None)
                assert no is not None, f"produtor não resolvido na linha {n.lineno}"
                raizes.append(no)
    assert len(raizes) >= 30, "o guarda deixou de achar os produtores — revise o teste"

    vistos, fila, problemas = set(), list(raizes), []
    while fila:
        no = fila.pop()
        if id(no) in vistos:
            continue
        vistos.add(id(no))
        nome = getattr(no, "name", "<lambda>")
        if nome not in PERMITIDOS:
            txt = ast.get_source_segment(src, no) or ""
            ruins = (chama(no) & POR_USUARIO) | {s for s in SQL_POR_USUARIO if s in txt}
            if "current_user()" in txt:
                ruins.add("current_user()")
            if ruins:
                problemas.append(f"{nome} (linha {no.lineno}): {sorted(ruins)}")
        for c in chama(no):
            if c in funcs and c not in PERMITIDOS:
                fila.append(funcs[c])
    assert not problemas, ("cálculo cacheado (compartilhado entre usuários) depende de quem "
                           "pede — gate/identidade vai no HANDLER, antes do cache: "
                           + "; ".join(problemas))

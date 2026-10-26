# -*- coding: utf-8 -*-
"""Testes da PONTE do tipo_vinculo (ticket 17). Sem banco, sem rede.

A ponte devolve o `PATCH /api/egp-atualizado-pipeline` que morreu com a aba (ticket 11),
mas SÓ para `tipo_vinculo`. O que estes testes protegem é justamente o estreitamento: se
etapa/status/responsável voltarem a passar por aqui, o funil paralelo ressuscita e a
unificação é desfeita pela porta dos fundos — em silêncio, porque a tela "salvaria" e
ninguém veria dois lugares registrando progresso.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backend.egps_atualizados as ega  # noqa: E402

ROTA = "/api/egp-atualizado-pipeline"


class _AppFake:
    def __init__(self):
        self.rotas = {}

    def _reg(self, path, **_kw):
        def deco(fn):
            self.rotas[path] = fn
            return fn
        return deco

    get = patch = post = delete = _reg


class _Http(Exception):
    def __init__(self, code, detail=""):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _rodar(payload, existe=True, atual=None):
    """Registra o módulo com um run_sql que despacha por tabela e chama a rota."""
    sqls = []

    def run_sql(stmt, want_rows=True, **_kw):
        s = " ".join(stmt.split())
        sqls.append(s)
        b = s.lower()
        if b.startswith("select 1 from") and "sas_egp_atualizados " in b + " ":
            return [{"1": 1}] if existe else []
        if "select tipo_vinculo from" in b:
            return [{"tipo_vinculo": atual}] if atual is not None else []
        return []

    app = _AppFake()
    ega.register(app, run_sql, "cat.sch", "true", _Http, lambda *_a, **_k: None)
    fn = app.rotas[ROTA]
    try:
        return fn(payload), sqls, None
    except _Http as e:
        return None, sqls, e


def _escreveu(sqls):
    j = " ".join(sqls).lower()
    return "merge into" in j or "insert into" in j


# ---- o estreitamento: os campos do funil morto ----------------------------------------

def test_recusa_etapa_e_nao_escreve():
    _, sqls, e = _rodar({"egp_key": "A__x", "etapa": "Migrado"})
    assert e and e.code == 400 and "aposentado" in e.detail
    assert not _escreveu(sqls)


def test_recusa_status_responsavel_e_responsavel_bv():
    for campo in ("status", "responsavel", "responsavel_bv"):
        _, sqls, e = _rodar({"egp_key": "A__x", campo: "qualquer"})
        assert e and e.code == 400, campo
        assert campo in e.detail, campo
        assert not _escreveu(sqls), campo


def test_recusa_lista_todos_os_campos_mortos_de_uma_vez():
    _, _, e = _rodar({"egp_key": "A__x", "etapa": "M", "status": "S", "tipo_vinculo": "atualizacao"})
    assert e and e.code == 400
    assert "etapa" in e.detail and "status" in e.detail


# ---- o caminho que a ponte existe para manter vivo -------------------------------------

def test_grava_tipo_vinculo_com_auditoria_antes_do_merge():
    """Ordem invertida de propósito (herdada do endpoint original): com o MERGE primeiro,
    uma auditoria que falhasse deixava a mudança gravada e sem histórico."""
    r, sqls, e = _rodar({"egp_key": "A__x", "tipo_vinculo": "atualizacao"}, atual=None)
    assert e is None and r["ok"] and r["tipo_vinculo"] == "atualizacao"
    ins = next(i for i, s in enumerate(sqls) if s.lower().startswith("insert into"))
    mrg = next(i for i, s in enumerate(sqls) if s.lower().startswith("merge into"))
    assert ins < mrg, "auditoria tem de vir ANTES da escrita"


def test_merge_toca_somente_tipo_vinculo():
    """O UPDATE SET não pode varrer etapa/status: elas seguem vivas na tabela e são o
    estado que a aba deixou para trás."""
    _, sqls, _ = _rodar({"egp_key": "A__x", "tipo_vinculo": "substituicao"}, atual="atualizacao")
    mrg = next(s for s in sqls if s.lower().startswith("merge into"))
    # alvo do SET sem o "t." (o Postgres não aceita coluna-alvo qualificada; o Spark aceita as duas)
    set_clause = mrg.split("UPDATE SET", 1)[1].split("WHEN NOT MATCHED", 1)[0]
    assert re.findall(r"(\w+) = ", set_clause) == ["tipo_vinculo", "updated_by", "updated_at"]
    assert "tipo_vinculo = s.tipo_vinculo" in set_clause


def test_sem_mudanca_nao_audita_mas_ainda_grava():
    _, sqls, _ = _rodar({"egp_key": "A__x", "tipo_vinculo": "atualizacao"}, atual="atualizacao")
    assert not any(s.lower().startswith("insert into") for s in sqls)
    assert any(s.lower().startswith("merge into") for s in sqls)


def test_limpar_o_tipo_grava_null():
    r, sqls, e = _rodar({"egp_key": "A__x", "tipo_vinculo": ""}, atual="atualizacao")
    assert e is None and r["tipo_vinculo"] is None
    mrg = next(s for s in sqls if s.lower().startswith("merge into"))
    assert "CAST(NULL AS STRING)" in mrg


# ---- guardas ---------------------------------------------------------------------------

def test_recusa_tipo_invalido():
    _, sqls, e = _rodar({"egp_key": "A__x", "tipo_vinculo": "inventado"})
    assert e and e.code == 400 and "tipo_vinculo deve ser" in e.detail
    assert not _escreveu(sqls)


def test_recusa_egp_key_vazio():
    _, sqls, e = _rodar({"tipo_vinculo": "atualizacao"})
    assert e and e.code == 400
    assert not _escreveu(sqls)


def test_recusa_chave_que_nao_existe_na_aba():
    """Não criar funil para chave arbitrária."""
    _, sqls, e = _rodar({"egp_key": "A__fantasma", "tipo_vinculo": "atualizacao"}, existe=False)
    assert e and e.code == 404
    assert not _escreveu(sqls)


def test_payload_sem_tipo_vinculo_e_400():
    _, sqls, e = _rodar({"egp_key": "A__x"})
    assert e and e.code == 400 and "tipo_vinculo" in e.detail
    assert not _escreveu(sqls)

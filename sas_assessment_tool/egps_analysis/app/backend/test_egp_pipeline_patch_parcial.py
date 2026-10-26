# -*- coding: utf-8 -*-
"""PATCH /api/egp-pipeline grava SÓ o que foi enviado.

O front manda um campo por PATCH (etapa, depois status, depois responsável...). O
handler lia a linha, montava TODAS as colunas com o valor lido e regravava tudo no MERGE:
dois PATCHes concorrentes no mesmo EGP — trocar a etapa e logo em seguida o status — liam
o mesmo `old`, e o segundo MERGE devolvia a etapa antiga por cima da nova (lost update;
a auditoria registrava a mudança que se perdeu). run_sql stubado, sem rede."""
import os
import re
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m

LINHA = {"et": "Conversão do Código", "st": "Em Andamento", "resp": "a@x", "resp_bv": None,
         "jira": None, "pw": "false", "pw_data": None, "atu_key": None,
         "vinc_tipo": None, "sucessor": None, "mes": None}


def _patch_e_merge(payload):
    sql = []

    def fake(stmt, want_rows=True):
        sql.append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_egp_pipeline" in s:
            return [dict(LINHA)]
        return []

    patches = [patch.object(m, "run_sql", side_effect=fake),
               patch.object(m, "_require_gestao", lambda: None),
               patch.object(m, "_ensure_pipe_table", lambda: True)]
    for p in patches:
        p.start()
    try:
        r = TestClient(m.app).patch("/api/egp-pipeline", json=payload)
        assert r.status_code == 200, r.text
    finally:
        for p in patches:
            p.stop()
    merge = next(s for s in sql if s.lstrip().upper().startswith("MERGE INTO"))
    return " ".join(merge.split())


def _set_do_matched(merge):
    return re.search(r"WHEN MATCHED THEN UPDATE SET (.*?) WHEN NOT MATCHED", merge).group(1)


def test_patch_so_de_responsavel_nao_regrava_etapa_nem_status():
    s = _set_do_matched(_patch_e_merge({"projeto": "Area__X", "funil": "migracao",
                                        "responsavel": "b@x"}))
    # alvo do SET sem o "t." (o Postgres não aceita coluna-alvo qualificada; o Spark aceita as duas)
    assert "responsavel = 'b@x'" in s
    assert "etapa_migracao" not in s
    assert "status_migracao" not in s
    assert "egp_sucessor" not in s


def test_patch_de_etapa_grava_a_etapa():
    s = _set_do_matched(_patch_e_merge({"projeto": "Area__X", "funil": "migracao",
                                        "etapa": "Validação em DES"}))
    assert "etapa_migracao = 'Validação em DES'" in s
    assert not re.search(r"\bresponsavel\b", s)


def test_linha_nova_continua_inserindo_todas_as_colunas():
    merge = _patch_e_merge({"projeto": "Area__X", "funil": "migracao", "status": "Block"})
    ins = merge.split("WHEN NOT MATCHED THEN INSERT", 1)[1]
    for col in ("etapa_migracao", "status_migracao", "responsavel", "egp_sucessor"):
        assert col in ins

# -*- coding: utf-8 -*-
"""O log diário de contadores grava UMA vez por dia por processo.

Ele roda dentro de um GET (/api/inputs/fragilidade) a cada miss de cache; a linha do dia
é a primeira foto e o MERGE nunca a reescreve, então repetir era CREATE + MERGE (~2-4 s)
pagos à toa no caminho de leitura. run_sql stubado, sem rede."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m


def test_segunda_chamada_no_mesmo_dia_nao_escreve():
    sqls = []
    with patch.object(m, "run_sql", side_effect=lambda s, want_rows=True: sqls.append(s) or []), \
            patch.object(m, "_SAN_LOG_ON", True), patch.object(m, "_san_log_dia", None):
        m._log_san_contadores({}, 0)
        n = len(sqls)
        m._log_san_contadores({}, 0)
    assert n == 2                      # CREATE + MERGE na primeira
    assert len(sqls) == n              # nada na segunda


def test_falha_na_escrita_deixa_tentar_de_novo():
    def falha(s, want_rows=True):
        raise m.HTTPException(502, "Falha SQL: timeout")
    with patch.object(m, "run_sql", side_effect=falha), \
            patch.object(m, "_SAN_LOG_ON", True), patch.object(m, "_san_log_dia", None):
        try:
            m._log_san_contadores({}, 0)
        except m.HTTPException:
            pass
        assert m._san_log_dia is None

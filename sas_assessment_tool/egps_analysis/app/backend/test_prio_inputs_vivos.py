#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coluna "+Inputs" da aba Priorização com contagem VIVA por família.

O plano fica congelado (quais EGPs em qual mês, na ordem salva), mas os números de input
são recalculados a cada request. Até 18/09/2026 só o par modernizados/total do mês era
vivo: a coluna por EGP continuava com o valor gravado no snapshot de 14/09, contado por
SAFRA. Num EGP que lê 47 cargas da mesma tabela, a coluna dizia 47 onde há 1 ingestão.

Regra do marginal, igual à do plano: input compartilhado conta uma vez, no primeiro EGP
que o traz, seguindo a ordem congelada do mês. Só pendentes entram (é "+Inputs a ingerir").
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402

FAM = "familia::tabela::GRIMALDI.CARGA_MASSIFICADOS"
T1, T2 = "tabela::OUTRA_A", "tabela::OUTRA_B"


def _meses():
    return [{"mes": 1, "egps": [{"projeto": "Cob__A"}, {"projeto": "Cob__B"}]},
            {"mes": 2, "egps": [{"projeto": "Cob__C"}]}]


def _rodar(pares):
    """pares: [(projeto, chave_familia, resolvido)] como o SELECT devolve."""
    def fake_run_sql(sql, want_rows=True, **kw):
        if "sas_egp_inputs" in sql.lower() or "left join" in sql.lower():
            return [{"projeto": p, "chave": ch, "fam": ch, "ok": str(ok).lower()}
                    for p, ch, ok in pares]
        return []
    ps = [patch.object(m, "run_sql", side_effect=fake_run_sql),
          patch.object(m, "FAMILIAS_ON", True),
          patch.object(m, "_ensure_link_tables", lambda: True),
          patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
    for p in ps:
        p.start()
    try:
        meses = _meses()
        tot = m._prio_live_input_stats(meses)
        return meses, tot
    finally:
        for p in ps:
            p.stop()


def test_familia_conta_uma_vez_na_coluna_do_egp():
    # Cob__A lê 3 cargas da mesma família (chegam colapsadas como 1 chave) + 1 tabela solta
    meses, _tot = _rodar([("Cob__A", FAM, False), ("Cob__A", T1, False)])
    a = meses[0]["egps"][0]
    assert a["n_inputs_novos_vivo"] == 2, "família + tabela solta = 2 unidades pendentes"


def test_input_compartilhado_conta_no_primeiro_egp_do_mes():
    meses, _tot = _rodar([("Cob__A", FAM, False), ("Cob__B", FAM, False)])
    a, b = meses[0]["egps"]
    assert a["n_inputs_novos_vivo"] == 1
    assert b["n_inputs_novos_vivo"] == 0, "o 2º consumidor não repete a mesma ingestão"


def test_dedupe_atravessa_os_meses():
    meses, _tot = _rodar([("Cob__A", FAM, False), ("Cob__C", FAM, False)])
    assert meses[0]["egps"][0]["n_inputs_novos_vivo"] == 1
    assert meses[1]["egps"][0]["n_inputs_novos_vivo"] == 0


def test_resolvido_nao_conta_como_pendente():
    meses, _tot = _rodar([("Cob__A", FAM, True), ("Cob__A", T1, False)])
    assert meses[0]["egps"][0]["n_inputs_novos_vivo"] == 1


def test_ex_dependencia_fica_zerada():
    def _com_ex():
        meses = [{"mes": 1, "egps": [{"projeto": "Cob__A", "ex_dependencia": True},
                                     {"projeto": "Cob__B"}]}]
        def fake_run_sql(sql, want_rows=True, **kw):
            return [{"projeto": "Cob__B", "chave": T2, "fam": T2, "ok": "false"}]
        ps = [patch.object(m, "run_sql", side_effect=fake_run_sql),
              patch.object(m, "FAMILIAS_ON", True),
              patch.object(m, "_ensure_link_tables", lambda: True),
              patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: None)]
        for p in ps:
            p.start()
        try:
            m._prio_live_input_stats(meses)
            return meses
        finally:
            for p in ps:
                p.stop()
    meses = _com_ex()
    assert meses[0]["egps"][0]["n_inputs_novos_vivo"] == 0
    assert meses[0]["egps"][1]["n_inputs_novos_vivo"] == 1


def test_totais_do_mes_seguem_iguais():
    meses, tot = _rodar([("Cob__A", FAM, True), ("Cob__A", T1, False), ("Cob__C", T2, False)])
    assert meses[0]["n_inputs_total"] == 2 and meses[0]["n_inputs_modernizados"] == 1
    assert tot == (1, 3)

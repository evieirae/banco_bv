# -*- coding: utf-8 -*-
"""O funil de ingestão por mês só dá mês ao input pelos consumidores VIVOS.

O plano é podado pela linha de base, não pelo frontier: uma ex-dependência que saiu do
recorte continua com mês no plano. Contando-a, o funil puxava para M1 inputs que nenhum
EGP vivo de M1 lê, e discordava da aba Inputs — que monta o mês a partir de
`/api/inputs-egps`, só com pares do frontier.

Medido em 09/10/2026: 22 x 20 em M1/A Receber. Os 2 de diferença eram lidos pelo
`Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` (ex-dependência, M1 no plano, fora do
frontier) e caem em M4 e M5 pelos consumidores vivos. Decisão da gestão: vale o 1º mês
entre os consumidores vivos.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m

FRONTIER = {"Cob__Vivo_M3", "Cob__Vivo_M4"}
PLANO = {"Cob__Vivo_M3": 3, "Cob__Vivo_M4": 4, "Cob__Saiu_M1": 1}
# i1: lido por quem saiu (M1) e por um vivo de M3   -> M3 (era M1)
# i2: lido só por quem saiu                          -> sem mês (era M1)
# i3: lido só por um vivo de M4                      -> M4 (não muda)
PARES = [("Cob__Saiu_M1", "tabela::I1"), ("Cob__Vivo_M3", "tabela::I1"),
         ("Cob__Saiu_M1", "tabela::I2"),
         ("Cob__Vivo_M4", "tabela::I3")]
LINHAS = [{"chave_canonica": k, "etapa": "A Receber", "status": None,
           "modernizada_auto": "A ingerir", "membros": [k]}
          for k in ("tabela::I1", "tabela::I2", "tabela::I3")]


def _funil():
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split())
        # o crosstab pede os pares só dos EGPs que receberam mês: devolver apenas os
        # pares cujo projeto aparece no IN é o que mede o filtro
        return [{"projeto": p, "chave": k} for p, k in PARES if f"'{p}'" in s]
    with patch.object(m, "FAMILIAS_ON", True), \
         patch.object(m, "_ensure_link_tables"), \
         patch.object(m, "_ensure_input_pipeline_cols"), \
         patch.object(m, "_frontier_egps", return_value=(set(FRONTIER), set())), \
         patch.object(m, "_sanitizacao_derivada", return_value={}), \
         patch.object(m, "_dataset_escopo", return_value=[dict(x) for x in LINHAS]), \
         patch.object(m, "_universo_contagem", side_effect=lambda rows: rows), \
         patch.object(m, "_mes_do_plano", return_value=dict(PLANO)), \
         patch.object(m, "_contaveis", side_effect=lambda egps: egps), \
         patch.object(m, "run_sql", side_effect=fake_run_sql):
        return m.funil_ingestao_mes()


def test_ex_dependencia_fora_do_frontier_nao_da_mes():
    por_mes = {x["mes"]: x["total"] for x in _funil()["meses"]}
    assert 1 not in por_mes, "quem saiu do recorte não pode puxar input para M1"


def test_input_cai_no_mes_do_consumidor_vivo():
    out = _funil()
    por_mes = {x["mes"]: x["total"] for x in out["meses"]}
    assert por_mes == {3: 1, 4: 1}          # I1 -> M3, I3 -> M4


def test_input_so_de_quem_saiu_vai_para_sem_mes():
    assert _funil()["sem_mes"]["total"] == 1  # I2


def test_total_nao_muda_so_o_mes():
    """A regra move inputs entre meses; não tira nem põe ninguém no funil."""
    assert _funil()["total"] == 3

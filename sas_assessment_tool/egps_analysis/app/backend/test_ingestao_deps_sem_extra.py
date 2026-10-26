# -*- coding: utf-8 -*-
"""Os funis de INGESTÃO não contam o inventário exclusivo dos extras.

Os dois são pares de funis de migração que já contam sem extra: `migracao` conta os 168 da
classe base, `migracao_deps` os 193 da linha de base. Enquanto os de ingestão contavam o
universo inteiro, o mesmo input aparecia DUAS vezes no mesmo Resumo: neles e no funil de
ingestão dos extras logo abaixo. Medido em prod 05/10/2026 — coorte +deps 703 onde o funil
por mês, que já aplicava a régua, dizia 630; e escopo 1.166 onde a Visão geral dizia 1.161.

A propriedade travada é a PARTIÇÃO: `ingestao_deps` + `ingestao_extras` = o universo
inteiro, sem sobra e sem repetição. É isso que faz os dois funis poderem ser lidos na
mesma tela sem se contradizerem.

run_sql e dataset stubados — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m
from backend.test_funil_extras import LB, NODES, PIPE_BASE, ESCOPO_BASE, _fake_db


def _input(chave, etapa, status, so_de_extra=False):
    return {"chave_canonica": chave, "artifact": chave, "categoria": "tabela",
            "origem": "SAS/Local (externo)", "etapa": etapa, "status": status,
            "modernizada_auto": "Disponível" if etapa == "Modernizado" else "A ingerir",
            "so_de_extra": so_de_extra}


# 3 do recorte contável + 2 que SÓ os extras leem.
DATASET = [
    _input("tabela::COMUM_PENDENTE", "A Receber", "A Iniciar"),
    _input("tabela::COMUM_PRONTA", "Modernizado", "Concluído"),
    _input("tabela::COMUM_ANDANDO", "Recebido", "Em Andamento"),
    _input("tabela::SO_EXTRA_PENDENTE", "A Receber", "A Iniciar", so_de_extra=True),
    _input("tabela::SO_EXTRA_PRONTA", "Modernizado", "Concluído", so_de_extra=True),
]


def _funis(dataset):
    m._lineage_cache.clear()
    patches = [
        patch.object(m, "run_sql", side_effect=_fake_db(PIPE_BASE, ESCOPO_BASE, NODES)),
        patch.object(m, "_linha_base", lambda: dict(LB)),
        patch.object(m, "FAMILIAS_ON", True),
        patch.object(m, "_dataset_escopo", lambda *a, **k: [dict(r) for r in dataset]),
        patch.object(m, "_ensure_escopo_ativo", lambda *a, **k: None),
        patch.object(m, "_ensure_link_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        r = TestClient(m.app).get("/api/funis")
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        for p in patches:
            p.stop()


def _kpis(funil):
    return {s["label"]: s["value"] for s in funil["top_stats"]}


def test_ingestao_deps_ignora_o_que_so_os_extras_leem():
    f = _funis(DATASET)
    k = _kpis(f["ingestao_deps"])
    assert k["A Receber"] == 1 and k["Modernizado"] == 1   # os 2 so_de_extra ficaram fora
    assert f["ingestao_deps"]["total"] == 3


def test_os_dois_funis_particionam_o_universo():
    """Sem sobra e sem repetição: é o que permite ler os dois na mesma tela."""
    f = _funis(DATASET)
    deps, extras = _kpis(f["ingestao_deps"]), _kpis(f["ingestao_extras"])
    for label in ("A Receber", "Em Processamento", "Modernizado", "Sanitizado"):
        assert deps[label] + extras[label] == _kpis(_funis(
            [dict(r, so_de_extra=False) for r in DATASET])["ingestao_deps"])[label], label


def test_o_funil_dos_extras_continua_vendo_so_o_exclusivo_deles():
    f = _funis(DATASET)
    k = _kpis(f["ingestao_extras"])
    assert k["A Receber"] == 1 and k["Modernizado"] == 1
    assert f["ingestao_extras"]["total"] == 2


def test_sem_nenhum_exclusivo_de_extra_nada_muda():
    """Guarda contra a correção ter virado um filtro que come linha legítima."""
    sem = [dict(r, so_de_extra=False) for r in DATASET]
    f = _funis(sem)
    assert f["ingestao_deps"]["total"] == 5
    assert f["ingestao_extras"]["total"] == 0


def test_funil_de_escopo_aplica_a_mesma_regua():
    """`ingestao` (só Indicium) é o par de `migracao`, que conta os 168 da classe base SEM
    extra — vale a mesma exclusão. Em prod isso era 1.166 contra as 1.161 do item 3 da
    Visão geral; as 5 de diferença eram exclusivas de extra, todas resolvidas (por isso só
    o universo divergia, nunca o "a ingerir")."""
    f = _funis(DATASET)
    assert f["ingestao"]["total"] == 3
    k = _kpis(f["ingestao"])
    assert k["A Receber"] == 1 and k["Modernizado"] == 1

# -*- coding: utf-8 -*-
"""Cards da aba EGPs: as unidades de input por EGP (`/api/egp-input-units`).

O que estes testes seguram é UMA propriedade: contar as unidades de TODOS os EGPs dá
exatamente o universo que a Visão geral conta — o mesmo dataset, a mesma unidade, a mesma
régua de pendência. Era a divergência que motivou o endpoint (711 × 1.303 em prod,
05/10/2026): o header de /api/egp-readiness agrega por SQL e tira o Sanitizado do
universo, então os cards da aba e o Resumo falavam de conjuntos diferentes.

A segunda propriedade é a que o usuário vê: restringir os EGPs restringe o conjunto, e
nada mais — o ESTADO de cada unidade é o do recorte inteiro, nunca reagregado por filtro.

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m
from backend.input_state import py_aingerir

# Dataset do recorte, no shape que `_dataset_escopo` entrega: uma FAMÍLIA (2 safras),
# um input solto pendente de origem externa, um resolvido, e dois que `_universo_contagem`
# tem de descartar (vínculo todo quebrado / exclusivo de ex-dependência).
DATASET = [
    {"chave_canonica": "familia::tabela::GH16.POLITICA", "artifact": "GH16.POLITICA",
     "categoria": "tabela", "origem": "SAS/Local (externo)", "is_familia": True,
     "membros": ["tabela::GH16.POLITICA_202506", "tabela::GH16.POLITICA_202507"],
     "etapa": "A Receber", "status": "A Iniciar", "modernizada_auto": "A ingerir"},
    {"chave_canonica": "tabela::SOLTO.PENDENTE", "artifact": "SOLTO.PENDENTE",
     "categoria": "tabela", "origem": "Arquivo", "etapa": "Recebido",
     "status": "Em Andamento", "modernizada_auto": "A ingerir"},
    {"chave_canonica": "tabela::JA.MODERNIZADA", "artifact": "JA.MODERNIZADA",
     "categoria": "tabela", "origem": "BigQuery", "etapa": "Modernizado",
     "status": "Concluído", "modernizada_auto": "Disponível"},
    {"chave_canonica": "tabela::TODO.QUEBRADO", "artifact": "TODO.QUEBRADO",
     "categoria": "tabela", "origem": "SAS/Local (externo)", "etapa": "A Receber",
     "status": "A Iniciar", "modernizada_auto": "A ingerir", "vinculo_ativo": False},
    {"chave_canonica": "tabela::SO.DE.EXDEP", "artifact": "SO.DE.EXDEP",
     "categoria": "tabela", "origem": "SAS/Local (externo)", "etapa": "A Receber",
     "status": "A Iniciar", "modernizada_auto": "A ingerir", "ex_dependencia": True},
]

# (EGP, chave FÍSICA, vínculo quebrado?) — o grão em que sas_egp_inputs vive.
PARES = [
    ("A", "tabela::GH16.POLITICA_202506", False),   # A e B leem safras DIFERENTES
    ("B", "tabela::GH16.POLITICA_202507", False),   # da MESMA família -> 1 unidade
    ("A", "tabela::SOLTO.PENDENTE", False),
    ("B", "tabela::JA.MODERNIZADA", False),
    ("C", "tabela::SOLTO.PENDENTE", True),          # vínculo quebrado: C não conta
    ("C", "tabela::TODO.QUEBRADO", False),          # unidade fora do universo
    ("D", "tabela::SO.DE.EXDEP", False),            # idem
]


def _fake_run_sql(stmt, want_rows=True):
    s = " ".join(stmt.split()).lower()
    if "sas_egp_inputs" in s:
        return [{"projeto": p, "chave_canonica": k, "broken": b} for p, k, b in PARES]
    return []


def _payload(ds="indi_deps"):
    with patch.object(m, "run_sql", side_effect=_fake_run_sql), \
         patch.object(m, "_dataset_escopo", lambda *a, **k: [dict(r) for r in DATASET]), \
         patch.object(m, "_ensure_link_tables", lambda *a, **k: True):
        return m._egp_input_units_uncached(ds)


def _conta(pay, egps):
    """Mesma conta que o frontend faz: união dos índices, dedup por unidade."""
    sel = set()
    for p in egps:
        sel.update(pay["por_egp"].get(p, []))
    us = [pay["unidades"][i] for i in sel]
    return {"dist": len(us), "faltam": sum(1 for u in us if u["a"]),
            "sem_fonte": sum(1 for u in us if u["sf"])}


def test_universo_e_o_mesmo_da_visao_geral():
    """Somar TODOS os EGPs reproduz o universo contado pela Visão geral, unidade a unidade.

    É a propriedade que o endpoint existe para garantir; se ela cair, o card volta a
    discordar do Resumo com nenhum filtro ligado — o defeito original."""
    pay = _payload()
    universo = m._universo_contagem([dict(r) for r in DATASET])
    assert len(pay["unidades"]) == len(universo) == 3
    assert {u["k"] for u in pay["unidades"]} == {r["chave_canonica"] for r in universo}
    todos = _conta(pay, pay["por_egp"].keys())
    assert todos["dist"] == len(universo)
    assert todos["faltam"] == sum(1 for r in universo if py_aingerir(r))


def test_familia_e_uma_unidade_mesmo_lida_por_safras_diferentes():
    """A e B leem safras distintas da mesma família: juntos, UMA unidade, não duas."""
    pay = _payload()
    assert _conta(pay, ["A"])["dist"] == 2          # família + SOLTO.PENDENTE
    assert _conta(pay, ["B"])["dist"] == 2          # família + JA.MODERNIZADA
    assert _conta(pay, ["A", "B"])["dist"] == 3     # e não 4


def test_filtrar_egps_estreita_o_conjunto_sem_mudar_o_estado():
    """O filtro escolhe o que contar; o estado da unidade é o do recorte inteiro."""
    pay = _payload()
    assert _conta(pay, ["A"]) == {"dist": 2, "faltam": 2, "sem_fonte": 1}
    assert _conta(pay, ["B"]) == {"dist": 2, "faltam": 1, "sem_fonte": 1}
    assert _conta(pay, []) == {"dist": 0, "faltam": 0, "sem_fonte": 0}


def test_vinculo_quebrado_nao_entra_no_mapa():
    """C lê SOLTO.PENDENTE com o vínculo quebrado — mesma exclusão do universo do Resumo."""
    pay = _payload()
    assert "tabela::SOLTO.PENDENTE" not in [
        pay["unidades"][i]["k"] for i in pay["por_egp"].get("C", [])]
    assert _conta(pay, ["C"])["dist"] == 0


def test_unidade_fora_do_universo_nao_aparece_por_nenhum_egp():
    """Vínculo todo quebrado e exclusivo de ex-dependência saem do universo (decisões 4/5);
    um EGP que as lê não pode reintroduzi-las pela porta do mapa."""
    pay = _payload()
    chaves = {u["k"] for u in pay["unidades"]}
    assert "tabela::TODO.QUEBRADO" not in chaves
    assert "tabela::SO.DE.EXDEP" not in chaves
    assert _conta(pay, ["D"])["dist"] == 0


def test_sem_fonte_e_so_o_externo_ainda_pendente():
    """Mesma régua do `n_sem_fonte` do header: origem externa E ainda pendente."""
    pay = _payload()
    por_k = {u["k"]: u for u in pay["unidades"]}
    assert por_k["familia::tabela::GH16.POLITICA"]["sf"] is True
    assert por_k["tabela::SOLTO.PENDENTE"]["sf"] is False      # pendente, origem Arquivo
    assert por_k["tabela::JA.MODERNIZADA"]["a"] is False
    assert por_k["tabela::JA.MODERNIZADA"]["sf"] is False


def test_grao_declarado_acompanha_a_flag():
    with patch.object(m, "FAMILIAS_ON", True):
        assert _payload()["grao"] == "familia"
    with patch.object(m, "FAMILIAS_ON", False):
        assert _payload()["grao"] == "safra"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-check da regra de atribuição de área do input (funil por área do Resumo).
Roda com pytest OU direto: `python test_area_principal.py`. Regra: ver escolhe_area_principal.
Cobre também o frontier que lastreia a votação no publish (frontier_egps)."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from publish_to_databricks import escolhe_area_principal as pick  # noqa: E402
from publish_to_databricks import frontier_egps  # noqa: E402

C = collections.Counter


def _e(alvo, dep, vias):
    return {"projeto_alvo": alvo, "depende_do": dep, "via_tabelas": " | ".join(vias)}


def test_sem_egp_vira_sem_area():
    # nenhuma área com EGP associado (ex.: os 18 inputs do Jurídico, 0 EGPs)
    assert pick(C()) == "(sem área)"


def test_cobranca_ganha_mesmo_com_menos_egps():
    # 1º critério: Cobrança presente vence, ignorando contagem
    assert pick(C({"Riscos": 5, "Cobrança": 1})) == "Cobrança"


def test_maior_contagem_quando_sem_cobranca():
    # 2º critério: sem Cobrança, a área com mais EGPs
    assert pick(C({"Riscos": 3, "Finanças": 1})) == "Riscos"


def test_empate_desempata_alfabetica():
    # 3º critério: empate na contagem -> ordem alfabética (Finanças < Riscos)
    assert pick(C({"Riscos": 2, "Finanças": 2})) == "Finanças"


def test_exemplo_X_cobranca_e_riscos():
    # input X: Cobrança e Riscos, ambos com EGP -> Cobrança
    assert pick(C({"Cobrança": 1, "Riscos": 1})) == "Cobrança"


def test_exemplo_Y_sem_cobranca_riscos_e_financas():
    # input Y: Cobrança 0 EGPs; Riscos e Finanças com EGP (empate) -> Finanças
    assert pick(C({"Riscos": 1, "Finanças": 1})) == "Finanças"


def test_frontier_puxa_dependencia_transitiva():
    # A (escopo) -> B -> C: os três entram no frontier, então o input só de C tem área.
    edges = [_e("A", "B", ["T1"]), _e("B", "C", ["T2"])]
    assert frontier_egps(edges, {"A"}, set(), set()) == {"A", "B", "C"}


def test_frontier_ignora_via_resolvida():
    # via já modernizada/sanitizada não puxa a dependência (espelha o backend)
    edges = [_e("A", "B", ["T1"]), _e("B", "C", ["T2"])]
    assert frontier_egps(edges, {"A"}, set(), {"T1"}) == {"A"}
    # aresta com ≥1 via viva continua puxando
    assert frontier_egps([_e("A", "B", ["T1", "T9"])], {"A"}, set(), {"T1"}) == {"A", "B"}


def test_frontier_despriorizado_entra_mas_nao_expande():
    # no_expand: B entra no frontier (esforço já contabilizado) mas não arrasta C
    edges = [_e("A", "B", ["T1"]), _e("B", "C", ["T2"])]
    assert frontier_egps(edges, {"A"}, {"B"}, set()) == {"A", "B"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")

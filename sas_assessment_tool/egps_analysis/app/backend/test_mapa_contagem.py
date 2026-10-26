# -*- coding: utf-8 -*-
"""Antecessor espelhado conta como migrado quando o FIM da cadeia migrou.

`Desatualizado` ocupa o campo de STATUS mas é um rótulo de RELAÇÃO, não uma posição de
trabalho. Quem contava terminais por status perdia o antecessor cujo sucessor já migrou:
ele aparecia DENTRO da coluna "Migrado" do gráfico (a etapa já espelha) e fora do "X/Y"
logo acima dela — 95/193 onde a coluna dizia 96 (prod, 05/10/2026).

Lógica pura: sem DB, sem FastAPI.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import vinculos as V

MIGR = "Migrado"
DESP = V.STATUS_DESPRIORIZADO
DESA = V.STATUS_DESATUALIZADO


def _v(tipo, sucessor):
    return {"tipo": tipo, "sucessor": sucessor}


def test_antecessor_herda_o_terminal_do_sucessor():
    pipe = {"A": ("Aprv. PR", "Em Andamento"), "B": ("Migrado", MIGR)}
    c = V.mapa_contagem(pipe, {"A": _v("Atualizado", "B")})
    assert c["A"] == MIGR
    # a EXIBIÇÃO não muda: a tela continua dizendo que A está Desatualizado
    assert V.mapa_exibido(pipe, {"A": _v("Atualizado", "B")})["A"] == ("Migrado", DESA)


def test_sucessor_ainda_em_andamento_nao_promove_o_antecessor():
    """O antecessor herda o estado do sucessor, não um terminal de graça."""
    pipe = {"A": ("Aprv. PR", "Em Andamento"), "B": ("Conversão do Código", "Em Andamento")}
    assert V.mapa_contagem(pipe, {"A": _v("Atualizado", "B")})["A"] == "Em Andamento"


def test_cadeia_vai_ate_o_fim():
    """v1 -> v2 -> v3: o v1 conta pelo v3, não pelo v2 (que também espelha)."""
    pipe = {"v1": ("x", "Em Andamento"), "v2": (None, None), "v3": ("Migrado", MIGR)}
    vincs = {"v1": _v("Atualizado", "v2"), "v2": _v("Unificado", "v3")}
    c = V.mapa_contagem(pipe, vincs)
    assert c["v1"] == MIGR and c["v2"] == MIGR


def test_substituido_nao_herda():
    """Trajetórias independentes: herdar o terminal contaria o mesmo trabalho duas vezes."""
    pipe = {"A": ("Pré-conversão", "Em Andamento"), "B": ("Migrado", MIGR)}
    assert V.mapa_contagem(pipe, {"A": _v("Substituído", "B")})["A"] == "Em Andamento"


def test_despriorizado_do_proprio_antecessor_vence():
    """Decisão de gestão não é apagada por fato derivado (mesma regra de status_exibido)."""
    pipe = {"A": ("Migrado", DESP), "B": ("Migrado", MIGR)}
    assert V.mapa_contagem(pipe, {"A": _v("Atualizado", "B")})["A"] == DESP


def test_sucessor_fora_do_recorte_vira_none_e_nao_terminal():
    """Sem a linha do sucessor, a resposta honesta é "não sei" — nunca um Migrado chutado."""
    pipe = {"A": ("Aprv. PR", "Em Andamento")}
    assert V.mapa_contagem(pipe, {"A": _v("Atualizado", "FORA")})["A"] is None


def test_sem_vinculo_e_identico_ao_status_real():
    pipe = {"A": ("x", "Em Andamento"), "B": ("Migrado", MIGR), "C": ("y", None)}
    assert V.mapa_contagem(pipe, {}) == {"A": "Em Andamento", "B": MIGR, "C": None}


def test_ciclo_nao_trava():
    pipe = {"A": ("x", "Em Andamento"), "B": ("y", "Block")}
    c = V.mapa_contagem(pipe, {"A": _v("Atualizado", "B"), "B": _v("Atualizado", "A")})
    assert set(c) == {"A", "B"}


def test_anexa_vinculo_serve_o_campo_por_linha():
    """A tabela por sub-área lê `status_contagem` da linha; `status` segue exibindo a relação."""
    linhas = [{"projeto": "A", "etapa": "Aprv. PR", "status": "Em Andamento"},
              {"projeto": "B", "etapa": "Migrado", "status": MIGR}]
    V.anexa_vinculo(linhas, {"A": _v("Atualizado", "B")}, linha_base=["A", "B"])
    a = next(r for r in linhas if r["projeto"] == "A")
    assert a["status"] == DESA           # o que a tela mostra
    assert a["status_contagem"] == MIGR  # o que a contagem usa
    assert a["etapa_real"] == "Aprv. PR"


def test_anexa_vinculo_linha_sem_vinculo_tem_os_dois_campos_iguais():
    linhas = [{"projeto": "X", "etapa": "Migrado", "status": MIGR}]
    V.anexa_vinculo(linhas, {}, linha_base=["X"])
    assert linhas[0]["status_contagem"] == linhas[0]["status"] == MIGR

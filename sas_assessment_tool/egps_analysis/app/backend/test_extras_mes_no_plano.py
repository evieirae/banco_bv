# -*- coding: utf-8 -*-
"""`/api/priorizacao` expõe o mês dos Extras — sem deixá-los entrar na contagem do plano.

O front monta o mapa `projeto -> mês` (`useMesPlan`) SÓ com `meses[].egps[]`, que são os
193 do plano congelado. Extra não está lá, então toda tela que usa o hook (11 em 08/10/2026)
dava mês "—" para Extra e o derrubava em qualquer filtro de mês — junto com os inputs que
só Extra lê (66 medidos naquele dia). O backend já sabia a resposta desde 30/09
(`_mes_dos_extras`: o mês do Antecessor), ela só nunca chegava ao cliente.

O que estes testes travam:
  - `extras` vem preenchido, com o mês do Antecessor, nos TRÊS caminhos de retorno;
  - `meses[].egps[]` NÃO ganha os extras (senão o denominador do plano deixaria de ser 193);
  - grafo não publicado vira lista vazia, e QUALQUER outra falha sobe — a mesma régua de
    `_objeto_ausente` que o PR #169 teve de consertar noutro ponto.

run_sql nunca é chamado: tudo stubado.
"""
import os
import sys
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m

PLANO = {"meses": [{"mes": 1, "egps": [{"projeto": "Cob__Velho"}]},
                   {"mes": 4, "egps": [{"projeto": "Cob__Outro"}]}]}
EXTRAS = {"Cob__Novo_v2": 1, "Cob__Outro_v3": 4}


def _chama(snapshot=PLANO, extras=EXTRAS, erro=None):
    def fake_extras():
        if erro is not None:
            raise erro
        return dict(extras)
    with patch.object(m, "_read_prio_snapshot", return_value=snapshot), \
         patch.object(m, "_poda_fora_da_linha_base", side_effect=lambda p: p), \
         patch.object(m, "_mes_dos_extras", side_effect=fake_extras):
        return m.priorizacao()


def test_extras_vem_no_payload_com_o_mes_do_antecessor():
    assert _chama()["extras"] == [{"projeto": "Cob__Novo_v2", "mes": 1},
                                  {"projeto": "Cob__Outro_v3", "mes": 4}]


def test_plano_nao_ganha_os_extras():
    """O denominador do plano é dos 193; Extra ganha mês, não vaga no plano."""
    out = _chama()
    nomes = [e["projeto"] for mm in out["meses"] for e in mm["egps"]]
    assert nomes == ["Cob__Velho", "Cob__Outro"]


def test_sem_extras_campo_vazio_e_presente():
    """Campo sempre existe: o front não precisa de guarda para plano antigo."""
    assert _chama(extras={})["extras"] == []


def test_grafo_nao_publicado_nao_derruba_o_plano():
    erro = HTTPException(500, "[TABLE_OR_VIEW_NOT_FOUND] sas_lineage_edges")
    out = _chama(erro=erro)
    assert out["extras"] == []
    assert len(out["meses"]) == 2


def test_falha_que_nao_e_objeto_ausente_sobe():
    """Timeout virando lista vazia esconderia o mês de TODO extra por 5 min de cache."""
    with pytest.raises(HTTPException):
        _chama(erro=HTTPException(500, "Timed out after 0:05:00"))


def test_caminho_sem_snapshot_tambem_traz_extras():
    """Auto-seed: o plano é computado e gravado, e o campo tem de vir junto."""
    with patch.object(m, "_read_prio_snapshot", side_effect=[None, PLANO]), \
         patch.object(m, "_compute_priorizacao", return_value=PLANO), \
         patch.object(m, "_write_prio_snapshot", return_value=None), \
         patch.object(m, "_poda_fora_da_linha_base", side_effect=lambda p: p), \
         patch.object(m, "_mes_dos_extras", return_value=dict(EXTRAS)):
        assert m.priorizacao()["extras"] == [{"projeto": "Cob__Novo_v2", "mes": 1},
                                             {"projeto": "Cob__Outro_v3", "mes": 4}]


def test_caminho_de_auto_seed_falho_tambem_traz_extras():
    """Snapshot não gravou (sem privilégio): segue ao vivo, mas com os extras."""
    with patch.object(m, "_read_prio_snapshot", return_value=None), \
         patch.object(m, "_compute_priorizacao", return_value=dict(PLANO)), \
         patch.object(m, "_write_prio_snapshot", side_effect=RuntimeError("sem SP")), \
         patch.object(m, "_mes_dos_extras", return_value=dict(EXTRAS)):
        out = m.priorizacao()
        assert out["snapshot"] is None
        assert [e["projeto"] for e in out["extras"]] == ["Cob__Novo_v2", "Cob__Outro_v3"]

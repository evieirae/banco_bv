# -*- coding: utf-8 -*-
"""Guarda do ensaio: o plan só pode criar ou não mudar nada; destruir ou substituir para tudo."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from treino import confere_plano  # noqa: E402


def _plano(*acoes):
    return {"resource_changes": [{"address": f"aws_x.r{i}", "change": {"actions": a}}
                                 for i, a in enumerate(acoes)]}


def test_criar_e_nao_mudar_passam():
    assert confere_plano.destrutivos(_plano(["create"], ["no-op"], ["update"])) == []


def test_destruir_e_substituir_sao_apontados():
    p = _plano(["create"], ["delete"], ["delete", "create"], ["create", "delete"])
    assert confere_plano.destrutivos(p) == ["aws_x.r1", "aws_x.r2", "aws_x.r3"]


def test_plano_sem_mudanca_nenhuma_passa():
    assert confere_plano.destrutivos({}) == []


def test_main_sai_com_erro_e_nomeia_o_recurso(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_plano(["delete"]))))
    with pytest.raises(SystemExit) as e:
        confere_plano.main()
    assert "aws_x.r0" in str(e.value)


# Derrubada (treino/desce_treino.sh): o plan só pode destruir; criar, mudar ou substituir para.
def test_derrubada_so_com_delete_passa():
    assert confere_plano.fora_da_derrubada(_plano(["delete"], ["delete"])) == []


def test_derrubada_aponta_o_que_nao_e_so_destruir():
    p = _plano(["delete"], ["create"], ["update"], ["delete", "create"], ["no-op"])
    assert confere_plano.fora_da_derrubada(p) == ["aws_x.r1", "aws_x.r2", "aws_x.r3", "aws_x.r4"]


def test_main_derruba_recusa_plano_que_cria(monkeypatch):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_plano(["delete"], ["create"]))))
    monkeypatch.setattr(sys, "argv", ["confere_plano", "--derruba"])
    with pytest.raises(SystemExit) as e:
        confere_plano.main()
    assert "aws_x.r1" in str(e.value)


def test_main_derruba_recusa_plano_vazio(monkeypatch):
    # nada a destruir = estado (sufixo) errado; derrubar "nada" esconderia o ensaio que ficou de pé
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({})))
    monkeypatch.setattr(sys, "argv", ["confere_plano", "--derruba"])
    with pytest.raises(SystemExit) as e:
        confere_plano.main()
    assert "nada" in str(e.value)


def test_main_derruba_conta_os_recursos(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_plano(["delete"], ["delete"]))))
    monkeypatch.setattr(sys, "argv", ["confere_plano", "--derruba"])
    confere_plano.main()
    assert "2 recursos" in capsys.readouterr().out

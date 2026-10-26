# -*- coding: utf-8 -*-
import argparse
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paridade import tabelas  # noqa: E402


def test_igual_mesmo_fora_de_ordem():
    r = tabelas.diferenca([("a", "1"), ("b", "2")], [("b", "2"), ("a", "1")], ("x", "y"))
    assert r["so_no_databricks"] == r["so_no_postgres"] == 0


def test_conta_repetidas_e_aponta_a_coluna_sem_mostrar_valor():
    r = tabelas.diferenca([("a", "1"), ("a", "1")], [("a", "1"), ("a", "2")], ("x", "y"))
    assert (r["so_no_databricks"], r["so_no_postgres"]) == (1, 1)
    assert r["colunas_que_diferem"] == ["y"]
    assert "1" not in repr(r["colunas_que_diferem"])


# Depois do roteiro de escritas (paridade.escritas): os dois lados carimbaram em instantes
# diferentes e sortearam ids diferentes — o valor some, a CLASSE do valor tem de bater.
def test_mascara_carimbo_e_id_gerado_mas_nao_o_resto():
    cols = ("id", "updated_by", "updated_at", "ts", "data")
    spark = ("3f2a9c0e8b7d4a1f9e6c5b4a3d2c1b0a", "a@x", "2026-10-15 19:27:07.090031",
             "2026-10-15T19:27:07.090Z", "2026-10-15")
    pg = ("9b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e", "a@x", "2026-10-15 19:28:01.5",
          "2026-10-15T19:28:01.500Z", "2026-10-15")
    assert tabelas.mascara(cols, spark) == tabelas.mascara(cols, pg) == \
        ("<id>", "a@x", "<instante>", "<instante T>", "2026-10-15")


def test_mascara_id_so_na_coluna_id():
    cols = ("id", "arquivo_hash")
    h = "3f2a9c0e8b7d4a1f9e6c5b4a3d2c1b0a"
    assert tabelas.mascara(cols, (h, h)) == ("<id>", h)


def test_mascara_formatos_de_instante_tem_classe_propria():
    cols = ("a", "b")
    assert tabelas.mascara(cols, ("2026-10-15 19:27:07", "2026-10-15T19:27:07Z")) == \
        ("<instante>", "<instante T>")


DESDE = "2026-10-15 19:00:00"


def test_desde_instante_antigo_compara_pelo_valor():
    cols = ("updated_at",)
    a = [tabelas.mascara(cols, ("2026-10-01 10:00:00.1",), DESDE)]
    b = [tabelas.mascara(cols, ("2026-10-15 19:27:07.5",), DESDE)]   # carimbou onde não devia
    assert tabelas.diferenca(a, b, cols)["so_no_databricks"] == 1
    # coluna timestamp (T...Z) no MESMO dia do desde, mas antes dele: também compara pelo valor
    assert tabelas.mascara(cols, ("2026-10-15T18:00:00.000Z",), "2026-10-15 19:25:00") == \
        ("2026-10-15T18:00:00.000Z",)


def test_desde_sem_escritas_e_recusado(monkeypatch):
    # isolado: se o guarda regredir, o import do SDK falha em vez de comparar contra o Databricks
    monkeypatch.setitem(sys.modules, "databricks.sdk", None)
    with pytest.raises(SystemExit) as e:
        tabelas.main(["--desde", "2026-10-15 19:25:00"])
    assert e.value.code == 2


def test_mascara_tamanhos_diferentes_falha_alto():
    with pytest.raises(ValueError):
        tabelas.mascara(("a", "b"), ("x",))


def test_desde_valido_normaliza_e_recusa_formato_fora_do_padrao():
    assert tabelas.desde_valido("2026-10-15 19:25") == "2026-10-15 19:25:00"
    assert tabelas.desde_valido("2026-10-15T19:25:30.5Z") == "2026-10-15 19:25:30"
    for ruim in ("15/10/2026 19:25", "10/15/2026 19:25:00", "2026-10-15", "2026-10-15 19:25+00"):
        with pytest.raises(argparse.ArgumentTypeError):
            tabelas.desde_valido(ruim)


def test_desde_instante_novo_continua_mascarado():
    cols = ("updated_at", "ts")
    a = tabelas.mascara(cols, ("2026-10-15 19:27:07.09", "2026-10-15T19:27:07.090Z"), DESDE)
    b = tabelas.mascara(cols, ("2026-10-15 19:40:00", "2026-10-15T19:40:00.5Z"), DESDE)
    assert a == b == ("<instante>", "<instante T>")


def test_sem_desde_todo_instante_vira_classe():
    cols = ("updated_at",)
    assert tabelas.mascara(cols, ("2026-10-01 10:00:00",)) == ("<instante>",)


def test_mascara_instante_gravado_em_coluna_de_valor():
    # o audit do snapshot da priorização grava a HORA em valor_novo (pego na prova de 15/10)
    cols = ("campo", "valor_novo")
    assert tabelas.mascara(cols, ("priorizacao_snapshot", "2026-10-15 20:46:39.015625")) == \
        ("priorizacao_snapshot", "<instante>")


def test_mascara_nao_esconde_carimbo_em_outro_formato_nem_nulo():
    cols = ("updated_at", "created_at")
    assert tabelas.mascara(cols, ("2026-10-15 19:27:07.090031+00", None)) == \
        ("2026-10-15 19:27:07.090031+00", None)        # '+00' no texto não é o formato do Spark

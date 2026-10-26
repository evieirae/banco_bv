# -*- coding: utf-8 -*-
"""PATCH /api/inputs × sanitização DERIVADA.

1. A resposta carrega as MESMAS derivações de leitura que o dataset. `aplica_em_linhas`
   sobrescreve `status` por 'Sanitizado' e (desde 14/10/2026) `etapa` por 'Modernizado' na
   LEITURA (§3.4.18): o banco guarda o real, a tela mostra o derivado. O front faz merge da
   resposta na linha em cache, então uma resposta crua fazia o estado "pular ao salvar e
   voltar no refetch" (medido em prod 09/10/2026, família TALITA.NOTIFICACAO_SOLAR).

2. Etapa e status de input sanitizado por derivação são TRAVADOS (14/10/2026). Gravar a
   etapa Modernizado tirava o input da derivação — ela só vale para chave pendente — e ele
   passava a contar como modernizado com o status cru 'A Iniciar' do publish: 37 inputs
   lidos só pelo antecessor de um vínculo estavam assim em prod. Destravar não precisa de
   ninguém: o input volta à fila sozinho quando o vínculo é desfeito ou o consumidor é
   repriorizado. Responsável e observação seguem editáveis.

Para a FAMÍLIA o overlay roda ANTES da reagregação, na mesma ordem de `_dataset_escopo`, e
a escrita de etapa/status pula as safras derivadas (as demais são trabalho de verdade).

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m
from backend import sanitizacao

CRUA = {"chave_canonica": "tabela::T.X", "artifact": "T.X", "categoria": "tabela",
        "origem": "SAS/Local", "source_types": "", "qtd_projetos": 1, "areas": "Cobrança",
        "escopo_indi": "true", "modernizada_auto": "A ingerir", "etapa": "A Receber",
        "status": "A Iniciar", "responsavel": None, "observacao": None, "orfao": False,
        "paths_fisicos": "", "n_paths_fisicos": 0}
DERIVADOS = {"tabela::T.X": "so_despriorizados"}


def _run_sql(linhas, escritas):
    def _run(stmt, want_rows=True):
        if stmt.lstrip().upper().startswith("SELECT"):
            return [dict(x) for x in linhas]
        escritas.append(stmt)
        return []
    return _run


def _patch(derivados=DERIVADOS, **campos):
    escritas = []
    with patch.object(m, "_ensure_input_pipeline_cols"), \
         patch.object(m, "_sanitizacao_derivada", return_value=dict(derivados)), \
         patch.object(m, "run_sql", side_effect=_run_sql([CRUA], escritas)):
        out = m.patch_input(m.Patch(chave_canonica="tabela::T.X", **campos))
    return out, escritas


# ---- 1. a resposta carrega o overlay ----------------------------------------------

def test_resposta_mantem_o_derivado_ao_editar_o_responsavel():
    out, _ = _patch(responsavel="fulano@indicium.ai")
    assert out["status"] == sanitizacao.STATUS_SANITIZADO
    assert out["etapa"] == "Modernizado"


def test_resposta_expoe_o_real_e_o_motivo():
    """O front precisa distinguir derivado de gravado (é o que o drawer mostra)."""
    out, _ = _patch(observacao="ok")
    assert out["status_real"] == "A Iniciar"
    assert out["etapa_real"] == "A Receber"
    assert out["sanitizado_derivado"] == "so_despriorizados"


def test_input_sem_derivacao_nao_ganha_campo_nenhum():
    """Ausência é o sinal de 'não se aplica' — não inventar Sanitizado para todo mundo."""
    out, escritas = _patch(derivados={}, etapa="Recebido")
    assert out["status"] == "A Iniciar" and out["etapa"] == "Recebido"
    assert "sanitizado_derivado" not in out and "etapa_real" not in out
    assert any(e.lstrip().upper().startswith("UPDATE") for e in escritas)


# ---- 2. trava de etapa/status -------------------------------------------------------

@pytest.mark.parametrize("campo,valor", [("etapa", "Modernizado"), ("status", "Concluído"),
                                         ("etapa", "Recebido"), ("status", "Sanitizado")])
def test_safra_derivada_recusa_etapa_e_status(campo, valor):
    with pytest.raises(HTTPException) as e:
        _patch(**{campo: valor})
    assert e.value.status_code == 409
    assert "automaticamente" in e.value.detail


def test_recusa_nao_escreve_nada():
    escritas = []
    with patch.object(m, "_ensure_input_pipeline_cols"), \
         patch.object(m, "_sanitizacao_derivada", return_value=dict(DERIVADOS)), \
         patch.object(m, "run_sql", side_effect=_run_sql([CRUA], escritas)):
        with pytest.raises(HTTPException):
            m.patch_input(m.Patch(chave_canonica="tabela::T.X", etapa="Modernizado"))
    assert escritas == []


def _patch_familia(derivados, **campos):
    safras = [dict(CRUA, chave_canonica=f"tabela::T.X_{a}", artifact=f"T.X_{a}")
              for a in ("2024", "2025")]
    corpus = {"membros": {("tabela", "T.X"): ["T.X_2024", "T.X_2025"]},
              "chave": {("tabela", "T.X_2024"): "T.X", ("tabela", "T.X_2025"): "T.X"}}
    escritas = []
    with patch.object(m, "_ensure_input_pipeline_cols"), \
         patch.object(m, "FAMILIAS_ON", True), \
         patch.object(m, "_familias_corpus", return_value=corpus), \
         patch.object(m, "_familia_egp_counts", return_value={}), \
         patch.object(m, "_sanitizacao_derivada", return_value=dict(derivados)), \
         patch.object(m, "run_sql", side_effect=_run_sql(safras, escritas)):
        linha = m.patch_input(m.Patch(chave_canonica=m.FAMILIA_PREFIX + "tabela::T.X", **campos))
    return linha, escritas


TODAS = {"tabela::T.X_2024": "so_antecessor", "tabela::T.X_2025": "so_antecessor"}


def test_familia_toda_derivada_recusa_etapa():
    with pytest.raises(HTTPException) as e:
        _patch_familia(TODAS, etapa="Modernizado")
    assert e.value.status_code == 409


def test_familia_toda_derivada_aceita_responsavel_e_agrega_o_derivado():
    linha, escritas = _patch_familia(TODAS, responsavel="fulano@indicium.ai")
    assert linha["status"] == sanitizacao.STATUS_SANITIZADO
    assert linha["etapa"] == "Modernizado"
    assert linha["n_safras_pendentes"] == 0      # sanitizado não é pendente
    upd = [e for e in escritas if e.lstrip().upper().startswith("UPDATE")]
    assert len(upd) == 1 and "T.X_2024" in upd[0] and "T.X_2025" in upd[0]


def test_familia_parcial_escreve_etapa_so_na_safra_viva():
    """A safra derivada não é trabalho; a viva é. A escrita vai só para a viva."""
    linha, escritas = _patch_familia({"tabela::T.X_2024": "so_antecessor"}, etapa="Recebido")
    upd = [e for e in escritas if e.lstrip().upper().startswith("UPDATE")]
    assert len(upd) == 1 and "T.X_2025" in upd[0] and "T.X_2024" not in upd[0]
    aud = [e for e in escritas if "sas_inputs_audit" in e]
    assert aud and "T.X_2025" in aud[0] and "T.X_2024" not in aud[0]
    assert linha["etapa"] == "Recebido"          # a família fala pela safra pendente
    assert linha["fan_out"]["alteracoes"] == 1

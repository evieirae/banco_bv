# -*- coding: utf-8 -*-
"""Quem conta no denominador de EGPs é a LISTA CONGELADA, em toda superfície.

O critério "189" (`_ex_deps_contab`: ex-dependência só conta com etapa REAL) foi ABSORVIDO
pela foto em 29/09/2026, quando o `total_egps` deixou de ser calculado e passou a ser o
tamanho da lista. Ele sobreviveu em superfícies que ninguém reviu, e cada sobra apareceu
como um número a menos numa tela:

- Gestão/Acompanhamento: 31 EGPs `Desatualizado` contra 33 da aba EGPs (07/10/2026);
- tabela/funil por área: 192 contra os 193 da Visão geral, na MESMA tela (08/10/2026).

Os dois casos eram ex-dependências com etapa FANTASMA (`Pré-conversão`) presentes na foto.

Lógica pura + stub de `_linha_base` — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m

# NA_FOTO_EX  entrou na foto já como ex              -> conta
# NA_FOTO_DEP entrou como `dependencia` e virou ex   -> conta (caso Performance_Saldo_COLORE)
# FORA_FOTO   nunca esteve na foto                   -> não conta
EX = {"Cob__NA_FOTO_EX", "Cob__NA_FOTO_DEP", "Cob__FORA_FOTO"}
FOTO = {"Cob__A": "base", "Cob__NA_FOTO_EX": "ex_dependencia", "Cob__NA_FOTO_DEP": "dependencia"}


def _na_foto():
    with patch.object(m, "_ex_deps", lambda *a, **k: (set(EX), {}, {})), \
         patch.object(m, "_linha_base", lambda: dict(FOTO)):
        return m._ex_deps_na_foto({"Cob__A"}, {"Cob__A"})


def test_conta_quem_esta_na_foto_qualquer_que_seja_a_classe():
    assert _na_foto() == {"Cob__NA_FOTO_EX", "Cob__NA_FOTO_DEP"}


def test_a_pergunta_e_estar_na_lista_nao_ser_classificado_ex_nela():
    """`NA_FOTO_DEP` entrou como `dependencia`; filtrar por classe o deixaria de fora."""
    assert "Cob__NA_FOTO_DEP" in _na_foto()


def test_quem_nunca_esteve_na_foto_fica_fora():
    assert "Cob__FORA_FOTO" not in _na_foto()


def test_difere_do_criterio_189_quando_a_etapa_e_fantasma():
    """A regressão exata das duas telas: etapa fantasma + presente na foto."""
    fantasma = sorted(m.PHANTOM_ETAPAS_MIGRACAO)[0]
    etapas = {"Cob__NA_FOTO_EX": fantasma, "Cob__NA_FOTO_DEP": fantasma}
    m._lineage_cache.clear()
    with patch.object(m, "_ex_deps", lambda *a, **k: (set(EX), {}, {})), \
         patch.object(m, "_linha_base", lambda: dict(FOTO)), \
         patch.object(m, "run_sql", side_effect=lambda *a, **k: [
             {"projeto": p, "etapa_migracao": e, "status_migracao": "A Iniciar"}
             for p, e in etapas.items()]):
        contab = m._ex_deps_contab({"Cob__A"}, {"Cob__A"})
    m._lineage_cache.clear()
    assert contab == set(), "critério 189 descarta etapa fantasma"
    assert _na_foto() == {"Cob__NA_FOTO_EX", "Cob__NA_FOTO_DEP"}, "a foto mantém"


# ---------------------------------------------------------------- Priorização

def _linha(projeto, ex, etapa=None, status=None):
    return {"projeto": projeto, "ex_dependencia": ex, "etapa": etapa, "status": status}


def test_prio_conta_ex_da_foto_mesmo_com_etapa_fantasma():
    fantasma = sorted(m.PHANTOM_ETAPAS_MIGRACAO)[0]
    e = _linha("Cob__NA_FOTO_EX", True, fantasma)
    assert m._prio_contabiliza(e, None, set(FOTO)) is True
    # sem a foto, cai no critério 189 (comportamento anterior, preservado p/ quem não passa)
    assert m._prio_contabiliza(e, None) is False


def test_prio_nao_conta_ex_fora_da_foto():
    e = _linha("Cob__FORA_FOTO", True, "Conversão do Código")
    assert m._prio_contabiliza(e, None, set(FOTO)) is False


def test_prio_conta_quem_nao_e_ex_independente_da_foto():
    """Só a ex-dependência passa pela régua; o resto do plano conta como sempre contou."""
    assert m._prio_contabiliza(_linha("Cob__QUALQUER", False), None, set(FOTO)) is True


# ---------------------------------------------------- guard de uso (não só da regra)
# Os testes acima travam a RÉGUA (`_ex_deps_na_foto`), mas não que as superfícies a USEM:
# reverter uma chamada para `_ex_deps_contab` passava por eles. Este guard fecha isso.
# Fonte, e não comportamento, porque exercitar `/api/resumo` e `/api/gestao/rows` exigiria
# reconstruir meio warehouse em stub — e o que se quer provar aqui é uma linha.

import re

ALVO = os.path.join(os.path.dirname(__file__), "main.py")
# (função, nº esperado de chamadas a `_ex_deps_na_foto` dentro dela). O `resumo` saiu
# daqui em 14/10/2026: passou a ler dependências E ex-dependências direto da classe
# gravada na foto — guard próprio logo abaixo.
SUPERFICIES = {"_gestao_rows_uncached": 1}


def _corpo(fonte, nome):
    """O corpo de uma função top-level, até a próxima definição no nível zero."""
    i = fonte.index(f"\ndef {nome}(")
    resto = fonte[i + 1:]
    m = re.search(r"\n(?:@app\.|def )", resto)
    return resto[:m.start()] if m else resto


def test_superficies_de_denominador_usam_a_regua_da_foto():
    with open(ALVO, encoding="utf-8") as fh:
        fonte = fh.read()
    for nome, n in SUPERFICIES.items():
        corpo = _corpo(fonte, nome)
        assert corpo.count("_ex_deps_na_foto(") == n, (
            f"{nome} deveria chamar _ex_deps_na_foto {n}x — se a régua mudou, mude aqui junto")
        assert "_ex_deps_contab(" not in corpo, (
            f"{nome} voltou ao critério 189; o denominador é a foto (ver _ex_deps_na_foto)")


def test_funil_por_area_conta_egps_pela_classe_da_foto():
    """Funil por área (+deps): dependências e ex pela classe GRAVADA, não pelo grafo vivo
    (que perdia a dependência da foto fora do recorte — 192 × 193 em 08/10 e 14/10/2026)."""
    with open(ALVO, encoding="utf-8") as fh:
        corpo = _corpo(fh.read(), "resumo")
    assert "linha_base.por_classe(" in corpo
    assert "_ex_deps_contab(" not in corpo
    assert "_contaveis(frontier) - base" not in corpo

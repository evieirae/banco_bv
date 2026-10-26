# -*- coding: utf-8 -*-
"""A etapa espelhada resolve mesmo com o sucessor FORA do recorte carregado.

O espelho era resolvido só entre as linhas do payload. No recorte "só Indicium" as cascas
aparecem (nascem com `escopo_indi=true`, regra 27) mas o unificador delas não (é sucessor,
`escopo_indi=false`): 27 linhas saíam com `etapa=None` e a tabela mostrava "— etapa —",
enquanto o drawer — que carrega o recorte `base` — mostrava `Pré-conversão` (08/10/2026).

O que o `.get` sem default protegia continua protegido: o fallback nunca é a etapa do
PRÓPRIO antecessor (exibir a velha como se fosse a nova), só a do sucessor lida de outro
lugar. Sucessor inexistente segue virando `None`.

Lógica pura — sem DB, sem FastAPI.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import vinculos as V


def _casca(projeto, etapa_propria=""):
    return {"projeto": projeto, "etapa": etapa_propria, "status": "A Iniciar"}


VINC = {"Cob__CASCA": {"tipo": "Unificado", "sucessor": "Cob__UNIFICADOR"}}
LB = ["Cob__CASCA"]


def test_sucessor_fora_do_recorte_resolve_pela_tabela_inteira():
    linhas = [_casca("Cob__CASCA")]                       # unificador NÃO está nas linhas
    V.anexa_vinculo(linhas, VINC, linha_base=LB,
                    etapa_de={"Cob__UNIFICADOR": "Pré-conversão"})
    assert linhas[0]["etapa"] == "Pré-conversão"
    assert linhas[0]["etapa_real"] == "", "a etapa GRAVADA do antecessor não muda"


def test_sem_a_tabela_inteira_continua_None():
    """Comportamento anterior, preservado para quem chamar sem `etapa_de`."""
    linhas = [_casca("Cob__CASCA")]
    V.anexa_vinculo(linhas, VINC, linha_base=LB)
    assert linhas[0]["etapa"] is None


def test_nunca_cai_na_etapa_velha_do_proprio_antecessor():
    """O risco que o `.get` sem default evitava: o antecessor tem etapa própria gravada e
    o sucessor não existe em lugar nenhum — tem de virar None, nunca a dele."""
    linhas = [_casca("Cob__CASCA", etapa_propria="Conversão do Código")]
    V.anexa_vinculo(linhas, VINC, linha_base=LB, etapa_de={"Cob__OUTRO": "Migrado"})
    assert linhas[0]["etapa"] is None
    assert linhas[0]["etapa_real"] == "Conversão do Código"


def test_linha_carregada_vence_a_tabela_inteira():
    """Mesma fonte nos dois casos (T_PIPE); se divergirem, manda o payload do recorte."""
    linhas = [_casca("Cob__CASCA"),
              {"projeto": "Cob__UNIFICADOR", "etapa": "Validação em DES", "status": "Em Andamento"}]
    V.anexa_vinculo(linhas, VINC, linha_base=LB,
                    etapa_de={"Cob__UNIFICADOR": "Pré-conversão"})
    assert linhas[0]["etapa"] == "Validação em DES"


def test_cadeia_longa_resolve_pelo_fim_mesmo_fora_do_recorte():
    """v1 -> v2 -> v3 com v2 e v3 fora das linhas: vale a etapa do v3 (fim_do_espelho)."""
    vinc = {"Cob__V1": {"tipo": "Atualizado", "sucessor": "Cob__V2"},
            "Cob__V2": {"tipo": "Unificado", "sucessor": "Cob__V3"}}
    linhas = [_casca("Cob__V1")]
    V.anexa_vinculo(linhas, vinc, linha_base=["Cob__V1"],
                    etapa_de={"Cob__V2": "", "Cob__V3": "Migrado"})
    assert linhas[0]["etapa"] == "Migrado"


def test_quem_nao_tem_vinculo_nao_e_tocado():
    linhas = [{"projeto": "Cob__SOZINHO", "etapa": "Projetos Habilitados", "status": "A Iniciar"}]
    V.anexa_vinculo(linhas, {}, linha_base=["Cob__SOZINHO"], etapa_de={"Cob__X": "Migrado"})
    assert linhas[0]["etapa"] == "Projetos Habilitados"

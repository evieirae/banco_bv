#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estado efetivo de um input (etapa, status, resolvido/pendente) em DUAS formas pareadas.

Extraído de `main.py` sem mudança de comportamento: as funções que geram SQL continuam
com os mesmos nomes e assinaturas (o main.py as reimporta), e ao lado de cada uma mora a
gêmea em Python (`py_*`), necessária desde que a contagem por FAMÍLIA DE SAFRAS passou a
ser feita em memória sobre o dataset já carregado (ver docs/adr/0002).

Por que pareadas no mesmo arquivo: a definição de "pendente" é sutil e já foi errada uma
vez nesta esteira — `status='Concluído'` numa etapa intermediária significa "essa etapa
acabou", NÃO "input resolvido". Resolvido = chegou na etapa terminal (Modernizado) OU tem
status terminal (Sanitizado/Autoprodutor). Deixar as duas formas lado a lado é o que torna
a divergência visível na leitura; a divergência em DADO é checada contra o warehouse por
`egps_analysis/scripts/verifica_familias.py`.
"""

def _eff_etapa(et="etapa", auto="modernizada_auto"):
    """SQL da ETAPA efetiva de um input (posição no funil de ingestão). A etapa humana
    prevalece; sem humana, deriva do auto (Disponível→Modernizado, senão→A Receber)."""
    auto_def = f"CASE {auto} WHEN 'Disponível' THEN 'Modernizado' ELSE 'A Receber' END"
    return f"coalesce(nullif({et}, ''), {auto_def})"


def _eff_status_input(st="status", et="etapa", auto="modernizada_auto"):
    """SQL do STATUS efetivo (progresso dentro da etapa). O status humano prevalece; sem
    humano, deriva da etapa efetiva (Modernizado→Concluído; qualquer outra etapa→A
    Iniciar — sem status humano, o padrão é "ainda não começou a trabalhar NESSA etapa",
    não "Em Andamento". Antes o fallback só dava A Iniciar p/ etapa=A Receber e Em
    Andamento p/ todas as demais, o que tornava IMPOSSÍVEL um item chegar numa etapa
    (ex.: Recebido, Pré-Working) sem status humano e aparecer como A Iniciar — sumindo
    do segmento A Iniciar em toda barra do funil de ingestão exceto a 1ª)."""
    ee = _eff_etapa(et, auto)
    auto_def = f"CASE WHEN {ee} = 'Modernizado' THEN 'Concluído' ELSE 'A Iniciar' END"
    return f"coalesce(nullif({st}, ''), {auto_def})"


def _modern(et="etapa", auto="modernizada_auto", st="status", lnk="false"):
    """Modernizado = resolvido (não pendente): chegou na etapa terminal (Modernizado) OU
    status terminal Sanitizado (pulou a esteira, exclui do universo) OU Autoprodutor
    (EGP consumidor também cria a tabela, conta como feito — ver STATUS_INPUT). `lnk`:
    expressão SQL BOOLEAN opcional (default 'false') que faz um par (egp, input) contar
    como resolvido — usado pelo overlay per-(EGP, Input) de vínculo quebrado. Callers que
    fazem LEFT JOIN sas_egp_input_link l ON ... passam lnk='coalesce(l.link_broken, false)'."""
    return (f"(({_eff_etapa(et, auto)} = 'Modernizado' OR "
            f"{_eff_status_input(st, et, auto)} IN ('Sanitizado', 'Autoprodutor')) OR {lnk})")


def _aingerir(et="etapa", auto="modernizada_auto", st="status", lnk="false"):
    """Pendência: tudo que não está modernizado. `lnk`: ver _modern — vínculo quebrado é
    considerado resolvido."""
    return f"(NOT {_modern(et, auto, st, lnk)})"


def _sanitizado(et="etapa", auto="modernizada_auto", st="status", lnk="false"):
    """Sanitizado = status TERMINAL (descartado, não vai ser migrado; input que pulou a
    esteira). Segue no escopo: conta no universo de inputs (Resumo/Inputs). SAI do
    trabalho pendente por subunidade (progresso por EGP, waves) — resolvê-lo não é
    modernização daquela subunidade. Regra: contadores de universo → contam; contadores
    de progresso/subunidade → excluem. `lnk`: expressão SQL BOOLEAN opcional (default
    'false') — vínculo quebrado é tratado como Sanitizado para AQUELE (EGP, Input) apenas
    (overlay per-EGP)."""
    return f"({_eff_status_input(st, et, auto)} = 'Sanitizado' OR {lnk})"


# ---------------------------------------------------------------- gêmeas em Python
# Mesma semântica das funções SQL acima, sobre uma linha já carregada (dict do
# StatementExecution). Usadas pela agregação por família em memória. Qualquer mudança nas
# de cima tem que descer para cá — e o script de verificação compara as duas em dado real.

def py_eff_etapa(row):
    """Etapa efetiva de uma linha de input (espelho de `_eff_etapa`)."""
    et = (row.get("etapa") or "").strip()
    if et:
        return et
    return "Modernizado" if row.get("modernizada_auto") == "Disponível" else "A Receber"


def py_eff_status(row):
    """Status efetivo de uma linha de input (espelho de `_eff_status_input`)."""
    st = (row.get("status") or "").strip()
    if st:
        return st
    return "Concluído" if py_eff_etapa(row) == "Modernizado" else "A Iniciar"


def py_modern(row, link_broken=False):
    """Resolvido/não pendente (espelho de `_modern`). `link_broken` = overlay per-(EGP, input)."""
    return bool(link_broken) or (py_eff_etapa(row) == "Modernizado"
                                 or py_eff_status(row) in ("Sanitizado", "Autoprodutor"))


def py_aingerir(row, link_broken=False):
    """Pendente de ingestão (espelho de `_aingerir`)."""
    return not py_modern(row, link_broken)


def py_sanitizado(row, link_broken=False):
    """Status terminal Sanitizado (espelho de `_sanitizado`)."""
    return bool(link_broken) or py_eff_status(row) == "Sanitizado"

# -*- coding: utf-8 -*-
"""Monta o retrato a partir das linhas lidas do Databricks: aplica o de-para e completa as
âncoras (EGP/input citados por um par mas ausentes da tabela-mãe entram como órfãos)."""
from . import espelho, mapeamento as mp


def monta(linhas):
    """`linhas`: dict tabela Delta -> lista de dicts (texto). Devolve o retrato de carrega():
    o de-para das 5 tabelas do 1a para o schema novo e o espelho fiel do que o app lê."""
    egps = {r["projeto"]: mp.egp(r) for r in linhas["sas_lineage_nodes"]}
    inputs = {r["chave_canonica"]: mp.input_(r) for r in linhas["sas_inputs_monitor"]}
    estados = [e for e in (mp.estado_input(r) for r in linhas["sas_inputs_monitor"]) if e]

    pares, vistos, duplicados = [], set(), 0
    egps_novos, inputs_novos = 0, 0
    for r in linhas["sas_egp_inputs"]:
        k = (r["projeto"], r["chave_canonica"])
        if k in vistos:
            duplicados += 1
            continue
        vistos.add(k)
        if r["projeto"] not in egps:
            egps[r["projeto"]] = mp.egp({"projeto": r["projeto"]}, orfao=True)
            egps_novos += 1
        if r["chave_canonica"] not in inputs:
            inputs[r["chave_canonica"]] = mp.ancora_input_ausente(
                r["chave_canonica"], r["categoria"], r["artifact"])
            inputs_novos += 1
        pares.append(mp.egp_input(r))

    usuarios = [(r["email"].strip().lower(), r.get("nome") or r["email"], mp._txt(r.get("papel")),
                 bool(mp._bool(r.get("organograma"))))
                for r in linhas["sas_analistas"]]
    referenciadas = [e[3] for e in estados if e[3]]
    return {
        "corpus.egp": list(egps.values()),
        "corpus.input": list(inputs.values()),
        "trabalho.estado_input": estados,
        "corpus.egp_input": pares,
        "trabalho.escopo_item": [mp.escopo_item(r) for r in linhas["sas_escopo"]],
        "usuarios": usuarios,
        "pessoas_referenciadas": referenciadas,
        "ancoras_acrescentadas": {"egp": egps_novos, "input": inputs_novos,
                                  "pares_duplicados_descartados": duplicados},
        "espelho": espelho.monta(linhas),
    }

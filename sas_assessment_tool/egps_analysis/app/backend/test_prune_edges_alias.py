#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_prune_edges: a escolha de produtor canônico tem de valer quando a aresta carrega um
ALIAS de libname da mesma tabela.

O problema real (prod, 2026-09-28): a escolha é gravada com a chave que o PRODUTOR
declara em sas_egp_outputs (`NPS.BA_ESTOQUE_NPSENVIO_CARTAO`) e a aresta carrega a via
com o alias que o CONSUMIDOR usa (`NPS_NEW.BA_ESTOQUE_NPSENVIO_CARTAO`). O casamento era
por string crua, então a escolha nunca entrava no `eff` — e o guard de self-heal ainda a
descartava por inteiro. Resultado: as duas cópias do EGP seguiam como produtoras e a
duplicata `__v2` continuava sendo puxada como dependência. 5 das 11 escolhas de prod
estavam inertes assim.

A regra tem de ser CONSERVADORA: colapsa só quando o conjunto de produtores é IDÊNTICO.
Medido em prod: 37 membros aparecem sob mais de um libname; 28 são alias (mesmos
produtores) e 9 são homônimos REAIS (`DIAS_UTEIS` em B_GERAL vs CARNEIRO, `TBPESSOA` em
5 variantes). Casar por membro sozinho fundiria tabelas distintas — o contrário do
invariante de identidade por caminho físico.

Uso: egps_analysis/venv/bin/python test_prune_edges_alias.py
"""
import os
import sys

os.environ.setdefault("PUBLISH_CATALOG", "bv_dev_db")
os.environ.setdefault("PUBLISH_SCHEMA", "monitoramento_sas")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as b  # noqa: E402

PROD_A = "Area__Produtor"
PROD_B = "Area__Produtor__v2"
CONS = "Area__Consumidor"


def aresta(depende_do, via, alvo=CONS):
    return {"projeto_alvo": alvo, "depende_do": depende_do, "via_tabelas": via}


def pares(rows):
    return {(e["projeto_alvo"], e["depende_do"]) for e in rows}


def roda():
    casos = []

    # 1) alias com produtores IDÊNTICOS -> a escolha vale e a duplicata é podada
    rows = [aresta(PROD_A, "NPS_NEW.BA_ESTOQUE"), aresta(PROD_B, "NPS_NEW.BA_ESTOQUE")]
    out = b._prune_edges(rows, {"NPS.BA_ESTOQUE": PROD_A},
                         {"NPS.BA_ESTOQUE": {PROD_A, PROD_B}})
    casos.append(("alias de libname: poda o produtor não escolhido",
                  pares(out) == {(CONS, PROD_A)}))

    # 2) mesmo MEMBRO, produtores DIFERENTES -> homônimo real, não colapsa
    rows = [aresta(PROD_A, "B_GERAL.DIAS_UTEIS"), aresta(PROD_B, "CARNEIRO.DIAS_UTEIS")]
    out = b._prune_edges(rows, {"B_GERAL.DIAS_UTEIS": PROD_A},
                         {"B_GERAL.DIAS_UTEIS": {PROD_A}})
    casos.append(("homônimo (produtores diferentes) NÃO é colapsado",
                  pares(out) == {(CONS, PROD_A), (CONS, PROD_B)}))

    # 3) via EXATA continua podando como antes (regressão da regra de hoje)
    rows = [aresta(PROD_A, "NPS.BA_ESTOQUE"), aresta(PROD_B, "NPS.BA_ESTOQUE")]
    out = b._prune_edges(rows, {"NPS.BA_ESTOQUE": PROD_A}, {"NPS.BA_ESTOQUE": {PROD_A, PROD_B}})
    casos.append(("via exata segue podando", pares(out) == {(CONS, PROD_A)}))

    # 4) sem produtores declarados p/ a chave -> não inventa equivalência
    rows = [aresta(PROD_A, "NPS_NEW.BA_ESTOQUE"), aresta(PROD_B, "NPS_NEW.BA_ESTOQUE")]
    out = b._prune_edges(rows, {"NPS.BA_ESTOQUE": PROD_A}, {})
    casos.append(("chave sem produtores declarados fica inerte",
                  pares(out) == {(CONS, PROD_A), (CONS, PROD_B)}))

    # 5) chave/via com CAMINHO: '.sas7bdat' viraria o "membro" de todo mundo se o split
    #    por ponto valesse — não pode casar por isso.
    rows = [aresta(PROD_A, "/a/x.sas7bdat"), aresta(PROD_B, "/b/y.sas7bdat")]
    out = b._prune_edges(rows, {"/a/x.sas7bdat": PROD_A},
                         {"/a/x.sas7bdat": {PROD_A, PROD_B}})
    casos.append(("caminho não casa por sufixo falso (.sas7bdat)",
                  pares(out) == {(CONS, PROD_A), (CONS, PROD_B)}))

    # 6) sem o mapa de produtores (argumento omitido) -> comportamento de hoje, intacto
    rows = [aresta(PROD_A, "NPS_NEW.BA_ESTOQUE"), aresta(PROD_B, "NPS_NEW.BA_ESTOQUE")]
    casos.append(("compatível: sem o 3º argumento, nada muda",
                  pares(b._prune_edges(rows, {"NPS.BA_ESTOQUE": PROD_A}))
                  == {(CONS, PROD_A), (CONS, PROD_B)}))

    # 7) a aresta que sobra mantém as OUTRAS vias (não pode perder via alheia)
    rows = [aresta(PROD_A, "NPS_NEW.BA_ESTOQUE | OUTRA.TABELA"),
            aresta(PROD_B, "NPS_NEW.BA_ESTOQUE")]
    out = b._prune_edges(rows, {"NPS.BA_ESTOQUE": PROD_A},
                         {"NPS.BA_ESTOQUE": {PROD_A, PROD_B}})
    casos.append(("a via não relacionada sobrevive na aresta mantida",
                  pares(out) == {(CONS, PROD_A)}
                  and out[0]["via_tabelas"] == "NPS_NEW.BA_ESTOQUE | OUTRA.TABELA"))

    falhas = 0
    for nome, ok in casos:
        print(f"[{'PASS' if ok else 'FAIL'}] {nome}")
        if not ok:
            falhas += 1
    print(f"\n{'TODOS PASSARAM' if falhas == 0 else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(roda())

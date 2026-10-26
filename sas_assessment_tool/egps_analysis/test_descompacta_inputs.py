#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão: macros no estilo %DESCOMPACTA(libname, base) copiam fisicamente
lib.base para WORK via `x cp` + `x gunzip`. A referência subsequente é
unqualified (WORK), então o scan de FROM/JOIN nunca a apanha como input e
a linhagem quebra (ex.: Cobranças__Avaliacao_modelos_v3, BASE_ESTUDO_PERFORMANCE_MIX).

Uso: egps_analysis/venv/bin/python test_descompacta_inputs.py
"""
import egps_extractor as e

INPUTS_IDX = 2


def inputs_of(sas):
    return set(e.scan_sas_dependencies(sas)[INPUTS_IDX])


DEF_DESCOMPACTA = """
LIBNAME JOAO '/riscosbv/cobranca/bsilva/';
%macro DESCOMPACTA(libname,base);
%let path = %sysfunc(pathname(&libname.));
%let work = %sysfunc(pathname(work));
x cp &path./&base..sas7* &work.;
x gunzip &work./&base.*;
%mend;
"""

# Nome alternativo do mesmo padrão (existe no corpus real).
DEF_COPIA_DESCOMPACTA = """
LIBNAME RENEG '/riscosbv/cobranca/reneg/';
%macro copia_descompacta(libname, arquivo);
%let path = %sysfunc(pathname(&libname.));
%let work = %sysfunc(pathname(work));
x cp &path./&arquivo..sas7* &work.;
x gunzip &work./&arquivo.*;
%mend;
"""

SQL_UNQUALIFIED = """
PROC SQL;
CREATE TABLE WORK.OUT AS
SELECT DISTINCT A.* FROM BASE_ESTUDO_PERFORMANCE_MIX A;
QUIT;
"""

# Leitura da base copiada sob OUTRO nome de membro (cada caso precisa ler o SEU membro:
# desde 2026-08-24 a cópia só vira input se o membro reaparecer em contexto de leitura).
SQL_LE_TAB_X = """
PROC SQL;
CREATE TABLE WORK.OUT AS SELECT * FROM TAB_X;
QUIT;
"""

# Só manutenção de disco: copia e nunca lê (o programa mexe em outra tabela).
SQL_NAO_LE = """
PROC SQL;
CREATE TABLE WORK.OUT AS SELECT * FROM OUTRA_COISA;
QUIT;
"""

DATASTEP_LE_TAB_X = """
DATA WORK.OUT;
  SET TAB_X;
RUN;
"""

# SET quebrado em continuação de linha (estilo de formatação comum no corpus real):
# a varredura linha-a-linha original nunca via SET e TAB_X na mesma linha física.
DATASTEP_LE_TAB_X_QUEBRA_LINHA = """
DATA WORK.OUT;
  SET
      TAB_X;
RUN;
"""

CASES = [
    (
        "literal: %DESCOMPACTA registra LIB.BASE como input",
        DEF_DESCOMPACTA + "%DESCOMPACTA(JOAO, base_estudo_performance_mix);\n" + SQL_UNQUALIFIED,
        ["JOAO.BASE_ESTUDO_PERFORMANCE_MIX"],
        [],
    ),
    (
        "nome alternativo do mesmo padrão (copia_descompacta)",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, tab_x);\n" + SQL_LE_TAB_X,
        ["RENEG.TAB_X"],
        [],
    ),
    (
        "cópia mecânica NUNCA lida não é input (só manutenção de disco)",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, tab_x);\n" + SQL_NAO_LE,
        [],
        ["RENEG.TAB_X"],
    ),
    (
        "leitura por DATA step SET também conta como uso",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, tab_x);\n" + DATASTEP_LE_TAB_X,
        ["RENEG.TAB_X"],
        [],
    ),
    (
        "leitura por SET quebrado em linha de continuação ainda conta como uso",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, tab_x);\n" + DATASTEP_LE_TAB_X_QUEBRA_LINHA,
        ["RENEG.TAB_X"],
        [],
    ),
    (
        "PROC DATASETS ... MODIFY conta como uso (quem modifica depende da tabela)",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, tab_x);\n"
        + "proc datasets lib=work nolist;\n  modify tab_x;\n  label a='x';\nquit;\n",
        ["RENEG.TAB_X"],
        [],
    ),
    (
        "chamada com argumento nomeado (base=) não conta como leitura de si mesma",
        DEF_COPIA_DESCOMPACTA + "%copia_descompacta(RENEG, base=tab_x);\n" + SQL_NAO_LE,
        [],
        ["RENEG.TAB_X", "RENEG.BASE=TAB_X"],
    ),
    (
        "dinâmico: base=&tabela. mantém LIB.&TABELA para o resolvedor de %LET",
        DEF_DESCOMPACTA + "%DESCOMPACTA(JOAO, &tabela.);\n" + SQL_UNQUALIFIED,
        ["JOAO.&TABELA"],
        [],
    ),
    (
        "dinâmico: %LET resolve para input estático",
        "%let tabela = base_final_2026;\n" + DEF_DESCOMPACTA +
        "%DESCOMPACTA(JOAO, &tabela.);\n" + SQL_UNQUALIFIED,
        ["JOAO.BASE_FINAL_2026"],
        ["JOAO.&TABELA"],
    ),
    (
        "guard: %macro de 2 args SEM `x cp`+`x gunzip` não é tratado como copy",
        "%macro OUTRO(a, b); %put &a &b; %mend;\n%OUTRO(FOO, bar);\n" + SQL_UNQUALIFIED,
        [],
        ["FOO.BAR"],
    ),
]


def run():
    fails = 0
    for name, sas, must, must_not in CASES:
        ins = inputs_of(sas)
        missing = [t for t in must if t not in ins]
        bad = [t for t in must_not if t in ins]
        ok = not missing and not bad
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if missing:
            print(f"        faltando: {missing}")
        if bad:
            print(f"        FALSO-POSITIVO: {bad}")
        if not ok:
            fails += 1
            print(f"        obtido: {sorted(ins)}")
    print(f"\n{'TODOS PASSARAM' if fails == 0 else f'{fails} FALHA(S)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(run())

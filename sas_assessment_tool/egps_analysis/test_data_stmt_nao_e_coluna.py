#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão: coluna `alias.Data` não é o statement `DATA <tabelas>;`.

`\\bDATA\\s+([^;]+);` casa `t2.Data` (o `\\b` existe entre `.` e `D`) e lê tudo até o próximo
`;` como lista de tabelas de saída. Num `ON t1.X = t2.Data GROUP BY t1.ANOMES_PROC, t2.Du;`
as colunas do GROUP BY viravam outputs permanentes (`T1.ANOMES_PROC`, `T2.DU`) — caso real
do Cobranças__Acompanhamento_Desconto - Painel_vK__ATU20260901 e de mais 18 EGPs (50 outputs
fantasmas, todos de lib `T1`/`T2`).

Offline: só o scan e leitura do fonte, nenhuma conexão.
"""
import pathlib
import re

import egps_extractor as e

OUTPUTS_IDX = 3  # scan_sas_dependencies -> (..., outputs no índice 3, ...)


def outputs_of(sql):
    return set(e.scan_sas_dependencies(sql)[OUTPUTS_IDX])


# Estrutura do Acompanhamento_Desconto - Painel_vK__ATU20260901 (task 02, CONSULTA_RECEB_PROD).
SQL_GROUP_BY_APOS_DATA = """
PROC SQL;
   CREATE TABLE WORK.CONSULTA_RECEB_PROD AS
   SELECT t1.ANOMES_PROC, t1.SISTEMA, (SUM(t1.VRPARCELA)) AS SUM_of_VRPARCELA, t2.Du
   FROM WORK.CONSULTA_RECEB_SOLAR_2 t1
   LEFT JOIN B_GERAL.DIAS_UTEIS t2
   ON t1.DTPROCESSAMENTO = t2.Data
   GROUP BY t1.ANOMES_PROC,
            t1.SISTEMA,
            t2.Du;
QUIT;
"""

# Estrutura do Cobranças__CARTA_RODAS_2026 (WHERE ... BETWEEN ... ORDER BY).
SQL_ORDER_BY_APOS_DATA = """
PROC SQL;
   CREATE TABLE DIAS_UTEIS AS
   SELECT DISTINCT Data, Safra
      FROM B_GERAL.DIAS_UTEIS t1
      WHERE t1.Data BETWEEN '01DEC2023'D AND "&dia_anterior2."D
      ORDER BY t1.Safra;
QUIT;
"""


def test_group_by_depois_de_alias_data_nao_vira_output():
    outs = outputs_of(SQL_GROUP_BY_APOS_DATA)
    assert not {"T1.ANOMES_PROC", "T1.SISTEMA", "T2.DU"} & outs, sorted(outs)
    assert "WORK.CONSULTA_RECEB_PROD" in outs


def test_order_by_depois_de_alias_data_nao_vira_output():
    outs = outputs_of(SQL_ORDER_BY_APOS_DATA)
    assert "T1.SAFRA" not in outs, sorted(outs)


def test_statement_data_de_verdade_continua_capturado():
    sql = ("data perm.a perm.b (keep=x); set t2.data; run;"
           "proc sort data=perm.a;by x;run;DATA PERM.C;set perm.a;run;")
    assert {"PERM.A", "PERM.B", "PERM.C"} <= outputs_of(sql)


def test_toda_regex_de_statement_data_ignora_alias_ponto():
    """As cópias da regex de statement DATA (outputs, append-only, non-creator, score
    consultivo, HAS_DATA_STEP) têm de concordar: se uma delas voltar a casar `t2.Data`,
    o metadado diverge do output em silêncio."""
    src = pathlib.Path(e.__file__).read_text(encoding="utf-8")
    sem_guarda = [m.group(0) for m in re.finditer(r"r'(?:\(\?<!\\\.\))?\\bDATA\\s\+", src)
                  if not m.group(0).startswith("r'(?<!")]
    assert not sem_guarda, f"{len(sem_guarda)} regex(es) de statement DATA sem (?<!\\.)"

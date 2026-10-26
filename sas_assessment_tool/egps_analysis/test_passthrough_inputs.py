#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harness de regressão para captura de inputs em pass-through SQL (egps_extractor).

Reproduz casos REAIS do inventário em que o extrator deixava de capturar a tabela
como input:
  - Caso A: notação db..tabela (dono omitido, Sybase) -> 'dbglobal..VwSistema'
  - Caso B: tabela crua (não-qualificada) em JOIN de pass-through -> 'VW_DESDOBRAMENTOS'
  - Caso C: corpo do FROM atravessava ';' e as colunas DB.* do SELECT seguinte viravam tabelas
  - Caso D: o ';' de '%if ... %then %do;' NÃO encerra o FROM -> JOIN condicional continua capturado

Uso: egps_analysis/venv/bin/python test_passthrough_inputs.py
"""
import egps_extractor as e

INPUTS_IDX = 2  # scan_sas_dependencies -> (..., inputs no índice 2, ...)


def inputs_of(sql):
    return set(e.scan_sas_dependencies(sql)[INPUTS_IDX])


# --- Caso A: db..tabela (Sybase, dono omitido) — projeto real Crédito__ProcessoDiario ---
SQL_DOUBLE_DOT = """
PROC SQL;
CONNECT TO SYBASE (DATASRC='X' USER='u' PASSWORD='p');
CREATE TABLE WORK.SIS AS
SELECT A.DsSistema, A.CdSistema
FROM CONNECTION TO SYBASE
(SELECT A.DsSistema, A.CdSistema FROM dbglobal..VwSistema AS A);
DISCONNECT FROM SYBASE;
QUIT;
"""

# --- Caso B: JOINs pendurados num FROM-subquery em pass-through — projeto real Riscos__1403 ---
# Gatilho real: `FROM (SELECT ...) as t1 INNER JOIN ... LEFT JOIN VW_DESDOBRAMENTOS ...`.
# O scan de FROM pula `FROM (`, então toda a cadeia de JOINs da subquery-FROM era ignorada.
# (Estrutura reconstruída; sem credenciais reais.)
SQL_BARE_JOIN = """
PROC SQL;
CONNECT TO postgres (server='s' database='d' user='u' password='REDACTED');
CREATE TABLE work.base AS
SELECT * FROM CONNECTION TO postgres(
SELECT t1.SERIAL_IMPORT
FROM (SELECT P.SERIAL_IMPORT FROM M_ENTIDADE P WHERE UPPER(P.NATUREZA) LIKE 'TRABALHISTA%') as t1
INNER JOIN M_PROCESSO t3 ON t3.SERIAL_IMPORT = t1.SERIAL_IMPORT
INNER JOIN LT_CARTEIRA_CUSTOM t4 ON t4.ID_CARTEIRA_CUSTOM = t3.ID_CARTEIRA_CUSTOM
LEFT JOIN VW_DESDOBRAMENTOS t2 ON t2.SERIAL_IMPORT = t1.SERIAL_IMPORT AND t2.ATUAL = 'SIM'
INNER JOIN LT_TIPO_ACAO t5 ON t5.ID_TIPO_ACAO = t3.ID_TIPO_ACAO
WHERE 1=1
);
DISCONNECT FROM postgres;
QUIT;
"""

# --- Caso C: FROM sem WHERE fecha com ';QUIT;' — projeto real Cobranças__CartoesAmigaveis_PilotoAcordos_20261002 ---
# Nenhuma parada (WHERE/SELECT/...) em profundidade 0 até o '(SELECT' do PROC SQL seguinte; dentro dos
# parênteses o SELECT não corta, e a lista de colunas DB.* era registrada como 15 tabelas.
SQL_FROM_CROSSES_SEMICOLON = """
PROC SQL;
CREATE TABLE tb5a75 AS SELECT a.*, 1 AS PESO FROM LIBA.ORIGEM a
;QUIT;
DATA _NULL_; call symput('anomes', put(202609, 6.)); RUN;
PROC SQL ;
CREATE TABLE WORK.CS_DB AS
(SELECT DB.NUCPFCNPJ, DB.CDPRODUTO, DB.GH_NOVO,
 MOD(input(hashing('sha1',PUT(DB.NUCPFCNPJ+12,z11.)),hex8.),100) as RDG_Collection
FROM LIBB.MARCACAO_DETERIORADO AS DB);
RUN;
"""

# --- Caso D: JOIN dentro de %if/%do no meio do FROM — projeto real Riscos__Controle_PMES_v19 ---
# O ';' de '%do;'/'%end;' pertence ao statement de macro; parar nele perdia MONITRCA.BASE_PME_&dt_ref60.
SQL_FROM_MACRO_DO = """
%macro m;
PROC SQL;
CREATE TABLE base AS SELECT a.nr_nos_nr
from MONITRCA.BASE_PME_&dt_ref. a
left join MONITRCA.BASE_PME_&dt_ref30. b on a.nr_nos_nr = b.nr_nos_nr
%if &dt_ref60. ne . %then %do;
left join MONITRCA.BASE_PME_&dt_ref60. c on a.nr_nos_nr = c.nr_nos_nr
%end;
;QUIT;
%mend;
"""

def W(inner, engine="postgres"):
    """Embrulha um SQL nativo num bloco de pass-through SAS."""
    return (f"PROC SQL; CONNECT TO {engine} (a=1); CREATE TABLE w.x AS "
            f"SELECT * FROM CONNECTION TO {engine}( {inner} ); DISCONNECT FROM {engine}; QUIT;")


# (nome, sql, deve_capturar, NÃO_pode_capturar)
CASES = [
    # --- casos reais (red->green) ---
    ("A: db..tabela captura DBGLOBAL.VWSISTEMA", SQL_DOUBLE_DOT, ["DBGLOBAL.VWSISTEMA"], []),
    ("B: JOINs de FROM-subquery capturam VW_DESDOBRAMENTOS + cadeia", SQL_BARE_JOIN,
     ["VW_DESDOBRAMENTOS", "M_PROCESSO", "LT_CARTEIRA_CUSTOM", "LT_TIPO_ACAO"], []),
    ("C: FROM para no ';' (colunas DB.* não viram tabela)", SQL_FROM_CROSSES_SEMICOLON,
     ["LIBA.ORIGEM", "LIBB.MARCACAO_DETERIORADO"], ["DB.CDPRODUTO", "DB.GH_NOVO"]),
    ("D: ';' de %do/%end não encerra o FROM (JOIN condicional capturado)", SQL_FROM_MACRO_DO,
     ["MONITRCA.BASE_PME_&DT_REF30", "MONITRCA.BASE_PME_&DT_REF60"], []),
    # --- positivos (edge) ---
    ("triple-dot db...tabela", W("select * from db...tab1 a"), ["DB.TAB1"], []),
    ("server.db..tabela", W("select * from srv.db..tab2 a"), ["SRV.DB.TAB2"], []),
    ("JOIN db.schema.table após subquery", W("select * from (select 1 from inner_t) z inner join sch.tab3 q on q.id=z.id"),
     ["INNER_T", "SCH.TAB3"], []),
    # --- negativos (falso-positivo guard) ---
    ("JOIN (subquery) não vira tabela", W("select * from base_t t1 left join (select id from real_t) sub on sub.id=t1.id"),
     ["BASE_T", "REAL_T"], ["SUB"]),
    ("alias após JOIN não vira tabela", W("select * from (select 1 from sq) z inner join realtbl alias1 on alias1.k=z.k"),
     ["REALTBL"], ["ALIAS1", "Z"]),
    ("'JOIN xxx' em literal não captura", W("select * from t_main m where m.txt = 'FOO JOIN BARSTRING'"),
     ["T_MAIN"], ["BARSTRING"]),
    ("JOIN a FQTN BigQuery (com hífen) não vira 'BV' truncado",
     W("select * from base_t b inner join bv-pdbd-prd.ds.tbx x on x.id=b.id", engine="bigquery"),
     ["BV-PDBD-PRD.DS.TBX"], ["BV"]),
]


def run():
    fails = 0
    for name, sql, must, must_not in CASES:
        ins = inputs_of(sql)
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressão: I/O de task do Query Builder que está no fluxo entra no cabeçalho.

O I/O do cabeçalho sai só do código "do fluxo" (`clean_sas_code_flow_linked_only`), que casa os
IDs do PFD com as pastas `<Task>/code.sas` do ZIP. Task do Query Builder não tem pasta de código: o
SQL dela só existe no project.xml, num Element `Code` ("Last Submitted Code") com `Parent` = ID da
task. O código ia para o texto como "Embedded Task (XML)", mas nunca para o I/O — caso real do
Cobranças__Acompanhamento_Desconto - Painel_vK__ATU20260901, cujo `KAUE.SOLAR_DESCONTO_202507` (lido
só pela "Query Builder (2)") não aparecia como input.

O filtro de órfãos continua valendo: código de task que NÃO está em nenhum fluxo fica de fora.

Offline: monta um .egp mínimo (EG 7.1) num diretório temporário.
"""
import re
import zipfile

import egps_extractor as e

PROJECT_XML = r"""<?xml version="1.0" encoding="utf-8"?>
<ProjectCollection>
  <Element Type="SAS.EG.ProjectElements.PFD">
    <Element><Label>Process Flow</Label><Type>CONTAINER</Type><ID>PFD-fluxo1</ID></Element>
    <PFD>
      <Process><Element><ID>CodeTask-prog1</ID></Element><Dependencies /></Process>
      <Process><Element><ID>Query-q1</ID></Element><Dependencies><DepID>CodeTask-prog1</DepID></Dependencies></Process>
      <Process><Element><ID>Query-q2</ID></Element><Dependencies><DepID>Query-q1</DepID></Dependencies></Process>
      <Process><Element><ID>ImportTask-imp1</ID></Element><Dependencies /></Process>
    </PFD>
  </Element>
  <Elements>
    <Element Type="SAS.EG.ProjectElements.CodeTask">
      <Element><Label>Programa</Label><Type>TASK</Type><ID>CodeTask-prog1</ID></Element>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Query">
      <Element><Label>Query Builder</Label><Type>QUERY</Type><ID>Query-q1</ID></Element>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Query">
      <Element><Label>Query Builder (2)</Label><Type>QUERY</Type><ID>Query-q2</ID></Element>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Query">
      <Element><Label>Query Builder (3)</Label><Type>QUERY</Type><ID>Query-orfa</ID></Element>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Code">
      <Element><Label>Last Submitted Code</Label><Type>CODE</Type><ID>Code-c1</ID></Element>
      <Code><Parent>Query-q1</Parent>
        <TaskCode>PROC SQL; CREATE TABLE WORK.QUERY_FOR_BASE AS SELECT t1.CONTRATO FROM LIBQ.TABELA_DA_QUERY t1 INNER JOIN WORK.BASE t2 ON t1.CONTRATO = t2.CONTRATO; QUIT;</TaskCode>
      </Code>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Code">
      <Element><Label>Last Submitted Code</Label><Type>CODE</Type><ID>Code-c2</ID></Element>
      <Code><Parent>Query-q2</Parent>
        <TaskCode>PROC SQL; CREATE TABLE PERMQ.SAIDA_DA_QUERY AS SELECT t1.CONTRATO FROM WORK.QUERY_FOR_BASE t1; QUIT;</TaskCode>
      </Code>
    </Element>
    <Element Type="SAS.EG.ProjectElements.ImportTask">
      <Element><Label>Import Data (orc_capi.xlsm)</Label><Type>TASK</Type><ID>ImportTask-imp1</ID></Element>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Code">
      <Element><Label>Last Submitted Code</Label><Type>CODE</Type><ID>Code-c4</ID></Element>
      <Code><Parent>ImportTask-imp1</Parent>
        <TaskCode>DATA WORK.IMP; INFILE '/SASWORK/SAS_WORK47BF000668D5_SRV-SASPRD05N1/#LN00010' DLM=';'; INPUT A $; RUN; PROC IMPORT DATAFILE="/riscosbv/entrada/orc_capi.csv" OUT=WORK.ORC DBMS=CSV REPLACE; RUN;</TaskCode>
      </Code>
    </Element>
    <Element Type="SAS.EG.ProjectElements.Code">
      <Element><Label>Last Submitted Code</Label><Type>CODE</Type><ID>Code-c3</ID></Element>
      <Code><Parent>Query-orfa</Parent>
        <TaskCode>PROC SQL; CREATE TABLE WORK.QUERY_FOR_ORFA AS SELECT t1.X FROM LIBO.TABELA_ORFA t1; QUIT;</TaskCode>
      </Code>
    </Element>
  </Elements>
</ProjectCollection>
"""

PROGRAMA = "data work.base; set LIBP.TABELA_DO_PROGRAMA; run;\n"


def _cabecalho(tmp_path):
    egp = tmp_path / "Projeto_QB.egp"
    with zipfile.ZipFile(egp, "w") as z:
        z.writestr("project.xml", PROJECT_XML)
        z.writestr("CodeTask-prog1/code.sas", PROGRAMA)
    out = tmp_path / "out"
    out.mkdir()
    e.extract_code_from_egp(str(egp), str(out), business_area="Teste")
    (txt,) = list(out.glob("*.txt"))
    return txt.read_text(encoding="utf-8").split("\nEND_METADATA\n", 1)[0]


def _campo(cab, nome):
    m = re.search(r"^" + re.escape(nome) + r"[^:]*: (.*)$", cab, re.M)
    v = m.group(1).strip() if m else ""
    return set() if v in ("", "(none)") else {x.rsplit(" [", 1)[0].strip().upper() for x in v.split(", ")}


def test_input_lido_so_pela_query_do_fluxo_entra(tmp_path):
    cab = _cabecalho(tmp_path)
    ins = _campo(cab, "EXTERNAL INPUTS")
    assert "LIBP.TABELA_DO_PROGRAMA" in ins, sorted(ins)  # o programa já entrava
    assert "LIBQ.TABELA_DA_QUERY" in ins, sorted(ins)


def test_output_permanente_gravado_pela_query_do_fluxo_entra(tmp_path):
    cab = _cabecalho(tmp_path)
    assert "PERMQ.SAIDA_DA_QUERY" in _campo(cab, "PERMANENT OUTPUTS"), cab


def test_importtask_nao_entra_pelo_codigo_embutido(tmp_path):
    """ImportTask tem caminho próprio (o arquivo de origem sai do XML dela). O código do wizard lê o
    upload temporário (/SASWORK/.../#LN000nn): se entrasse no fluxo, viraria leitura — 126 casos no
    corpus em 14/10/2026."""
    cab = _cabecalho(tmp_path)
    for campo in ("INTERNAL READS", "IMPORTED FILES", "EXTERNAL FILE PATHS"):
        assert not [x for x in _campo(cab, campo) if "SASWORK" in x], _campo(cab, campo)


def test_query_fora_do_fluxo_continua_fora(tmp_path):
    cab = _cabecalho(tmp_path)
    assert "LIBO.TABELA_ORFA" not in _campo(cab, "EXTERNAL INPUTS")


def test_comentario_sem_fechar_vale_ate_o_fim_da_propria_task():
    """Casos reais: Atacado__Esteira 2 ("XX. Correção Database" abre `/*` e nunca fecha) e
    Cobranças__QUERY_LINHA_DIGITAVEL_CA_v2 (`/*AND TO_CHAR(...)` solto na task INICIO). O EG submete cada
    task sozinha e acrescenta `;*';*";*/;quit;run;` no fim: o `/*` sem fechar comenta o RESTO DAQUELA
    task e só. No texto concatenado ele casava com o `*/` de outra task e apagava o código entre as duas
    (ou, sem `*/` adiante, contava código desligado como ativo)."""
    buf = {
        "codetask-a": "data work.ok; set LIBA.ANTES; run;\n/*PROC SQL; CREATE TABLE LIBA.DESLIGADA AS SELECT * FROM LIBA.DESLIGADA; QUIT;",
        "codetask-b": "data work.x; set LIBB.ENTRE_AS_DUAS; run;",
        "query-c": "PROC SQL; CREATE TABLE WORK.Q AS SELECT /* COUNT */ COUNT(*) AS N FROM LIBC.Z t1; QUIT;",
    }
    codigo = e.clean_sas_code_flow_linked_only(buf, {"fluxo": ["codetask-a", "codetask-b", "query-c"]})
    assert "LIBB.ENTRE_AS_DUAS" in codigo and "LIBC.Z" in codigo and "LIBA.ANTES" in codigo
    assert "LIBA.DESLIGADA" not in codigo


def test_barra_asterisco_entre_aspas_nao_e_comentario():
    """`x 'chmod 777 /logs/*';` (6 tasks de Seguros): no SAS o `/*` entre aspas não abre comentário. Não
    pode cortar a task nem casar com o `*/` de outra."""
    buf = {
        "codetask-a": "x 'chmod 777 /seguros/logs/*';\ndata work.y; set LIBD.DEPOIS_DO_CHMOD; run;",
        "codetask-b": "data work.z; set LIBE.OUTRA_TASK; run; /* fim */",
    }
    codigo = e.clean_sas_code_flow_linked_only(buf, {"fluxo": ["codetask-a", "codetask-b"]})
    assert "LIBD.DEPOIS_DO_CHMOD" in codigo and "LIBE.OUTRA_TASK" in codigo

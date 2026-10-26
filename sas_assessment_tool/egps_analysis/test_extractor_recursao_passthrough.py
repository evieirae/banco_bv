#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duas falhas do extractor, testadas nas DUAS cópias (canônica e converter/scripts).

1. `find_real_table_name` recorre por `Parent`/`INPUTID` de atalhos (ShortCutToData) sem
   guarda de ciclo. Um atalho que aponta (direta ou indiretamente) para si mesmo estoura
   RecursionError — e isso não falha só a chamada, derruba a extração do `.egp` inteiro.

2. `analyze_complexity` devolvia `DBT_BQ, 0, "Native SQL"` para QUALQUER task de
   `source_type == 'SQL Query'`, sem olhar o corpo. Mas o Query Builder passa por ali
   também quando o SQL é PASS-THROUGH (`CONNECT TO` / `EXECUTE (...)`), que fala com
   Sybase/SQL Server/BigQuery no dialeto DELES. O TARGET_ARCH saía DBT_BQ e o conversor
   tentaria gerar BigQuery a partir de código que nem é SAS.

As duas cópias são testadas de propósito: o repo mantém `converter/scripts/` como cópia
de diff da canônica, e correção que entra só numa volta a divergir em silêncio (foi o que
aconteceu com o escape de aspa e com o truncamento de chunk).

Offline: monta o XML na mão, não abre `.egp` nenhum.
"""
import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent

COPIAS = {
    "canonica": RAIZ / "egps_analysis" / "egps_extractor.py",
    "converter": RAIZ / "converter" / "scripts" / "egps_extractor.py",
}


def _carrega(nome, caminho):
    spec = importlib.util.spec_from_file_location(f"_ext_{nome}", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MODS = {nome: _carrega(nome, p) for nome, p in COPIAS.items() if p.exists()}
IDS = sorted(MODS)


def _xml(elementos):
    """<Project> com um <Element> por tupla (id, tipo, parent, inputid, label)."""
    partes = ["<Project>"]
    for eid, tipo, parent, inputid, label in elementos:
        partes.append("<Element>")
        partes.append(f"<ID>{eid}</ID>")
        if tipo:
            partes.append(f"<Type>{tipo}</Type>")
        if parent:
            partes.append(f"<Parent>{parent}</Parent>")
        if inputid:
            partes.append(f"<INPUTID>{inputid}</INPUTID>")
        if label:
            partes.append(f"<Label>{label}</Label>")
        partes.append("</Element>")
    partes.append("</Project>")
    return ET.fromstring("".join(partes))


# ---------------------------------------------------------------- guarda de ciclo

@pytest.mark.parametrize("copia", IDS)
def test_atalho_que_aponta_para_si_mesmo_nao_estoura(copia):
    m = MODS[copia]
    root = _xml([("A", "ShortCutToData", "A", None, None)])
    assert m.find_real_table_name(root, "A", {}) == "WORK.UNKNOWN_TABLE"


@pytest.mark.parametrize("copia", IDS)
def test_ciclo_de_dois_atalhos_nao_estoura(copia):
    m = MODS[copia]
    root = _xml([("A", "ShortCutToData", "B", None, None),
                 ("B", "ShortCutToData", "A", None, None)])
    assert m.find_real_table_name(root, "A", {}) == "WORK.UNKNOWN_TABLE"


@pytest.mark.parametrize("copia", IDS)
def test_ciclo_por_INPUTID_tambem(copia):
    """A recursão desce por dois caminhos; o guarda vale para os dois."""
    m = MODS[copia]
    root = _xml([("A", "ShortCutToData", None, "B", None),
                 ("B", "ShortCutToData", None, "A", None)])
    assert m.find_real_table_name(root, "A", {}) == "WORK.UNKNOWN_TABLE"


@pytest.mark.parametrize("copia", IDS)
def test_cadeia_legitima_continua_resolvendo(copia):
    """Controle: atalho -> atalho -> tabela real tem de chegar no Label do fim."""
    m = MODS[copia]
    root = _xml([("A", "ShortCutToData", "B", None, None),
                 ("B", "ShortCutToData", "C", None, None),
                 ("C", "DataTable", None, None, "[LIB.TABELA_REAL]")])
    assert m.find_real_table_name(root, "C", {}) == "WORK.LIB.TABELA_REAL"
    assert m.find_real_table_name(root, "A", {}) == "WORK.LIB.TABELA_REAL"


@pytest.mark.parametrize("copia", IDS)
def test_label_com_WORK_passa_intacto(copia):
    m = MODS[copia]
    root = _xml([("A", "DataTable", None, None, "WORK.MINHA_TAB")])
    assert m.find_real_table_name(root, "A", {}) == "WORK.MINHA_TAB"


@pytest.mark.parametrize("copia", IDS)
def test_elemento_ausente_cai_no_node_map(copia):
    m = MODS[copia]
    root = _xml([("A", "DataTable", None, None, "X")])
    assert m.find_real_table_name(root, "Z", {"Z": "DO_MAPA"}) == "WORK.DO_MAPA"


@pytest.mark.parametrize("copia", IDS)
def test_id_vazio_devolve_desconhecido(copia):
    m = MODS[copia]
    assert m.find_real_table_name(_xml([]), "", {}) == "WORK.UNKNOWN_TABLE"


# ---------------------------------------------------------------- pass-through

PASSTHROUGH = [
    "PROC SQL; CONNECT TO SYBASE AS c (user=x); "
    "CREATE TABLE a AS SELECT * FROM CONNECTION TO c (SELECT * FROM dbo.t); QUIT;",
    "PROC SQL; CONNECT TO BIGQUERY; EXECUTE (DELETE FROM proj.ds.t WHERE 1=1) BY BIGQUERY; QUIT;",
    "proc sql;\n  connect to odbc as lig;\nquit;",
]

NATIVO = [
    "PROC SQL; CREATE TABLE WORK.A AS SELECT * FROM LIB.B; QUIT;",
    "PROC SQL; SELECT count(*) FROM LIB.T GROUP BY 1; QUIT;",
]


@pytest.mark.parametrize("copia", IDS)
@pytest.mark.parametrize("code", PASSTHROUGH)
def test_sql_query_com_passthrough_vai_para_databricks(copia, code):
    m = MODS[copia]
    alvo, score, razao = m.analyze_complexity(code, source_type="SQL Query")
    assert alvo == "DATABRICKS", f"pass-through declarado {alvo}: {razao}"
    assert score >= 70, "score abaixo do limiar de DATABRICKS"
    assert "pass-through" in razao.lower()


@pytest.mark.parametrize("copia", IDS)
@pytest.mark.parametrize("code", NATIVO)
def test_sql_query_nativo_continua_dbt_bq(copia, code):
    """Controle: SQL nativo não pode ser arrastado para Databricks pelo fix."""
    m = MODS[copia]
    alvo, score, razao = m.analyze_complexity(code, source_type="SQL Query")
    assert (alvo, score, razao) == ("DBT_BQ", 0, "Native SQL")


@pytest.mark.parametrize("copia", IDS)
def test_passthrough_fora_de_sql_query_segue_o_caminho_normal(copia):
    """Sem source_type 'SQL Query' a função nem entra no atalho — não deve mudar nada."""
    m = MODS[copia]
    alvo, _score, _razao = m.analyze_complexity(PASSTHROUGH[0], source_type="")
    assert alvo in ("DBT_BQ", "DATABRICKS")   # decidido pelos pesos, não pelo atalho


def test_as_duas_copias_estao_no_teste():
    """Se `converter/scripts/` sumir ou mudar de lugar, o teste tem de acusar em vez de
    silenciosamente passar a cobrir só uma cópia."""
    assert set(MODS) == {"canonica", "converter"}, f"cópias carregadas: {sorted(MODS)}"

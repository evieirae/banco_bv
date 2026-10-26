"""Roda contra o schema-alvo (só leitura) cada peça de conhecimento.py, os exemplos e os benchmarks.

Pega o que o Genie aceitaria em silêncio e quebraria na hora da pergunta: coluna com nome
errado, expressão que não compila, join sem casamento nenhum, exemplo com parâmetro inválido.
Uso: python valida_conhecimento.py [--schema monitoramento_sas_dev]  (sai 1 se algo falhar)
"""
import argparse
import pathlib
import re
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format

import conhecimento as K

AQUI = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--schema", default="monitoramento_sas")
FQ = f"bv_dev_db.{ap.parse_args().schema}"
w = WorkspaceClient(profile="bv")


def troca(txt):
    return txt.replace("bv_dev_db.monitoramento_sas.", f"{FQ}.")


def roda(sql):
    assert re.match(r"^\s*(SELECT|WITH|DESCRIBE)\b", sql, re.I), "só leitura"
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id="5922c26f81f1bbdd", wait_timeout="50s",
                                                disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else str(r.status.state))
    return r.result.data_array or []


def tabelas_de(expr):
    return sorted(set(re.findall(r"\b(sas_[a-z_]+)\.", expr)))


def from_de(tabs):
    assert len(tabs) == 1, f"expressão cruza tabelas: {tabs}"
    return f"FROM {FQ}.{tabs[0]} AS {tabs[0]}"


falhas = []


def checa(rotulo, sql, exige_linha=False):
    try:
        linhas = roda(sql)
        if exige_linha and not (linhas and linhas[0] and str(linhas[0][0]) not in ("0", "None")):
            raise RuntimeError(f"zero casamentos: {linhas[:1]}")
        print(f"ok   {rotulo}")
    except Exception as e:
        falhas.append(rotulo)
        print(f"FAIL {rotulo}: {str(e)[:300]}")


for tab, cols in K.COLUNAS.items():
    try:
        existentes = {r[0] for r in roda(f"DESCRIBE {FQ}.{tab}") if r[0] and not r[0].startswith("#")}
    except Exception as e:
        falhas.append(f"tabela {tab}")
        print(f"FAIL tabela {tab}: {str(e)[:200]}")
        continue
    for c in cols:
        if c not in existentes:
            falhas.append(f"coluna {tab}.{c}")
            print(f"FAIL coluna {tab}.{c} não existe")
print(f"ok   colunas ({sum(len(c) for c in K.COLUNAS.values())} configuradas)")

for nome, sql, *_ in K.FILTROS:
    checa(f"filtro '{nome}'", f"SELECT count(*) {from_de(tabelas_de(sql))} WHERE {sql}")
for nome, sql, *_ in K.CAMPOS:
    checa(f"campo '{nome}'", f"SELECT {sql} {from_de(tabelas_de(sql))} LIMIT 5")
for nome, sql, *_ in K.MEDIDAS:
    checa(f"medida '{nome}'", f"SELECT {sql} {from_de(tabelas_de(sql))}")
for esq, dir_, cond, _rel in K.JOINS:
    checa(f"join {esq}->{dir_}",
          f"SELECT count(*) FROM {FQ}.{esq} AS {esq} JOIN {FQ}.{dir_} AS {dir_} ON {cond}", exige_linha=True)

txt = troca((AQUI / "exemplos.sql").read_text(encoding="utf-8"))
blocos = re.split(r"^-- ([A-Z]\d+) (.+)$", txt, flags=re.M)
ids = []
for i in range(1, len(blocos), 3):
    bid, sql = blocos[i], blocos[i + 2].strip().rstrip(";").strip()
    ids.append(bid)
    for nome, _tipo, _d, padrao in K.PARAMETROS.get(bid, []):
        sql = sql.replace(f":{nome}", "'" + padrao.replace("'", "''") + "'")
    checa(f"exemplo {bid}", f"SELECT count(*) FROM ({sql})")
for bid in K.PARAMETROS:
    if bid not in ids:
        falhas.append(f"parâmetro de {bid} sem exemplo")
        print(f"FAIL PARAMETROS[{bid}] não tem bloco em exemplos.sql")

txt = troca((AQUI / "benchmarks.sql").read_text(encoding="utf-8"))
blocos = re.split(r"^-- (B\d+) \| (?:escalar|conjunto) \| (.+)$", txt, flags=re.M)
for i in range(1, len(blocos), 3):
    checa(f"benchmark {blocos[i]}", f"SELECT count(*) FROM ({blocos[i + 2].strip().rstrip(';').strip()})")

print(f"\n{len(falhas)} falha(s)" + (f": {falhas}" if falhas else ""))
sys.exit(1 if falhas else 0)

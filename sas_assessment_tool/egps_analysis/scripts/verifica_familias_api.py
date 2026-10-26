#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate do ticket 09: os números da API com e sem a flag de família, num schema de DEV.

Complementa `verifica_familias.py` (que mede por fora, em SQL): aqui a medição sai da
PRÓPRIA API, exercitando os endpoints que a tela usa. Rodar as duas pontas e comparar é o
que prova que a unidade mudou sem a contagem quebrar.

Rode DUAS vezes, uma por valor da flag (ela é lida no import do backend):
    cd egps_analysis
    export PUBLISH_SCHEMA=monitoramento_sas_dev DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd
    venv/bin/python scripts/verifica_familias_api.py                   # flag desligada
    FAMILIAS_SAFRA=1 venv/bin/python scripts/verifica_familias_api.py  # flag ligada

(sem `DATABRICKS_WAREHOUSE_ID` o backend devolve 500 e o script morre em KeyError: 'rows'.)

Só leitura de dados — mas o boot do backend cria as tabelas de estado ausentes
(`CREATE TABLE IF NOT EXISTS`), então o script RECUSA schema de produção.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "backend"))

if os.environ.get("PUBLISH_SCHEMA", "") == "monitoramento_sas":
    sys.exit("❌ PUBLISH_SCHEMA=monitoramento_sas é PROD — o boot do backend cria tabelas; "
             "rode contra um schema _dev.")
os.environ.setdefault("PUBLISH_SCHEMA", "monitoramento_sas_dev")
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "bv")

from fastapi.testclient import TestClient  # noqa: E402
from backend import main as M  # noqa: E402


def main():
    c = TestClient(M.app)
    on = M.FAMILIAS_ON
    print(f"== FAMILIAS_SAFRA={'ON' if on else 'OFF'} · {M.FQ} ==")
    inp = c.get("/api/inputs", params={"scope": "indi"}).json()
    land = c.get("/api/landing").json()
    fun = c.get("/api/funis").json()
    res = c.get("/api/resumo").json()
    mes = c.get("/api/funil-ingestao-mes").json()
    rdy = c.get("/api/egp-readiness", params={"scope": "indi_deps"}).json()

    fams = [r for r in inp["rows"] if r.get("is_familia")]
    print(f"\naba Inputs   : grao={inp.get('grao')} linhas={inp['total']} famílias={len(fams)}")
    print(f"landing      : escopo={land['inputs_escopo']} a_ingerir={land['inputs_a_ingerir']} "
          f"deps={land['inputs_deps']} total={land['total_inputs']}")
    kpi = {x["label"]: x["value"] for x in fun["ingestao"]["top_stats"]}
    print(f"funil ingest.: universo={fun['ingestao']['total'] + kpi['Sanitizado']} "
          f"coorte={fun['ingestao']['coorte']} sanitizados={kpi['Sanitizado']}")
    print(f"resumo origem: {res['origem']['total']}")
    print(f"funil por mês: total={mes['total']} sanitizados={mes['sanitizados']}")
    print(f"readiness    : EGPs={len(rdy['rows'])} "
          f"soma_n_inputs={sum(int(r['n_inputs']) for r in rdy['rows'])} "
          f"soma_n_faltam={sum(int(r['n_faltam']) for r in rdy['rows'])}")

    # --- coerência interna: as quatro superfícies têm que falar do MESMO universo ---
    print("\ncoerência (tudo True):")
    ri = M._universo_contagem(M._dataset_escopo("indi", []))
    checks = {
        "card escopo == universo do dataset": land["inputs_escopo"] == len(ri),
        "universo do funil == card escopo":
            fun["ingestao"]["total"] + kpi["Sanitizado"] == land["inputs_escopo"],
        "tabela de origem + fora-dos-4-buckets == card":
            res["origem"]["total"]["total"]
            + sum(1 for r in ri if not M._bucket_origem(r.get("origem")))
            == land["inputs_escopo"],
        "funil por mês == funil +deps":
            mes["total"] + mes["sanitizados"]
            == fun["ingestao_deps"]["total"]
            + {x["label"]: x["value"] for x in fun["ingestao_deps"]["top_stats"]}["Sanitizado"],
    }
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'FALHOU'} {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

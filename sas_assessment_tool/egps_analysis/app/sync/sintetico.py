# -*- coding: utf-8 -*-
"""Massa SINTÉTICA no formato do Databricks, para o ensaio diário na training (ADR 0005).

A training não recebe dado do BV (é compartilhada e apagada toda noite pelo aws-nuke). Esta
massa passa pelo MESMO caminho da sincronização real (de-para -> retrato -> carga atômica),
então o ensaio exercita o código de verdade, só que com nomes inventados.

Uso: PG_DSN=... python -m sync.sintetico [--gestao fulano@indicium.ai]
"""
import argparse
import os
import random
import uuid

import psycopg

from . import carrega, retrato

AREAS = ("Cobranças", "Riscos", "Jurídico")
ETAPAS = (("A Receber", "A Iniciar"), ("Recebido", "A Iniciar"), ("Pré-Working", "Em Andamento"),
          ("Modernizado", "Concluído"), ("Modernizado", "Sanitizado"))
MOLDES = (("tabela", "LIB{n}.TAB_{i:04d}"), ("arquivo", "ARQ_{i:04d}.CSV"), ("script", "SCRIPT_{i:04d}.SAS"))


def linhas(n_egps=40, n_inputs=300, semente=42):
    """Linhas das 5 tabelas Delta que a fatia 1a sincroniza, todas como TEXTO (igual ao
    Databricks). Determinístico pela semente: o ensaio de hoje é igual ao de ontem."""
    rnd = random.Random(semente)
    egps = [f"{AREAS[i % 3]}__EGP_TREINO_{i:03d}" for i in range(n_egps)]
    no_escopo = set(egps[: n_egps * 2 // 3])
    inputs = []
    for i in range(n_inputs):
        cat, molde = MOLDES[i % 3]
        art = molde.format(n=i % 7, i=i)
        etapa, status = rnd.choice(ETAPAS)
        inputs.append({
            "chave_canonica": f"{cat}::{art}", "artifact": art, "categoria": cat,
            "source_types": "PROC SQL | DATA", "qtd_projetos": str(rnd.randint(1, 4)),
            "areas": " | ".join(sorted(rnd.sample(AREAS, rnd.randint(1, 2)))),
            "modernizada_auto": "Disponível" if etapa == "Modernizado" else "A ingerir",
            "responsavel": "", "observacao": None, "updated_at": None, "updated_by": None,
            "orfao": "false", "refreshed_at": "2026-10-15 09:00:00",
            "origem": rnd.choice(("BigQuery", "Transacional", "Arquivo")), "paths_fisicos": "",
            "n_paths_fisicos": "0", "etapa": etapa, "status": status})
    pares = []
    for p in egps:
        for r in rnd.sample(inputs, rnd.randint(3, 8)):
            pares.append({"projeto": p, "area": p.split("__")[0], "onda": "Onda 0",
                          "escopo_indi": "true" if p in no_escopo else "false", "ciclo_id": "0",
                          "chave_canonica": r["chave_canonica"], "artifact": r["artifact"],
                          "categoria": r["categoria"], "source_types": "PROC SQL",
                          "modernizada_auto": r["modernizada_auto"]})
    # escopo_indi gravado como o publish do Databricks grava: EGP do escopo, e input lido por um
    lidos = {x["chave_canonica"] for x in pares if x["projeto"] in no_escopo}
    for r in inputs:
        r["escopo_indi"] = "true" if r["chave_canonica"] in lidos else "false"
    nos = [{"projeto": p, "area": p.split("__")[0], "onda": "Onda 0", "ciclo_id": "0",
            "escopo_indi": "true" if p in no_escopo else "false", "n_outputs": "0",
            "n_inputs": str(sum(1 for x in pares if x["projeto"] == p))} for p in egps]
    escopo = [{"id": uuid.UUID(int=rnd.getrandbits(128)).hex, "egp_dor1": p.split("__")[1],
               "area": p.split("__")[0], "status_extracao": "exato", "projeto": p, "origem": "csv",
               "created_by": "seed", "created_at": "seed", "ativo": "true"}
              for p in egps if p in no_escopo]
    return {"sas_lineage_nodes": nos, "sas_inputs_monitor": inputs, "sas_egp_inputs": pares,
            "sas_escopo": escopo, "sas_analistas": []}


def carrega_sintetico(conn, gestao=None):
    resumo = carrega.carrega(conn, retrato.monta(linhas()), "sintetico")
    if gestao:
        conn.execute("INSERT INTO cadastro.usuario (email, nome, papel) VALUES (%s, %s, 'gestao') "
                     "ON CONFLICT (email) DO UPDATE SET papel = 'gestao', ativo = true",
                     (gestao.strip().lower(), gestao))
        conn.commit()
    return resumo


def main(argv=None):
    ap = argparse.ArgumentParser(description="Carga sintética para o ensaio na training")
    ap.add_argument("--gestao", help="e-mail que entra como gestão (o DEV_USUARIO do ensaio)")
    args = ap.parse_args(argv)
    with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
        print(f"[sintetico] OK {carrega_sintetico(conn, args.gestao)}", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Religa escopo_indi do EGP Cobranças__CPF_Contrato__v2 (reparo pontual).

Desde 16/10/2026 o renome vem de `src/egps_decisoes.csv` e o publish já grava o nó como __v2
antes do recompute; o re-key pós-publish descrito abaixo não roda mais. Segue útil só para
CONFERIR se as duas contagens do Resumo batem.

POR QUE: o re-key pós-publish (reaplica_rename_cpf_contrato_pos_publish.py) renomeia
o nó para __v2 DEPOIS do recompute_escopo, e não reaplica a flag. O EGP fica com a
linha ATIVA em sas_escopo mas escopo_indi=false no grafo — o que separa por 1 as duas
contagens da aba Resumo (card por sas_escopo = 195; funil/grafo = 194).

Desde 18/09/2026 o próprio reaplica_rename_cpf_contrato_pos_publish.py faz isso no
passo 4, então este script é rede de segurança/diagnóstico: use-o para CONFERIR se as
duas contagens batem, ou para reparar um ambiente onde o re-key rodou na versão antiga.

Espelha exatamente os 4 UPDATEs "liga" de recompute_escopo (publish_to_databricks.py
~L1400 e main.py), restritos a este projeto. NÃO toca sas_egp_outputs: os 4 outputs
CARNEIRO.BASE_3040_* ficam escopo_indi=false de propósito (decisão do re-key).

    python repara_escopo_indi_cpf_contrato.py                  # dry-run
    python repara_escopo_indi_cpf_contrato.py --apply          # grava
    python repara_escopo_indi_cpf_contrato.py --schema monitoramento_sas_dev --apply
"""
import argparse

from databricks.sdk import WorkspaceClient

WAREHOUSE = "5922c26f81f1bbdd"
PROJETO = "Cobranças__CPF_Contrato__v2"


def executa(w, sql):
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE, wait_timeout="50s")
    if r.status and r.status.state.value != "SUCCEEDED":
        raise SystemExit(f"FALHOU: {sql[:90]}…\n  {r.status.error}")
    return r.result.data_array or [] if r.result else []


def diagnostico(w, fq):
    """(base no grafo, escopo ativo, flag do nó) — as 3 contas que devem casar."""
    row = executa(w, f"""SELECT
      (SELECT count(*) FROM {fq}.sas_lineage_nodes WHERE escopo_indi = true),
      (SELECT count(*) FROM {fq}.sas_escopo WHERE projeto <> '' AND ativo IS NOT false),
      (SELECT max(CASE WHEN escopo_indi THEN 1 ELSE 0 END) FROM {fq}.sas_lineage_nodes
        WHERE projeto = '{PROJETO}')""")[0]
    return int(row[0]), int(row[1]), row[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava (sem isso, só mostra)")
    ap.add_argument("--catalog", default="bv_dev_db")
    ap.add_argument("--schema", default="monitoramento_sas")
    ap.add_argument("--profile", default="bv")
    args = ap.parse_args()

    fq = f"{args.catalog}.{args.schema}"
    w = WorkspaceClient(profile=args.profile)

    # Mesmos predicados do recompute, restritos ao projeto. Só LIGAM a flag: uma
    # chave_canonica compartilhada com outro EGP em escopo já está true.
    ch_egp = (f"(SELECT DISTINCT chave_canonica FROM {fq}.sas_egp_inputs "
              f"WHERE projeto = '{PROJETO}')")
    ch_res = (f"(SELECT DISTINCT chave_canonica FROM {fq}.sas_resumo_proj "
              f"WHERE projeto = '{PROJETO}')")
    statements = [
        f"UPDATE {fq}.sas_lineage_nodes  SET escopo_indi = true WHERE projeto = '{PROJETO}'",
        f"UPDATE {fq}.sas_egp_inputs     SET escopo_indi = true WHERE projeto = '{PROJETO}'",
        f"UPDATE {fq}.sas_inputs_monitor SET escopo_indi = true WHERE chave_canonica IN {ch_egp}",
        f"UPDATE {fq}.sas_resumo_inputs  SET escopo_indi = true WHERE chave_canonica IN {ch_res}",
    ]

    base, ativo, flag = diagnostico(w, fq)
    print(f"== {fq} ==")
    print(f"  ANTES: base no grafo={base}  escopo ativo={ativo}  flag do nó={flag}")
    if base == ativo:
        print("  nada a fazer: as contagens já batem.")
        return

    if not args.apply:
        print("\n[dry-run] rodaria:")
        for s in statements:
            print(f"  {s}")
        print("\n  use --apply para gravar")
        return

    for s in statements:
        executa(w, s)
        print(f"  ok  {s[:72]}…")

    base, ativo, flag = diagnostico(w, fq)
    print(f"\n  DEPOIS: base no grafo={base}  escopo ativo={ativo}  flag do nó={flag}")
    print("  OK: contagens casam." if base == ativo else "  ATENÇÃO: ainda divergem.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guarda de IDENTIDADE de input: o publish desfez alguma decisão de colapso?

## O problema que esta guarda existe para tornar barulhento

Decisões de identidade — qual alias de libname é o canônico, qual chave uma planilha
`[SHEET=]` recebe — são aplicadas como UPDATE/DELETE nas tabelas do corpus. O publish é
full-replace nessas tabelas (`DROP TABLE` em `sas_lineage_*`, `sas_egp_inputs`, …), então
toda decisão morre no publish seguinte **sem uma linha de log**.

Medido em 29/09/2026 comparando prod com um clone que levou republish completo: dos **101**
colapsos ativos em `sas_input_alias_canonico`, prod tinha **0** chaves soltas (colapso
aplicado) e o clone tinha **101** (colapso inteiro desfeito). O mapa sobreviveu ao publish;
o efeito dele não. O sintoma chegou como "o escopo mudou de 1.237 para 1.251 e não sei por
quê".

## O que ela faz

Nada além de contar e recusar. `verifica()` é pura — recebe conjuntos, devolve o veredito —
e `main()` liga nas tabelas. NÃO escreve, NÃO repara: reparar exige decidir o que fazer com
o estado humano da chave que some, e essa decisão é do ticket 25, não de uma guarda.

Exit 1 quando há colapso desfeito. É de propósito: um publish que apaga 101 decisões em
silêncio é pior que um publish que falha.
"""
import argparse
import os
import sys

TABELA_MAPA = "sas_input_alias_canonico"


def verifica(colapsos_ativos, chaves_no_corpus):
    """(desfeitos, veredito). `colapsos_ativos` = chaves NÃO-canônicas que o mapa manda
    colapsar; `chaves_no_corpus` = as chaves vivas em sas_inputs_monitor.

    Pura de propósito: a régua é testável sem banco, e o `main()` abaixo só a alimenta.
    Uma chave que o mapa manda colapsar e que ainda está viva no corpus é um colapso
    desfeito — não importa por qual publish."""
    desfeitos = set(colapsos_ativos or ()) & set(chaves_no_corpus or ())
    return desfeitos, {
        "colapsos_ativos": len(set(colapsos_ativos or ())),
        "desfeitos": len(desfeitos),
        "ok": not desfeitos,
    }


def _linha_de_saida(v, desfeitos, limite=12):
    if v["colapsos_ativos"] == 0:
        return ["  identidade: mapa vazio — nada a verificar."]
    if v["ok"]:
        return [f"  identidade: OK — {v['colapsos_ativos']} colapso(s) do mapa seguem aplicados."]
    out = [f"  ERRO DE IDENTIDADE: o corpus tem {v['desfeitos']} de {v['colapsos_ativos']} "
           f"colapso(s) DESFEITO(S).",
           f"  Cada um é uma decisão de identidade que alguém tomou e este publish apagou.",
           f"  Reaplique antes de considerar o publish bom (ticket 25). Chaves:"]
    for c in sorted(desfeitos)[:limite]:
        out.append(f"     {c}")
    if len(desfeitos) > limite:
        out.append(f"     … e mais {len(desfeitos) - limite}")
    return out


def _chaves(linhas):
    """Extrai a 1ª coluna, seja a linha um dict ou uma lista posicional.

    As duas formas existem de verdade: o `read_rows` do `publish_to_databricks.py` devolve
    LISTAS POSICIONAIS (ele pagina chunks do `data_array`), e o do app devolve dicts. A
    guarda roda nos dois, então não pode assumir nenhuma — foi isso que quase a deixou
    quebrada exatamente onde ela mais importa, dentro do publish."""
    out = set()
    for l in linhas or ():
        if isinstance(l, dict):
            v = l.get("chave_canonica")
        elif l:
            v = l[0]
        else:
            continue
        if v:
            out.add(v)
    return out


def checa_no_banco(read_rows, fq):
    """Lê o mapa e o corpus e devolve (desfeitos, veredito). `read_rows(sql)` pode devolver
    dicts (app) ou listas posicionais (publish) — ver `_chaves`.

    Mapa ausente (nunca criado neste schema) é `ok` com 0 colapsos, não erro: o schema
    simplesmente não tem decisão de identidade registrada."""
    try:
        mapa = read_rows(
            f"SELECT chave_canonica FROM {fq}.{TABELA_MAPA} "
            f"WHERE eh_canonico = 'false' AND ativo = 'true'")
    except Exception as e:                      # tabela ausente -> sem decisões a proteger
        print(f"  identidade: {TABELA_MAPA} ausente ({type(e).__name__}); nada a verificar.")
        return set(), {"colapsos_ativos": 0, "desfeitos": 0, "ok": True}
    vivas = read_rows(f"SELECT chave_canonica FROM {fq}.sas_inputs_monitor WHERE NOT orfao")
    return verifica(_chaves(mapa), _chaves(vivas))


def flags_defasadas(read_rows, fq):
    """Chaves cujo `escopo_indi` no monitor NÃO bate com os pares que a leem.

    Segunda invariante, aprendida errando: a 1ª versão da reaplicação repontava os pares e
    deixava a flag velha, e o `CP.MIS_TABLEAU_GERAL_2` passou a contar como dependência em
    vez de escopo — a guarda original não pegou, porque ela só conferia que o alias sumiu.
    Colapso aplicado não basta; as derivações têm de acompanhar."""
    try:
        linhas = read_rows(
            f"SELECT i.chave_canonica FROM {fq}.sas_inputs_monitor i "
            f"WHERE NOT i.orfao AND coalesce(i.escopo_indi, false) <> "
            f"(i.chave_canonica IN (SELECT DISTINCT chave_canonica FROM {fq}.sas_egp_inputs "
            f"WHERE escopo_indi = true))")
    except Exception as e:
        print(f"  identidade: nao deu p/ conferir escopo_indi ({type(e).__name__}).")
        return set()
    return _chaves(linhas)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "bv"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    a = ap.parse_args()
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=a.profile)

    def read_rows(sql):
        r = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=a.warehouse_id, wait_timeout="50s")
        cols = [c.name for c in (r.manifest.schema.columns or [])]
        return [dict(zip(cols, row)) for row in (r.result.data_array or [])] if r.result else []

    desfeitos, v = checa_no_banco(read_rows, f"{a.catalog}.{a.schema}")
    print(f"=== identidade de input — {a.catalog}.{a.schema}")
    for l in _linha_de_saida(v, desfeitos):
        print(l)
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

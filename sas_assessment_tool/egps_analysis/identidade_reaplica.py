#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reaplica os colapsos de identidade que o publish desfaz (ticket 25, camada 2).

## Por que existe

O publish é full-replace nas tabelas do corpus, então todo colapso de alias aplicado à mão
morre nele. Medido em 29/09/2026: um republish desfez os **101** colapsos ativos de
`sas_input_alias_canonico` de uma vez. `identidade_guard.py` tornou isso barulhento; este
módulo fecha o ciclo — o publish reaplica sozinho e o guard confirma.

Substitui os scripts avulsos que existiam um por caso (o rename do `CPF_Contrato`, as
planilhas `[SHEET=]`, os homônimos de libname) por um só, dirigido por **dado versionado**
em vez de lista no código.

## A semântica NÃO foi inventada

Ela foi lida do próprio prod, comparando uma chave colapsada tabela a tabela contra um
clone que levou republish. O colapso toca exatamente três:

| tabela | o que acontece com o alias |
|---|---|
| `sas_egp_inputs`    | o par é **repontado** para o canônico |
| `sas_inputs_monitor`| a linha é **apagada** (o canônico não é tocado) |
| `sas_resumo_inputs` | a linha é **apagada** |

O canônico fica intacto de propósito: **estado não se propaga entre irmãos** (regra de
23/09/2026 — propagar cancelaria ingestão ativa). É por isso que o passo abaixo RECUSA
quando o alias carrega trabalho de gente.

## As duas recusas

Nenhuma adivinha; as duas falham alto e não escrevem nada daquele colapso.

1. **alvo ausente** em `sas_inputs_monitor` — apagar o alias perderia o input inteiro;
2. **alias com estado além do default** (`A Receber`/`A Iniciar`, sem responsável nem
   observação) — apagá-lo jogaria fora trabalho humano. Em 29/09 os 101 estavam todos no
   default, então a reaplicação era lossless; a recusa existe para o dia em que não for.
"""
import argparse
import os
import sys

TABELA_MAPA = "sas_input_alias_canonico"
ETAPA_DEFAULT = "A Receber"
STATUS_DEFAULT = "A Iniciar"


def _vazio(v):
    return not (v or "").strip()


def sem_trabalho_humano(linha):
    """A linha do monitor está no estado de fábrica? Só então ela pode ser apagada.

    `modernizada_auto` NÃO entra: é detecção automática, recalculada no publish seguinte —
    tratá-la como trabalho humano bloquearia o colapso por um dado que se refaz sozinho."""
    return ((linha.get("etapa") or ETAPA_DEFAULT) == ETAPA_DEFAULT
            and (linha.get("status") or STATUS_DEFAULT) == STATUS_DEFAULT
            and _vazio(linha.get("responsavel"))
            and _vazio(linha.get("observacao")))


def plano(alias_para_alvo, monitor, descartar_estado=False):
    """(aceitos, recusas) — PURA, para a régua ser testável sem banco.

    `alias_para_alvo`: {chave_alias: chave_alvo} só dos colapsos ativos.
    `monitor`: {chave: linha} das chaves vivas em sas_inputs_monitor.

    Alias que já não está no monitor foi colapsado antes: sai do plano sem virar recusa —
    é o que faz rodar duas vezes não mudar nada."""
    aceitos, recusas = {}, []
    for alias, alvo in sorted((alias_para_alvo or {}).items()):
        if alias not in (monitor or {}):
            continue                                  # já colapsado: idempotência
        if alvo not in (monitor or {}):
            recusas.append((alias, alvo, "alvo ausente em sas_inputs_monitor"))
            continue
        if not sem_trabalho_humano(monitor[alias]) and not descartar_estado:
            recusas.append((alias, alvo, "alias tem estado humano gravado"))
            continue
        aceitos[alias] = alvo
    return aceitos, recusas


def sqls(aceitos, fq):
    """Os statements de um colapso, na ordem que importa: o par é repontado ANTES de a
    linha do alias sumir, senão sobra par órfão. A deduplicação vem antes do UPDATE porque
    o EGP pode já ler o canônico (14 casos em 29/09) e o repontar criaria linha dupla."""
    if not aceitos:
        return []
    T_EGP, T_IN = f"{fq}.sas_egp_inputs", f"{fq}.sas_inputs_monitor"
    T_RES, T_LINK = f"{fq}.sas_resumo_inputs", f"{fq}.sas_egp_input_link"
    lit = lambda v: "'" + str(v).replace("'", "''") + "'"
    out = []
    for alias, alvo in sorted(aceitos.items()):
        a, t = lit(alias), lit(alvo)
        # 1. o EGP que já lê o canônico não ganha linha dupla — o par do alias some
        out.append(f"DELETE FROM {T_EGP} WHERE chave_canonica = {a} AND projeto IN "
                   f"(SELECT projeto FROM {T_EGP} WHERE chave_canonica = {t})")
        out.append(f"DELETE FROM {T_LINK} WHERE chave_canonica = {a} AND projeto IN "
                   f"(SELECT projeto FROM {T_LINK} WHERE chave_canonica = {t})")
        # 2. o resto reponta (o link segue o par: é a MESMA decisão humana, sobre o mesmo
        #    par EGP×input — não é propagar estado para um irmão)
        out.append(f"UPDATE {T_EGP} SET chave_canonica = {t} WHERE chave_canonica = {a}")
        out.append(f"UPDATE {T_LINK} SET chave_canonica = {t} WHERE chave_canonica = {a}")
        # 3. o alias some das tabelas por chave; o canônico fica intocado
        out.append(f"DELETE FROM {T_IN} WHERE chave_canonica = {a}")
        out.append(f"DELETE FROM {T_RES} WHERE chave_canonica = {a}")
    return out


def sqls_flags(alvos, fq):
    """RECOMPUTA `escopo_indi` das chaves canônicas — a partir dos pares que as leem.

    Repontar o par muda QUEM lê a chave, e essa flag é derivada dos pares; só que quem a
    calcula é o publish, que já passou. Sem isto o canônico que GANHOU um leitor de escopo
    pelo colapso fica com a flag velha e cai no balde errado: em 30/09 o
    `CP.MIS_TABLEAU_GERAL_2` tinha 2 pares de escopo apontando para ele e
    `escopo_indi=false`, contando como dependência em vez de escopo.

    Roda SEMPRE, não só nos colapsos aceitos desta rodada: a reaplicação é idempotente, e
    se o recompute dependesse de haver colapso novo ele nunca repararia o que uma rodada
    anterior deixou torto. É idempotente também (dois UPDATEs que descrevem o estado final,
    não um delta) e CIRÚRGICO — só os alvos, nunca o reset global que o publish faz.
    """
    if not alvos:
        return []
    T_EGP, T_IN = f"{fq}.sas_egp_inputs", f"{fq}.sas_inputs_monitor"
    lit = lambda v: "'" + str(v).replace("'", "''") + "'"
    inl = ", ".join(lit(t) for t in sorted(set(alvos)))
    return [
        f"UPDATE {T_IN} SET escopo_indi = false WHERE chave_canonica IN ({inl})",
        f"UPDATE {T_IN} SET escopo_indi = true WHERE chave_canonica IN ({inl}) "
        f"AND chave_canonica IN (SELECT DISTINCT chave_canonica FROM {T_EGP} "
        f"WHERE escopo_indi = true)",
    ]


def _le_mapa_e_monitor(read_rows, fq):
    mapa = read_rows(f"SELECT chave_canonica, chave_canonica_alvo FROM {fq}.{TABELA_MAPA} "
                     f"WHERE eh_canonico = 'false' AND ativo = 'true'")
    alias = {}
    for l in mapa:
        k, v = (l["chave_canonica"], l["chave_canonica_alvo"]) if isinstance(l, dict) else (l[0], l[1])
        if k and v:
            alias[k] = v
    linhas = read_rows(f"SELECT chave_canonica, etapa, status, responsavel, observacao "
                       f"FROM {fq}.sas_inputs_monitor WHERE NOT orfao")
    COLS = ("chave_canonica", "etapa", "status", "responsavel", "observacao")
    monitor = {}
    for l in linhas:
        d = l if isinstance(l, dict) else dict(zip(COLS, list(l) + [None] * len(COLS)))
        if d.get("chave_canonica"):
            monitor[d["chave_canonica"]] = d
    return alias, monitor


def reaplica(run, read_rows, fq, *, aplicar=True, descartar_estado=False):
    """Executa (ou só planeja) a reaplicação. Devolve (aceitos, recusas).

    Mapa ausente -> no-op silencioso: o schema não tem decisão de identidade registrada."""
    try:
        alias, monitor = _le_mapa_e_monitor(read_rows, fq)
    except Exception as e:
        print(f"  identidade: {TABELA_MAPA} ausente ({type(e).__name__}); nada a reaplicar.")
        return {}, []
    aceitos, recusas = plano(alias, monitor, descartar_estado)
    if aplicar:
        for st in sqls(aceitos, fq):
            run(st)
        # sempre, mesmo sem colapso novo — ver `sqls_flags`
        for st in sqls_flags(set(alias.values()), fq):
            run(st)
    return aceitos, recusas


def relata(aceitos, recusas, aplicado):
    verbo = "reaplicado(s)" if aplicado else "a reaplicar"
    out = [f"  identidade: {len(aceitos)} colapso(s) {verbo}."]
    if recusas:
        out.append(f"  RECUSADOS {len(recusas)} — nao foram tocados:")
        for alias, alvo, motivo in recusas[:12]:
            out.append(f"     {alias} -> {alvo}: {motivo}")
        if len(recusas) > 12:
            out.append(f"     … e mais {len(recusas) - 12}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "bv"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    ap.add_argument("--aplica", action="store_true", help="sem isto, so mostra o plano")
    ap.add_argument("--descartar-estado", action="store_true",
                    help="aceita colapsar alias COM trabalho humano gravado (descarta)")
    a = ap.parse_args()
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=a.profile)

    def _exec(sql):
        return w.statement_execution.execute_statement(
            statement=sql, warehouse_id=a.warehouse_id, wait_timeout="50s")

    def read_rows(sql):
        r = _exec(sql)
        cols = [c.name for c in (r.manifest.schema.columns or [])]
        return [dict(zip(cols, row)) for row in (r.result.data_array or [])] if r.result else []

    fq = f"{a.catalog}.{a.schema}"
    print(f"=== reaplicacao de identidade — {fq}{'' if a.aplica else '  (DRY-RUN)'}")
    aceitos, recusas = reaplica(_exec, read_rows, fq, aplicar=a.aplica,
                                descartar_estado=a.descartar_estado)
    for l in relata(aceitos, recusas, a.aplica):
        print(l)
    return 1 if recusas else 0


if __name__ == "__main__":
    sys.exit(main())

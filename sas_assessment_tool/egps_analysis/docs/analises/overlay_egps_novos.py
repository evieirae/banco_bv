#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overlay INSERT-only de EGPs NOVOS para o app monitoramento-sas.

POR QUE EXISTE
O publish completo reconstrói todas as tabelas do pipeline a partir dos CSVs locais e,
com isso, reverte os patches que hoje só existem em prod (rename cpf_contrato, lote
Sanitizar/Desvincular, duplicatas removidas à mão, overlay do %DESCOMPACTA). Para subir
1..N EGPs novos não vale pagar esse preço. Este script copia APENAS as linhas dos
projetos da whitelist de um schema de STAGING (onde o publish rodou completo, sobre uma
worktree isolada) para o schema alvo. Toda inserção é guardada por NOT EXISTS: nenhuma
linha fora da whitelist é lida, alterada ou apagada.

ROTA COMPLETA
  1. worktree isolada:  egps_extractor.py <pasta_stage>  &&  orchestrator_inventory.py
  2. staging:           publish_to_databricks.py --apply --schema <STG> --profile bv
  3. dry-run:           overlay_egps_novos.py --staging <STG> --projetos-file wl.txt
  4. aplica em prod:    ... --apply --schema monitoramento_sas --prod-confirm

O QUE ELE TOCA (nada fora disto)
  INSERT-only, filtrado por projeto:
    sas_lineage_nodes · sas_egp_inputs · sas_egp_outputs · sas_resumo_proj
    sas_lineage_edges  (aresta com ponta na whitelist)
    sas_inputs_monitor · sas_outputs_monitor  (só chave_canonica AINDA INEXISTENTE no alvo)
  INSERT direto (não vem do staging, porque publish só semeia escopo se a tabela estiver vazia):
    sas_escopo  (ativo=true, origem=<--origem>)
  UPDATE escopado à whitelist:
    escopo_indi=true em nodes/egp_inputs/egp_outputs — SÓ para projeto que já tem linha
    ativa em sas_escopo. O overlay não muda a pertinência ao escopo de ninguém.
    qtd_projetos recalculado em sas_inputs_monitor, só nas chaves que o overlay toca.
  --substitui <projeto>  DELETE+INSERT das linhas por-projeto de UM projeto que já existe
    no alvo (caso de versão nova com o MESMO nome). Só age nos nomes passados explicitamente.
  --desativa <projeto>   UPDATE sas_escopo SET ativo=false (troca de versão: aposenta o
    antecessor). Reversível; o histórico da linha continua na tabela.
  --sem-escopo           não insere em sas_escopo: o EGP entra como nó do corpus (visível,
    conta como dependência/consumidor no grafo) mas fora do escopo de migração.

O QUE ELE NÃO FAZ
  Não recalcula sas_resumo_inputs, sas_funil_area nem area_principal (agregados por área).
  Eles ficam defasados pelo número de EGPs do overlay até o próximo publish completo.
  Não cria linha em sas_egp_pipeline: o funil de cada EGP novo é preenchido pela Gestão no app.

DÍVIDA QUE O OVERLAY CRIA
Prod passa a ter linhas que os CSVs locais não têm. Para o próximo publish completo não
perder os EGPs novos, os .egp precisam estar em received_egps/<Área>/ e os .txt
correspondentes commitados em text_egps/ (que é versionado).
"""
import argparse
import os
import sys
import time
import uuid

_HERE_PUB = os.path.dirname(os.path.abspath(__file__))
_EGPS_PUB = os.path.dirname(os.path.dirname(_HERE_PUB))
if _EGPS_PUB not in sys.path:
    sys.path.insert(0, _EGPS_PUB)
import publish_to_databricks as _pub                       # noqa: E402
WAREHOUSE = os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID", "5922c26f81f1bbdd")
PROD_SCHEMA = "monitoramento_sas"

# (tabela, coluna(s) de identidade, predicado de recorte pela whitelist)
# O SELECT é sempre `SELECT <cols> FROM staging` para casar a ordem de colunas do alvo.
POR_PROJETO = [
    ("sas_lineage_nodes", ["projeto"], "projeto IN {wl}"),
    ("sas_egp_inputs", ["projeto", "chave_canonica"], "projeto IN {wl}"),
    ("sas_egp_outputs", ["projeto", "chave_canonica"], "projeto IN {wl}"),
    ("sas_resumo_proj", ["projeto", "chave_canonica"], "projeto IN {wl}"),
    ("sas_lineage_edges", ["projeto_alvo", "depende_do"],
     "(projeto_alvo IN {wl} OR depende_do IN {wl})"),
]
# tabelas de grão GLOBAL (input/output distinto): insere só a chave inexistente no alvo
POR_CHAVE = [
    ("sas_inputs_monitor", "sas_egp_inputs"),
    ("sas_outputs_monitor", "sas_egp_outputs"),
]
ESCOPO_INDI = ["sas_lineage_nodes", "sas_egp_inputs", "sas_egp_outputs"]


# Helper CANÔNICO (publish_to_databricks.sql_lit), não uma cópia local: ele escapa a
# contrabarra ANTES da aspa. As cópias locais só escapavam a aspa, e este corpus é
# cheio de caminho UNC/Windows (`N:\`, `\\bvnet\global\...`) que chega ao SQL via
# `observacao`/`comentario` escritos por analista. Em Spark SQL a `\` é escape dentro
# do literal: valor terminado em `\` escapa a aspa de fechamento e quebra (ou desloca)
# o statement; `\g` & cia corrompem o texto gravado em silêncio.
def q(s: str) -> str:
    return _pub.sql_lit(s)


def lista(nomes) -> str:
    return "(" + ", ".join(q(n) for n in nomes) + ")"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default="monitoramento_sas_dev",
                    help="alvo (default sandbox); monitoramento_sas exige --prod-confirm")
    ap.add_argument("--staging", required=True, help="schema onde o publish completo rodou")
    ap.add_argument("--projetos-file", required=True,
                    help="whitelist: 1 nome de projeto por linha (como aparece em sas_lineage_nodes)")
    ap.add_argument("--substitui", action="append", default=[],
                    help="projeto que JÁ existe no alvo e deve ser substituído (DELETE+INSERT)")
    ap.add_argument("--desativa", action="append", default=[],
                    help="antecessor a aposentar: sas_escopo SET ativo=false")
    ap.add_argument("--sem-escopo", action="store_true",
                    help="não insere linha em sas_escopo: os EGPs entram como nó do corpus "
                         "(visíveis, contam como dependência/consumidor) mas FORA do escopo "
                         "de migração. Quem já tinha linha ativa continua no escopo.")
    ap.add_argument("--origem", default=None, help="valor de sas_escopo.origem (default overlay_<data>)")
    ap.add_argument("--ator", default=os.environ.get("USER", "overlay"))
    ap.add_argument("--apply", action="store_true", help="escreve (default: dry-run)")
    ap.add_argument("--prod-confirm", action="store_true")
    ap.add_argument("--warehouse-id", default=WAREHOUSE)
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "bv"))
    args = ap.parse_args()

    if args.schema == PROD_SCHEMA and args.apply and not args.prod_confirm:
        ap.error(f"--apply contra PROD ({args.catalog}.{args.schema}) requer --prod-confirm")

    wl = [ln.strip() for ln in open(args.projetos_file, encoding="utf-8") if ln.strip()]
    if not wl:
        ap.error("whitelist vazia")
    for p in args.substitui + args.desativa:
        if p in args.desativa and p in wl:
            ap.error(f"'{p}' está na whitelist e em --desativa ao mesmo tempo")
    faltando = [p for p in args.substitui if p not in wl]
    if faltando:
        ap.error(f"--substitui fora da whitelist: {faltando}")

    tgt = f"{args.catalog}.{args.schema}"
    stg = f"{args.catalog}.{args.staging}"
    hoje = time.strftime("%Y-%m-%d")
    origem = args.origem or f"overlay_{hoje}"
    WL, SUB = lista(wl), lista(args.substitui)

    print("== OVERLAY EGPs NOVOS ==")
    print(f"  staging : {stg}")
    print(f"  alvo    : {tgt}{'   ⚠️ PRODUÇÃO' if args.schema == PROD_SCHEMA else ''}")
    print(f"  apply   : {args.apply}")
    print(f"  projetos: {len(wl)}")
    for p in wl:
        marca = "  [SUBSTITUI]" if p in args.substitui else ""
        print(f"     - {p}{marca}")
    if args.desativa:
        print(f"  desativa no escopo: {args.desativa}")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState
    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()

    def run(sql, escreve=False):
        if escreve and not args.apply:
            print(f"  [dry-run] {sql[:220]}{' ...' if len(sql) > 220 else ''}")
            return None
        r = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id, wait_timeout="50s")
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            print(f"\n!! FALHA: {r.status.error}\n   SQL: {sql[:400]}")
            sys.exit(1)
        return r

    def um(sql):
        r = run(sql)
        da = r.result.data_array if r and r.result else None
        return int(da[0][0]) if da else 0

    def _cols(schema, tabela):
        r = run(f"SELECT column_name FROM {args.catalog}.information_schema.columns "
                f"WHERE table_schema = {q(schema)} AND table_name = {q(tabela)} "
                f"ORDER BY ordinal_position")
        return [row[0] for row in (r.result.data_array or [])]

    def cols(tabela):
        """Colunas comuns a staging e alvo, na ordem do alvo. Os schemas divergem quando um
        ALTER foi aplicado só em prod (ex.: loc/code_tasks_count em 29/08) ou quando a
        worktree do staging está num commit anterior. Coluna que só existe no alvo fica
        NULL para os projetos do overlay — o próximo publish completo a preenche."""
        tg, st = _cols(args.schema, tabela), set(_cols(args.staging, tabela))
        comuns = [c for c in tg if c in st]
        so_alvo = [c for c in tg if c not in st]
        if so_alvo:
            print(f"     ({tabela}: só no alvo, entra NULL -> {', '.join(so_alvo)})")
        return comuns

    # ---------- 0. checagem prévia: staging tem os projetos? alvo já tem? ----------
    print("\n-- pré-checagem")
    n_stg = um(f"SELECT count(*) FROM {stg}.sas_lineage_nodes WHERE projeto IN {WL}")
    if n_stg != len(wl):
        print(f"!! staging tem {n_stg}/{len(wl)} projetos em sas_lineage_nodes. Rode o publish "
              f"no staging antes, ou confira os nomes.")
        sys.exit(1)
    r = run(f"SELECT projeto FROM {tgt}.sas_lineage_nodes WHERE projeto IN {WL}")
    ja = [row[0] for row in (r.result.data_array or [])]
    inesperados = [p for p in ja if p not in args.substitui]
    if inesperados:
        print(f"!! já existem no alvo e NÃO estão em --substitui: {inesperados}")
        print("   passe --substitui <projeto> para trocar as linhas, ou remova-o da whitelist.")
        sys.exit(1)
    print(f"  staging ok ({n_stg} projetos) · já no alvo: {ja or 'nenhum'}")

    # ---------- 1. substituição: apaga as linhas por-projeto dos nomes listados ----------
    if args.substitui:
        print(f"\n-- substituição ({len(args.substitui)} projeto(s))")
        for tabela, _ident, pred in POR_PROJETO:
            campo = "projeto_alvo" if tabela == "sas_lineage_edges" else "projeto"
            n = um(f"SELECT count(*) FROM {tgt}.{tabela} WHERE {campo} IN {SUB}")
            print(f"  {tabela}: apaga {n} linha(s)")
            run(f"DELETE FROM {tgt}.{tabela} WHERE {campo} IN {SUB}", escreve=True)

    # ---------- 2. tabelas por projeto ----------
    print("\n-- INSERT por projeto")
    for tabela, ident, pred in POR_PROJETO:
        c = cols(tabela)
        cs = ", ".join(c)
        on = " AND ".join(f"t.{k} = s.{k}" for k in ident)
        onde = pred.format(wl=WL)
        sel = (f"SELECT {cs} FROM {stg}.{tabela} s WHERE {onde} "
               f"AND NOT EXISTS (SELECT 1 FROM {tgt}.{tabela} t WHERE {on})")
        n = um(f"SELECT count(*) FROM ({sel})")
        print(f"  {tabela}: +{n}")
        if n:
            run(f"INSERT INTO {tgt}.{tabela} ({cs}) {sel}", escreve=True)

    # ---------- 3. tabelas de grão global (só chaves novas) ----------
    print("\n-- INSERT de chaves novas (grão global)")
    for tabela, fonte in POR_CHAVE:
        c = cols(tabela)
        cs = ", ".join(c)
        chaves = (f"SELECT DISTINCT chave_canonica FROM {stg}.{fonte} WHERE projeto IN {WL}")
        sel = (f"SELECT {cs} FROM {stg}.{tabela} s "
               f"WHERE s.chave_canonica IN ({chaves}) "
               f"AND NOT EXISTS (SELECT 1 FROM {tgt}.{tabela} t "
               f"WHERE t.chave_canonica = s.chave_canonica)")
        n = um(f"SELECT count(*) FROM ({sel})")
        tot = um(f"SELECT count(*) FROM ({chaves})")
        print(f"  {tabela}: +{n} nova(s) de {tot} referenciada(s) "
              f"({tot - n} já existiam no alvo)")
        if n:
            run(f"INSERT INTO {tgt}.{tabela} ({cs}) {sel}", escreve=True)

    # ---------- 4. escopo ----------
    # Regra: o overlay NUNCA muda a pertinência ao escopo de ninguém. Ele só CORRIGE o
    # escopo_indi dos projetos que JÁ tinham linha ativa em sas_escopo no alvo — o staging
    # não conhece essas edições e traria escopo_indi=false, tirando do escopo um EGP que
    # está nele (regressão silenciosa no caso --substitui).
    print("\n-- sas_escopo")
    r = run(f"SELECT projeto, ativo FROM {tgt}.sas_escopo WHERE projeto IN {WL}")
    esc_alvo = {row[0]: row[1] for row in (r.result.data_array or [])}
    ja_no_escopo = [p for p, ativo in esc_alvo.items() if str(ativo).lower() != "false"]
    if args.sem_escopo:
        print(f"  --sem-escopo: nenhuma linha inserida. Os {len(wl) - len(esc_alvo)} EGP(s) "
              f"sem linha entram no app como nó do corpus, FORA do escopo.")
    else:
        r = run(f"SELECT projeto, area FROM {stg}.sas_lineage_nodes WHERE projeto IN {WL}")
        areas = {row[0]: row[1] for row in (r.result.data_array or [])}
        novos_esc = [p for p in wl if p not in esc_alvo]
        print(f"  +{len(novos_esc)} linha(s) (ativo=true, origem={origem}); "
              f"{len(esc_alvo)} já tinha(m) linha e é(são) preservada(s)")
        if novos_esc:
            vals = ", ".join(
                f"({q(uuid.uuid4().hex)}, {q(p.split('__')[-1])}, {q(areas.get(p) or '')}, "
                f"'exato', {q(p)}, {q(origem)}, {q(args.ator)}, {q(hoje)}, true)"
                for p in novos_esc)
            run(f"INSERT INTO {tgt}.sas_escopo (id, egp_dor1, area, status_extracao, projeto, "
                f"origem, created_by, created_at, ativo) VALUES {vals}", escreve=True)
            # Só os recém-inseridos (ativo=true) entram; NÃO `list(wl)`. A whitelist
            # inteira inclui quem já tinha linha com ativo=false — um EGP despriorizado
            # de propósito. Atribuir escopo_indi=true a ele logo abaixo o devolvia
            # calado às contagens de escopo, violando a regra declarada no topo deste
            # bloco e em :28 ("o overlay NUNCA muda a pertinência ao escopo de ninguém").
            # Caso real de disparo: --substitui de uma versão nova cujo antecessor
            # tinha sido desativado.
            ja_no_escopo = ja_no_escopo + novos_esc

    if ja_no_escopo:
        ESC = lista(ja_no_escopo)
        print(f"  escopo_indi=true preservado em: {', '.join(ja_no_escopo)}")
        for tabela in ESCOPO_INDI:
            run(f"UPDATE {tgt}.{tabela} SET escopo_indi = true WHERE projeto IN {ESC}",
                escreve=True)
    else:
        print("  escopo_indi: nenhum projeto do overlay está no escopo — fica false")

    # ---------- 4b. agregados por chave referenciada ----------
    # qtd_projetos de um input já existente passa a estar defasado em -1 quando um EGP novo
    # o referencia. Vale para EGP fora do escopo também: a coluna conta PROJETOS, não escopo.
    # Recalcula do zero A PARTIR de sas_egp_inputs, restrito às chaves que os projetos do
    # overlay tocam — nenhuma outra linha do monitor entra no MERGE.
    print("\n-- agregados das chaves referenciadas")
    ch_in = f"SELECT DISTINCT chave_canonica FROM {stg}.sas_egp_inputs WHERE projeto IN {WL}"
    n_ch = um(f"SELECT count(*) FROM ({ch_in})")
    print(f"  qtd_projetos recalculado em {n_ch} chave(s) de sas_inputs_monitor")
    run(f"""MERGE INTO {tgt}.sas_inputs_monitor t
USING (
  SELECT chave_canonica, count(DISTINCT projeto) AS n
  FROM {tgt}.sas_egp_inputs
  WHERE chave_canonica IN ({ch_in})
  GROUP BY chave_canonica
) s ON t.chave_canonica = s.chave_canonica
WHEN MATCHED THEN UPDATE SET t.qtd_projetos = s.n""", escreve=True)
    # escopo_indi do input só vira true se quem o referencia está no escopo
    if ja_no_escopo:
        ch_esc = (f"SELECT DISTINCT chave_canonica FROM {stg}.sas_egp_inputs "
                  f"WHERE projeto IN {lista(ja_no_escopo)}")
        n_e = um(f"SELECT count(*) FROM {tgt}.sas_inputs_monitor "
                 f"WHERE escopo_indi IS NOT true AND chave_canonica IN ({ch_esc})")
        print(f"  escopo_indi=true em {n_e} chave(s) de EGP do escopo")
        if n_e:
            run(f"UPDATE {tgt}.sas_inputs_monitor SET escopo_indi = true "
                f"WHERE escopo_indi IS NOT true AND chave_canonica IN ({ch_esc})",
                escreve=True)
    else:
        print("  escopo_indi das chaves: intocado (nenhum EGP do overlay no escopo)")

    # ---------- 5. aposenta antecessores ----------
    if args.desativa:
        print("\n-- aposenta antecessor(es) no escopo")
        DES = lista(args.desativa)
        r = run(f"SELECT projeto, ativo FROM {tgt}.sas_escopo WHERE projeto IN {DES}")
        for row in (r.result.data_array or []):
            print(f"  {row[0]}: ativo {row[1]} -> false")
        run(f"UPDATE {tgt}.sas_escopo SET ativo = false WHERE projeto IN {DES}", escreve=True)
        vals = ", ".join(
            f"({q(uuid.uuid4().hex)}, 'desativa_overlay', {q(p.split('__')[-1])}, {q(p)}, "
            f"{q(args.ator)}, {q(hoje)})" for p in args.desativa)
        run(f"INSERT INTO {tgt}.sas_escopo_audit (id, acao, egp_dor1, projeto, ator, ts) "
            f"VALUES {vals}", escreve=True)

    print("\n== FIM ==" + ("" if args.apply else "  (dry-run: nada foi escrito)"))
    print("Agregados NÃO recalculados por este script: sas_resumo_inputs, sas_funil_area, "
          "area_principal. Ficam defasados até o próximo publish completo.")


if __name__ == "__main__":
    main()

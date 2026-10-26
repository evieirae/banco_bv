#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OBSOLETO: o renome e o corte dos outputs BASE_3040 vêm de `src/egps_decisoes.csv`, que o
orquestrador e o publish aplicam na leitura do corpus. Depois de um publish com o arquivo,
`Cobranças__CPF_Contrato` não existe mais nas tabelas derivadas, e a guarda abaixo aborta
este script ("Não há o que renomear") sem escrever nada. Fica no repo como registro.

Manutenção recorrente prevista no AVISO CRÍTICO de rename_cpf_contrato_v1_para_v2.py
(rodado em 2026-08-24): as 5 tabelas *full-replace* (sas_lineage_nodes, sas_lineage_edges,
sas_egp_inputs, sas_egp_outputs, sas_resumo_proj) são regeradas por MERGE a cada
Processar/publish a partir da extração dos `.egp`. O `.egp` original pequeno do
`Cobranças__CPF_Contrato__v2` (descartado por decisão de negócio — ver D013 em
RELATORIO_VERSOES_EGPS_2026-08-13.md) continua existindo na base de extração, então
cada publish volta a: (a) sobrescrever a chave `__v2` com os dados do projeto PEQUENO
descartado (não com os dados do v1 grande renomeado), e (b) reintroduzir
`Cobranças__CPF_Contrato` (sem sufixo) com os dados do v1 grande, órfão das tabelas
overlay (sas_egp_pipeline/sas_escopo/sas_gestao_*), que continuam corretas em `__v2`.
Confirmado por leitura direta em 2026-08-31 (prod E dev): `sas_lineage_nodes` mostra
as DUAS chaves, com `__v2` no perfil pequeno (106 loc/3 tasks) e a chave sem sufixo
no perfil grande (1114 loc/13 tasks) — o inverso do que devia aparecer no app.

Este script SÓ toca nas 5 tabelas derivadas (full-replace). NÃO toca em nenhuma tabela
overlay (sas_egp_pipeline, sas_escopo, sas_gestao_status, sas_gestao_datas,
sas_output_producer_choice, sas_egp_input_link*) — essas já estão corretas hoje (só
`__v2`) e acumularam histórico legítimo desde 24/08 que NÃO pode ser apagado
(diferente do primeiro rename, que apagava o `__v2` original porque ele era de fato
descartável). Repetir o DELETE-tudo-de-`__v2` do script original aqui destruiria esse
histórico — por isso este é um script novo e mais restrito, não uma repetição do
`rename_cpf_contrato_v1_para_v2.py`.

Para cada uma das 5 tabelas, na ordem (a ordem importa: delete antes do rename):
  1. DELETE das linhas com a chave NEW_KEY (dado do v2 pequeno descartado, regerado
     pelo publish mais recente).
  2. UPDATE renomeando OLD_KEY -> NEW_KEY (migra o dado FRESCO do v1 grande,
     regerado pelo publish, para a identidade correta).
  3. Reaplica o trim de escopo do rename original: escopo_indi=false nos 4 outputs
     CARNEIRO.BASE_3040_* (perdido no MERGE, porque a extração não sabe dessa decisão
     de negócio).
  4. Religa escopo_indi=true no EGP renomeado. O rename traz a flag JUNTO com a linha,
     e a chave sem sufixo está com escopo_indi=false (o recompute_escopo do publish só
     liga a flag para projetos presentes no sas_escopo, e lá consta só a `__v2`). Sem
     este passo o EGP fica ATIVO no sas_escopo e FORA do grafo, o que separa por 1 as
     duas contagens da aba Resumo — o card conta pelo sas_escopo e o funil pelo grafo.
     Visto em dev 14/09/2026 e em prod 18/09/2026 (195 vs 194).
  5. Uma linha de auditoria em sas_pipeline_audit documentando a reaplicação.

Rode sempre primeiro em dry-run, depois --apply no sandbox (_dev), confira na tela do
app, e só então repita com --prod-confirm contra produção — mesmo padrão dos demais
scripts desta pasta.

Uso:
  cd egps_analysis
  python docs/analises/reaplica_rename_cpf_contrato_pos_publish.py \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                              # dry-run
  python docs/analises/reaplica_rename_cpf_contrato_pos_publish.py --apply \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                              # dev
  python docs/analises/reaplica_rename_cpf_contrato_pos_publish.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd    # PROD
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
PROD_SCHEMA = "monitoramento_sas"
OLD_KEY = "Cobranças__CPF_Contrato"
NEW_KEY = "Cobranças__CPF_Contrato__v2"


# Helper CANÔNICO (publish_to_databricks.sql_lit), não uma cópia local: ele escapa a
# contrabarra ANTES da aspa. As cópias locais só escapavam a aspa, e este corpus é
# cheio de caminho UNC/Windows (`N:\`, `\\bvnet\global\...`) que chega ao SQL via
# `observacao`/`comentario` escritos por analista. Em Spark SQL a `\` é escape dentro
# do literal: valor terminado em `\` escapa a aspa de fechamento e quebra (ou desloca)
# o statement; `\g` & cia corrompem o texto gravado em silêncio.
lit = _pub.sql_lit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                     help="conecta e escreve no Databricks (default: dry-run, só mostra o que faria)")
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas_dev"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
                     help="perfil do ~/.databrickscfg (OAuth/U2M)")
    ap.add_argument("--prod-confirm", action="store_true",
                     help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    ap.add_argument("--actor", default=os.environ.get("USER", "reaplica_rename_cpf_contrato_script"),
                     help="valor gravado como ator na linha de auditoria criada")
    args = ap.parse_args()

    if args.apply and args.schema == PROD_SCHEMA and not args.prod_confirm:
        ap.error(f"--apply contra PROD ('{args.catalog}.{args.schema}') requer --prod-confirm. "
                 f"Sem ele, use o sandbox (default --schema monitoramento_sas_dev).")
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_DEFAULT_WAREHOUSE_ID")

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
    except ImportError:
        print("ERRO: databricks-sdk não instalado no venv ativo.", file=sys.stderr)
        sys.exit(1)

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"

    def run(sql):
        if not args.apply:
            print(f"[dry-run] {sql}")
            return
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id,
            wait_timeout="50s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            print(f"FALHOU: {sql}\n  -> {resp.status}", file=sys.stderr)
            sys.exit(1)

    target = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"{'--apply' if args.apply else 'dry-run'} contra {fq}  [{target}]")
    print(f"reaplica pós-publish: apaga '{NEW_KEY}' (dado stale do v2 pequeno descartado, "
          f"regerado pelo MERGE) e renomeia '{OLD_KEY}' -> '{NEW_KEY}' (dado fresco do v1) "
          f"nas 5 tabelas derivadas. NÃO toca em overlay.")

    def conta_derivadas(chave):
        """Linhas da chave nas tabelas derivadas. Lê SEMPRE (inclusive em dry-run):
        o guard precisa do estado real, e ler não muda nada."""
        sql = (
            f"SELECT "
            f"(SELECT count(*) FROM {fq}.sas_lineage_nodes WHERE projeto = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_egp_inputs WHERE projeto = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_egp_outputs WHERE projeto = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_resumo_proj WHERE projeto = {lit(chave)})"
        )
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id,
            wait_timeout="50s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            print(f"FALHOU (guard): {sql}\n  -> {resp.status}", file=sys.stderr)
            sys.exit(1)
        da = resp.result.data_array if resp.result else None
        return int(da[0][0]) if da and da[0] and da[0][0] is not None else 0

    # --- GUARD DE REEXECUÇÃO ----------------------------------------------------------
    # A sequência é DELETE(NEW) + UPDATE(OLD -> NEW), correta UMA vez por publish.
    # Rodando de novo SEM um publish no meio, OLD_KEY já não existe (virou NEW no run
    # anterior): o DELETE apaga o dado VIVO recém-renomeado e o UPDATE não acha nada
    # para repor — o EGP some das 5 tabelas derivadas até alguém rodar um publish
    # completo. Este script foi feito para ser chamado à mão depois de cada publish,
    # então "rodei duas vezes" é o erro ESPERADO, não o exótico.
    n_old = conta_derivadas(OLD_KEY)
    n_new = conta_derivadas(NEW_KEY)
    print(f"   guard: derivadas de '{OLD_KEY}' = {n_old} linha(s); "
          f"'{NEW_KEY}' = {n_new} linha(s)")
    if n_old == 0:
        print(
            f"\nABORTADO: '{OLD_KEY}' não tem linha nas tabelas derivadas de {fq}.\n"
            f"Não há o que renomear — e seguir apagaria as {n_new} linha(s) de "
            f"'{NEW_KEY}', que neste estado é o dado VIVO do EGP.\n"
            f"Rode o publish/Processar primeiro (ele regenera '{OLD_KEY}') e só então "
            f"reaplique este script.",
            file=sys.stderr)
        sys.exit(2)

    derived_tables = [
        ("sas_lineage_nodes", "projeto", "projeto"),
        ("sas_egp_inputs", "projeto", "projeto"),
        ("sas_egp_outputs", "projeto", "projeto"),
        ("sas_resumo_proj", "projeto", "projeto"),
    ]
    for table, del_col, ren_col in derived_tables:
        run(f"DELETE FROM {fq}.{table} WHERE {del_col} = {lit(NEW_KEY)}")
        run(f"UPDATE {fq}.{table} SET {ren_col} = {lit(NEW_KEY)} WHERE {ren_col} = {lit(OLD_KEY)}")

    # sas_lineage_edges tem duas colunas de chave (projeto_alvo / depende_do)
    run(
        f"DELETE FROM {fq}.sas_lineage_edges "
        f"WHERE projeto_alvo = {lit(NEW_KEY)} OR depende_do = {lit(NEW_KEY)}"
    )
    run(f"UPDATE {fq}.sas_lineage_edges SET projeto_alvo = {lit(NEW_KEY)} WHERE projeto_alvo = {lit(OLD_KEY)}")
    run(f"UPDATE {fq}.sas_lineage_edges SET depende_do = {lit(NEW_KEY)} WHERE depende_do = {lit(OLD_KEY)}")

    # reaplica o trim de escopo (motivo de negócio do rename original: v2 = v1 sem base 3040)
    run(
        f"UPDATE {fq}.sas_egp_outputs SET escopo_indi = false "
        f"WHERE projeto = {lit(NEW_KEY)} AND artifact LIKE 'CARNEIRO.BASE_3040%'"
    )

    # religa o escopo no EGP renomeado (passo 4 do cabeçalho). Espelha os UPDATEs "liga"
    # de recompute_escopo (publish_to_databricks.py + main.py), restritos a este projeto e
    # condicionados ao sas_escopo VIGENTE: se alguém desativar o EGP na tela, o script não
    # o ressuscita. Só LIGAM a flag — chave compartilhada com outro EGP em escopo já é true.
    esc = f"(SELECT projeto FROM {fq}.sas_escopo WHERE projeto <> '' AND ativo IS NOT false)"
    # ordem importa: sas_inputs_monitor lê o escopo já corrigido de sas_egp_inputs.
    run(f"UPDATE {fq}.sas_lineage_nodes SET escopo_indi = true "
        f"WHERE projeto = {lit(NEW_KEY)} AND projeto IN {esc}")
    run(f"UPDATE {fq}.sas_egp_inputs SET escopo_indi = true "
        f"WHERE projeto = {lit(NEW_KEY)} AND projeto IN {esc}")
    run(f"UPDATE {fq}.sas_inputs_monitor SET escopo_indi = true WHERE chave_canonica IN "
        f"(SELECT DISTINCT chave_canonica FROM {fq}.sas_egp_inputs "
        f"WHERE projeto = {lit(NEW_KEY)} AND escopo_indi = true)")
    run(f"UPDATE {fq}.sas_resumo_inputs SET escopo_indi = true WHERE chave_canonica IN "
        f"(SELECT DISTINCT chave_canonica FROM {fq}.sas_resumo_proj "
        f"WHERE projeto = {lit(NEW_KEY)} AND projeto IN {esc})")

    run(
        f"INSERT INTO {fq}.sas_pipeline_audit (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
        f"VALUES ({lit(uuid.uuid4().hex)}, {lit(NEW_KEY)}, 'migracao', 'rekey_pos_publish', "
        f"{lit(OLD_KEY)}, {lit(NEW_KEY)}, {lit(args.actor)}, CAST(current_timestamp() AS STRING))"
    )

    print("\nLembrete: isso vai se repetir a cada novo Processar/publish enquanto o .egp "
          "original pequeno do v2 descartado continuar na base de extração (não existe "
          "hoje mecanismo de alias persistente no pipeline — ver AVISO CRÍTICO em "
          "rename_cpf_contrato_v1_para_v2.py).")


if __name__ == "__main__":
    main()

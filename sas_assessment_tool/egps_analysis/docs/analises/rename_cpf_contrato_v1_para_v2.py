#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decidido com o usuário em 2026-08-24 (as 4 perguntas abertas do rascunho anterior
foram respondidas: rename completo incluindo tabelas derivadas, trim de escopo da
base 3040 já incluído, nota de encerramento gravada, aplicar em dev e depois prod).

Objetivo de negócio: o EGP `Cobranças__CPF_Contrato` ("v1", produtor canônico,
outputs BASE_3040_* + INFO_CONTA) foi decidido para migração, mas SEM a base 3040
(escopo reduzido). Esse escopo reduzido vai passar a se chamar "v2" no app. O EGP
`Cobranças__CPF_Contrato__v2` ORIGINAL (script pequeno, 2 outputs, produtor só de
INFO_CONTA, sem papel na linhagem — ver docs/analises/RELATORIO_VERSOES_EGPS_2026-08-13.md
caso D013, similaridade de código 0,025 com o v1: são projetos DIFERENTES) será
descartado do app.

Este script faz QUATRO coisas, NESSA ORDEM (a ordem importa: a 2ª reusa a chave da 1ª):

  1. DELETE de toda linha própria do `Cobranças__CPF_Contrato__v2` ORIGINAL nas
     tabelas onde ele aparece como dono de linha (overlay + derivadas), e grava uma
     nota de encerramento em `sas_gestao_status` fechando a dúvida "Tratar como
     intermediate CPF_Contrato INFO_CONTA — falar com Leandro" que estava aberta
     nele (perdida no DELETE se não fosse registrada à parte).
  2. UPDATE renomeando `Cobranças__CPF_Contrato` -> `Cobranças__CPF_Contrato__v2`
     em toda tabela onde a chave `projeto`/`entity_id`/`projeto_alvo`/`depende_do`/
     `projeto_escolhido` aparece (overlay + derivadas, por decisão do usuário).
  3. UPDATE em `sas_egp_outputs` marcando `escopo_indi = false` nos 4 outputs
     `CARNEIRO.BASE_3040_*` do EGP renomeado — é o próprio motivo de negócio do
     rename (v2 = v1 sem a base 3040). `INFO_CONTA` continua `escopo_indi = true`.
  4. Trilha em `sas_pipeline_audit` para a remoção, o rename e o trim de escopo.

Confirmado por investigação em prod+dev (2026-08-24) que NINGUÉM depende do `__v2`
original como produtor (`sas_lineage_edges.depende_do` não tem nenhuma linha
apontando pra ele) — não há consumidor a re-apontar, diferente do caso do Cartão
Amigável __v2 (cartao-amigavel-v2-removido, memória). Estado confirmado por leitura
direta em 2026-08-24: prod tem v1 `ativo=true`/v2 `ativo=false` em `sas_escopo`; dev
tem o INVERSO (v2 `ativo=true`) — os dois ambientes estão dessincronizados hoje,
por isso a decisão foi aplicar nos dois.

RESOLVIDO em 16/10/2026: o renome agora mora em `src/egps_decisoes.csv`, que o orquestrador
e o publish aplicam na leitura do corpus. O aviso abaixo fica como registro do porquê.

⚠️ AVISO CRÍTICO — RISCO DE RE-KEY NO REPUBLISH (não resolvido por este script):
`sas_lineage_nodes`, `sas_lineage_edges`, `sas_egp_inputs`, `sas_egp_outputs`,
`sas_resumo_proj` são tabelas *full-replace*, regeradas por
`app/pipeline/publish_to_databricks.py` a partir da extração do `.egp` (o nome
"CPF_Contrato" vem do cabeçalho PROJECT do arquivo fonte — não existe hoje
mecanismo de alias/rename lido pelo orchestrator). Ou seja: este UPDATE renomeia
o que está HOJE no banco, mas o próximo `Processar`/publish vai regerar essas 5
tabelas com o nome original "Cobranças__CPF_Contrato" de novo, órfão das linhas
overlay (`sas_egp_pipeline`, `sas_escopo`, `sas_gestao_*`, `sas_output_producer_choice`)
que ficaram com a chave nova. Não existe hoje (2026-08-24) um jeito de fazer esse
rename sobreviver a um republish sem repetir este patch depois de cada
`Processar`/publish — igual ao padrão já aceito em Sanitizar/Desvincular
(memória sanitizar-desvincular-lote-prod). Decidir com o usuário antes de aplicar:
(a) aceitar reaplicar depois de cada publish, (b) construir um mecanismo de alias
persistente (novo — não existe), ou (c) não tocar nas 5 tabelas derivadas e
renomear só as overlay (o app mostraria o nome errado no grafo/EGPs até o
próximo publish, mas a Gestão/Pipeline mostraria "v2").

NÃO toca:
  - `sas_priorizacao_snapshot` (payload JSON com 3 menções a "Cobranças__CPF_Contrato"
    em prod, de meses já congelados) — editar string dentro de JSON é mais arriscado;
    decidir manualmente se vale a pena (ver relatório).
  - `sas_escopo.egp_dor1` do v1 (hoje "cpf_contrato", minúsculo, sem sufixo) — é o
    identificador do inventário corporativo (DOR1); renomear quebraria o match
    contra `inventario_transacional.csv`. Deixado como está de propósito.
  - `sas_inputs_monitor` / `sas_outputs_monitor` / `sas_pipeline_metrics` — agregados
    por chave_canonica/área, não guardam `projeto` individual.

Uso (mesmo padrão dos demais scripts de docs/analises/):
  cd egps_analysis
  python docs/analises/rename_cpf_contrato_v1_para_v2.py \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                 # dry-run (default)
  python docs/analises/rename_cpf_contrato_v1_para_v2.py --apply \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                 # aplica no sandbox _dev
  python docs/analises/rename_cpf_contrato_v1_para_v2.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd   # PROD

Rode sempre primeiro em dry-run, depois --apply no sandbox (_dev), confira na tela do
app, e só então repita com --prod-confirm contra produção.
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
NEW_KEY = "Cobranças__CPF_Contrato__v2"  # == chave do __v2 original, que é apagado antes


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
    ap.add_argument("--skip-derived", action="store_true",
                     help="não tocar em sas_lineage_nodes/edges, sas_egp_inputs/outputs, "
                          "sas_resumo_proj (evita o risco de re-key no republish; só reflete "
                          "a nova chave nas tabelas 'overlay' de gestão/pipeline)")
    ap.add_argument("--skip-delete", action="store_true",
                     help="pula o bloco 1 (DELETE do __v2 original) e só executa o rename. "
                          "É o modo correto para RE-APLICAR o rename depois de um republish: "
                          "repetir o DELETE apagaria o EGP vivo (ver guard de reexecução).")
    ap.add_argument("--forca-delete-perigoso", action="store_true",
                     help="ignora o guard de reexecução e apaga NEW_KEY mesmo assim. "
                          "Só use se souber que NEW_KEY ainda é o __v2 ORIGINAL descartável.")
    ap.add_argument("--actor", default=os.environ.get("USER", "rename_cpf_contrato_script"),
                     help="valor gravado como ator/updated_by/autor nas linhas de auditoria criadas")
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

    def conta(chave):
        """Nº de linhas de overlay humano da chave. Lê SEMPRE (inclusive em dry-run):
        o guard precisa do estado real para decidir, e ler não muda nada."""
        sql = (
            f"SELECT "
            f"(SELECT count(*) FROM {fq}.sas_egp_pipeline WHERE projeto = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_escopo WHERE projeto = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_gestao_status WHERE entity = 'egp' AND entity_id = {lit(chave)}) + "
            f"(SELECT count(*) FROM {fq}.sas_egp_input_link WHERE projeto = {lit(chave)})"
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

    target = "PRODUÇÃO ⚠️" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"{'--apply' if args.apply else 'dry-run'} contra {fq}  [{target}]")

    # --- GUARD DE REEXECUÇÃO (o bloco 1 é irreversível) -------------------------------
    # O DELETE mira NEW_KEY. ANTES do rename, NEW_KEY é o __v2 ORIGINAL (descartável);
    # DEPOIS do rename (bloco 2), NEW_KEY passa a ser o EGP VIVO. Rodar de novo apagaria
    # funil, escopo, gestão, links e o AUDIT TRAIL do EGP recém-renomeado — nada disso é
    # recriado pelo publish (backup_overlays_prod.py: "perda aqui é irrecuperável").
    # Sinal: se OLD_KEY não tem mais linha de overlay, o rename já rodou.
    faz_delete = not args.skip_delete
    if faz_delete:
        n_old, n_new = conta(OLD_KEY), conta(NEW_KEY)
        print(f"   guard: overlay de '{OLD_KEY}' = {n_old} linha(s); "
              f"'{NEW_KEY}' = {n_new} linha(s)")
        if n_old == 0 and n_new > 0:
            if args.forca_delete_perigoso:
                print("   ⚠️  guard IGNORADO por --forca-delete-perigoso", file=sys.stderr)
            else:
                print(
                    f"\nABORTADO: '{OLD_KEY}' não tem mais linha de overlay, mas "
                    f"'{NEW_KEY}' tem {n_new}.\n"
                    f"Isso indica que o rename JÁ FOI APLICADO e que '{NEW_KEY}' agora é o "
                    f"EGP VIVO.\nRepetir o DELETE apagaria o funil/escopo/gestão/links e a "
                    f"trilha de auditoria dele — irrecuperável.\n\n"
                    f"Para RE-APLICAR o rename após um republish, use --skip-delete.\n"
                    f"Se você tem certeza de que '{NEW_KEY}' ainda é o __v2 original "
                    f"descartável, use --forca-delete-perigoso.",
                    file=sys.stderr)
                sys.exit(2)
        if n_old == 0 and n_new == 0:
            print(f"\nABORTADO: nem '{OLD_KEY}' nem '{NEW_KEY}' têm linha de overlay em {fq} "
                  f"— não há o que renomear aqui.", file=sys.stderr)
            sys.exit(2)

    if faz_delete:
        print(f"1) apaga tudo de '{NEW_KEY}' (__v2 original)")
    else:
        print("1) PULADO (--skip-delete)")
    print(f"2) renomeia '{OLD_KEY}' -> '{NEW_KEY}'")
    if args.skip_derived:
        print("   (--skip-derived: NÃO vai tocar nas tabelas full-replace — só overlay)")

    # --- 1. apaga o __v2 ORIGINAL (dono de linha própria em cada tabela) ---------------
    overlay_delete = [
        f"DELETE FROM {fq}.sas_egp_pipeline WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_escopo WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_output_producer_choice WHERE projeto_escolhido = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_gestao_status WHERE entity = 'egp' AND entity_id = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_gestao_datas WHERE entity = 'egp' AND entity_id = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_egp_input_link WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_egp_input_link_audit WHERE projeto = {lit(NEW_KEY)}",
    ]
    derived_delete = [
        f"DELETE FROM {fq}.sas_lineage_nodes WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_lineage_edges WHERE projeto_alvo = {lit(NEW_KEY)} OR depende_do = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_egp_inputs WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_egp_outputs WHERE projeto = {lit(NEW_KEY)}",
        f"DELETE FROM {fq}.sas_resumo_proj WHERE projeto = {lit(NEW_KEY)}",
    ]
    if faz_delete:
        for sql in overlay_delete:
            run(sql)
        if not args.skip_derived:
            for sql in derived_delete:
                run(sql)

    # Trilha e nota de encerramento pertencem ao DESCARTE do __v2 original: só fazem
    # sentido junto do bloco 1. Num re-apply (--skip-delete) nada foi removido, então
    # repeti-las criaria trilha de uma remoção que não aconteceu e duplicaria a nota.
    if faz_delete:
        # trilha da remoção do __v2 original — mesmo padrão de campo 'remocao' usado no
        # caso Cartão Amigável (memória cartao-amigavel-v2-removido)
        run(
            f"INSERT INTO {fq}.sas_pipeline_audit (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({lit(uuid.uuid4().hex)}, {lit(NEW_KEY)}, 'migracao', 'remocao', "
            f"'existia', 'removido (duplicata __v2 sem papel na linhagem; ver D013 em "
            f"RELATORIO_VERSOES_EGPS_2026-08-13.md)', {lit(args.actor)}, CAST(current_timestamp() AS STRING))"
        )

        # nota de encerramento da dúvida aberta em sas_gestao_status do __v2 original
        # ("Tratar como intermediate CPF_Contrato INFO_CONTA — dúvida falar com Leandro"),
        # registrada sob a chave NEW_KEY (que, após o rename abaixo, é o EGP resultante)
        closure_note = (
            "EGP CPF_Contrato__v2 original (script de 106 linhas, sem papel na linhagem, "
            "sem consumidores) descartado; nome 'v2' reaproveitado para este EGP (v1 sem "
            "base 3040), conforme alinhamento de escopo. Dúvida pendente sobre "
            "INFO_CONTA/Leandro (registrada em 2026-08-19) fica resolvida por esse descarte."
        )
        run(
            f"INSERT INTO {fq}.sas_gestao_status (id, entity, entity_id, autor, criado_por, ts, texto) "
            f"VALUES ({lit(uuid.uuid4().hex)}, 'egp', {lit(NEW_KEY)}, {lit(args.actor)}, "
            f"{lit(args.actor)}, CAST(current_timestamp() AS STRING), {lit(closure_note)})"
        )

    # --- 2. renomeia o v1 para a chave livre ------------------------------------------
    overlay_rename = [
        f"UPDATE {fq}.sas_egp_pipeline SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_escopo SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_output_producer_choice SET projeto_escolhido = {lit(NEW_KEY)} "
        f"WHERE projeto_escolhido = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_gestao_status SET entity_id = {lit(NEW_KEY)} "
        f"WHERE entity = 'egp' AND entity_id = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_gestao_datas SET entity_id = {lit(NEW_KEY)} "
        f"WHERE entity = 'egp' AND entity_id = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_egp_input_link SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_egp_input_link_audit SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_pipeline_audit SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_escopo_audit SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
    ]
    derived_rename = [
        f"UPDATE {fq}.sas_lineage_nodes SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_lineage_edges SET projeto_alvo = {lit(NEW_KEY)} WHERE projeto_alvo = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_lineage_edges SET depende_do = {lit(NEW_KEY)} WHERE depende_do = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_egp_inputs SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_egp_outputs SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
        f"UPDATE {fq}.sas_resumo_proj SET projeto = {lit(NEW_KEY)} WHERE projeto = {lit(OLD_KEY)}",
    ]
    for sql in overlay_rename:
        run(sql)
    if not args.skip_derived:
        for sql in derived_rename:
            run(sql)

    # --- 3. trim de escopo: base 3040 não vai ser migrada neste EGP ------------------
    # (o motivo de negócio do próprio rename: "v2" = v1 sem a base 3040). Só faz sentido
    # se as tabelas derivadas foram renomeadas (senão a linha ainda está sob OLD_KEY).
    if not args.skip_derived:
        run(
            f"UPDATE {fq}.sas_egp_outputs SET escopo_indi = false "
            f"WHERE projeto = {lit(NEW_KEY)} AND artifact LIKE 'CARNEIRO.BASE_3040%'"
        )

    run(
        f"INSERT INTO {fq}.sas_pipeline_audit (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
        f"VALUES ({lit(uuid.uuid4().hex)}, {lit(NEW_KEY)}, 'migracao', 'rename', "
        f"{lit(OLD_KEY)}, {lit(NEW_KEY)}, {lit(args.actor)}, CAST(current_timestamp() AS STRING))"
    )
    if not args.skip_derived:
        run(
            f"INSERT INTO {fq}.sas_pipeline_audit (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({lit(uuid.uuid4().hex)}, {lit(NEW_KEY)}, 'migracao', 'escopo_output', "
            f"'BASE_3040_* escopo_indi=true', 'BASE_3040_* escopo_indi=false (base 3040 fora "
            f"do escopo deste EGP)', {lit(args.actor)}, CAST(current_timestamp() AS STRING))"
        )

    print("\nNÃO esquecer manualmente (fora do script, revisar caso a caso):")
    print(f"  - sas_priorizacao_snapshot: payload JSON pode ter menções a '{OLD_KEY}' em meses "
          f"congelados (prod tinha 3 na leitura de 2026-08-24) — editar a string dentro do JSON "
          f"se quiser consistência histórica.")
    print(f"  - Jira UDAA-4759 (v1) e o card 'Tratar como intermediate CPF_Contrato INFO_CONTA' "
          f"(gestão v2 original) — avisar responsáveis do nome novo.")
    if not args.skip_derived:
        print("  - Rodar Processar/publish de novo vai REGERAR sas_lineage_nodes/edges, "
              "sas_egp_inputs/outputs e sas_resumo_proj com o nome ORIGINAL "
              f"'{OLD_KEY}' a partir da extração do .egp — reaplicar DEPOIS DE CADA PUBLISH "
              "com:\n"
              "        python docs/analises/rename_cpf_contrato_v1_para_v2.py --skip-delete "
              "--apply [--prod-confirm]\n"
              "    (--skip-delete é obrigatório no re-apply: repetir o bloco 1 apagaria o "
              "EGP vivo. O guard de reexecução barra isso, mas a flag é o caminho correto.) "
              "Vale até existir um mecanismo de alias persistente no pipeline.")


if __name__ == "__main__":
    main()

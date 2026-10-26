#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aplica em lote as ações de BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv
(gerado por build_acao_egp_sanitizar_desvincular.py) contra o Databricks — sem editar
input por input na tela.

  - acao == "Sanitizado"  -> UPDATE sas_inputs_monitor (etapa='Modernizado',
    status='Sanitizado', observacao += motivo, sem apagar observação humana existente)
    + auditoria em sas_inputs_audit. Ação GLOBAL por chave_canonica (mesmo efeito de
    PATCH /api/inputs na tela) — o CSV só marca "Sanitizado" quando já garantiu que não
    há outro leitor que dependa de ingestão real desse input.

  - acao == "Desvincular" -> MERGE em sas_egp_input_link (link_broken=true) + auditoria
    em sas_egp_input_link_audit (mesmo efeito de PATCH /api/egp-input-link na tela).
    Ação por par (EGP, input) — não toca no status do input para os demais leitores
    (comentário no próprio main.py: "Broken=True -> aquele input passa a contar como
    Sanitizado para AQUELE EGP apenas").

Linhas com acao == "Revisar manualmente" são ignoradas de propósito (não existem na
versão atual do CSV, mas o script não assume isso).

Idempotente: pula o que já está no estado desejado (status já 'Sanitizado', link já
quebrado) — pode rodar de novo sem duplicar auditoria.

Uso (mesmo padrão de scripts/migrate_input_status_split.py):
  cd egps_analysis
  python docs/analises/aplica_acao_sanitizar_desvincular.py \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                 # dry-run
  python docs/analises/aplica_acao_sanitizar_desvincular.py --apply \\
      --profile bv --warehouse-id 5922c26f81f1bbdd                 # aplica no sandbox _dev
  python docs/analises/aplica_acao_sanitizar_desvincular.py --apply --prod-confirm \\
      --schema monitoramento_sas --profile bv --warehouse-id 5922c26f81f1bbdd   # PROD

Rode sempre primeiro em dry-run, depois --apply no sandbox (_dev) e confira na tela
antes de repetir com --prod-confirm contra produção.
"""
import argparse
import csv
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
DEFAULT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv",
)


# Helper CANÔNICO (publish_to_databricks.sql_lit), não uma cópia local: ele escapa a
# contrabarra ANTES da aspa. As cópias locais só escapavam a aspa, e este corpus é
# cheio de caminho UNC/Windows (`N:\`, `\\bvnet\global\...`) que chega ao SQL via
# `observacao`/`comentario` escritos por analista. Em Spark SQL a `\` é escape dentro
# do literal: valor terminado em `\` escapa a aspa de fechamento e quebra (ou desloca)
# o statement; `\g` & cia corrompem o texto gravado em silêncio.
lit = _pub.sql_lit


def as_bool(v):
    return str(v).strip().lower() in ("true", "1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--apply", action="store_true",
                     help="conecta e escreve no Databricks (default: dry-run, só mostra o que faria)")
    ap.add_argument("--only", choices=["sanitizado", "desvincular", "all"], default="all",
                     help="rodar só uma das duas ações (ex.: aplicar Desvincular antes de revisar Sanitizado)")
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas_dev"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"),
                     help="perfil do ~/.databrickscfg (OAuth/U2M)")
    ap.add_argument("--prod-confirm", action="store_true",
                     help=f"obrigatório p/ --apply contra o schema de PROD ('{PROD_SCHEMA}')")
    args = ap.parse_args()

    if args.apply and args.schema == PROD_SCHEMA and not args.prod_confirm:
        ap.error(f"--apply contra PROD ('{args.catalog}.{args.schema}') requer --prod-confirm. "
                 f"Sem ele, use o sandbox (default --schema monitoramento_sas_dev).")
    if not args.warehouse_id:
        ap.error("defina --warehouse-id ou DATABRICKS_DEFAULT_WAREHOUSE_ID")

    with open(args.csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    sanit, desv, ignoradas = {}, {}, 0
    for r in rows:
        if r["acao"] == "Sanitizado":
            sanit.setdefault(r["chave_canonica"], r["comentario"])
        elif r["acao"] == "Desvincular":
            desv[(r["egp"], r["chave_canonica"])] = r["comentario"]
        else:
            ignoradas += 1  # "Revisar manualmente" ou outro valor futuro — não decide por código

    print(f"CSV: {len(rows)} linhas -> {len(sanit)} inputs distintos p/ Sanitizado, "
          f"{len(desv)} pares EGP+input p/ Desvincular, {ignoradas} ignoradas")

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
    except ImportError:
        print("ERRO: databricks-sdk não instalado no venv ativo.", file=sys.stderr)
        sys.exit(1)

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    fq = f"{args.catalog}.{args.schema}"
    t_in, t_aud = f"{fq}.sas_inputs_monitor", f"{fq}.sas_inputs_audit"
    t_link, t_link_aud = f"{fq}.sas_egp_input_link", f"{fq}.sas_egp_input_link_audit"

    def run(sql, want_rows=True):
        resp = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=args.warehouse_id,
            wait_timeout="50s", disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if (resp.status and resp.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:800]}")
        if not want_rows or not resp.result or not resp.result.data_array:
            return []
        cols = [c.name for c in resp.manifest.schema.columns]
        return [dict(zip(cols, row)) for row in resp.result.data_array]

    _tgt = "PRODUÇÃO ⚠" if args.schema == PROD_SCHEMA else "sandbox/dev"
    print(f"== aplica_acao_sanitizar_desvincular ==  destino: {fq}  [{_tgt}]  "
          f"{'APPLY' if args.apply else 'DRY-RUN'}  (só: {args.only})")

    # ------------------------------------------------------------------
    # 1) Sanitizado — status GLOBAL do input, só quando ainda não está lá
    # ------------------------------------------------------------------
    if sanit and args.only in ("sanitizado", "all"):
        chaves = list(sanit.keys())
        in_list = ",".join(lit(c) for c in chaves)
        old_rows = run(f"SELECT chave_canonica, etapa, status, observacao FROM {t_in} "
                        f"WHERE chave_canonica IN ({in_list})")
        old_by_key = {r["chave_canonica"]: r for r in old_rows}
        faltantes = [c for c in chaves if c not in old_by_key]
        if faltantes:
            preview = ", ".join(faltantes[:5]) + ("..." if len(faltantes) > 5 else "")
            print(f"  [aviso] {len(faltantes)} chaves do CSV não existem em {t_in} "
                  f"(fora do publish atual) — ignoradas: {preview}")

        to_update, audit_rows = [], []
        for chave, motivo in sanit.items():
            old = old_by_key.get(chave)
            if not old or old["status"] == "Sanitizado":
                continue  # não encontrado, ou já feito (idempotente)
            to_update.append(chave)
            audit_rows.append((chave, "status", old["status"] or "", "Sanitizado"))
            if old["etapa"] != "Modernizado":
                audit_rows.append((chave, "etapa", old["etapa"] or "", "Modernizado"))

        ja_feito = len(old_by_key) - len(to_update)
        print(f"  Sanitizado: {len(to_update)} precisam de update, {ja_feito} já 'Sanitizado', "
              f"{len(faltantes)} fora da tabela")

        if to_update and args.apply:
            case_obs = " ".join(
                f"WHEN chave_canonica = {lit(c)} THEN "
                f"CASE WHEN observacao IS NULL OR observacao = '' THEN {lit(sanit[c])} "
                f"ELSE concat(observacao, ' | ', {lit(sanit[c])}) END"
                for c in to_update)
            in_upd = ",".join(lit(c) for c in to_update)
            run(f"UPDATE {t_in} SET etapa = 'Modernizado', status = 'Sanitizado', "
                f"observacao = CASE {case_obs} END, "
                f"updated_at = current_timestamp(), updated_by = current_user() "
                f"WHERE chave_canonica IN ({in_upd})", want_rows=False)
            vals = ",\n".join(
                f"({lit(c)}, {lit(campo)}, {lit(va)}, {lit(vn)}, current_user(), current_timestamp())"
                for c, campo, va, vn in audit_rows)
            run(f"INSERT INTO {t_aud} (chave_canonica, campo, valor_antigo, valor_novo, "
                f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
            print(f"  [apply] {len(to_update)} inputs marcados Sanitizado, "
                  f"{len(audit_rows)} linhas de auditoria gravadas.")

    # ------------------------------------------------------------------
    # 2) Desvincular — por par (EGP, input), não afeta outros leitores
    # ------------------------------------------------------------------
    if desv and args.only in ("desvincular", "all"):
        pairs = list(desv.keys())
        values_sql = ",".join(f"({lit(p)}, {lit(c)})" for p, c in pairs)
        old_rows = run(
            f"SELECT s.projeto AS projeto, s.chave_canonica AS chave_canonica, "
            f"t.link_broken AS link_broken FROM "
            f"(SELECT * FROM VALUES {values_sql} AS v(projeto, chave_canonica)) s "
            f"LEFT JOIN {t_link} t "
            f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica")
        already_broken = {(r["projeto"], r["chave_canonica"])
                           for r in old_rows if r["link_broken"] is not None and as_bool(r["link_broken"])}
        to_break = [p for p in pairs if p not in already_broken]

        print(f"  Desvincular: {len(to_break)} pares precisam de MERGE, "
              f"{len(already_broken)} já quebrados")

        if to_break and args.apply:
            values_sql2 = ",".join(f"({lit(p)}, {lit(c)})" for p, c in to_break)
            run(f"MERGE INTO {t_link} t USING "
                f"(SELECT * FROM VALUES {values_sql2} AS v(projeto, chave_canonica)) s "
                f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
                f"WHEN MATCHED THEN UPDATE SET t.link_broken = true, "
                f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
                f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, link_broken, "
                f"updated_by, updated_at) VALUES (s.projeto, s.chave_canonica, true, "
                f"current_user(), current_timestamp())", want_rows=False)
            vals = ",\n".join(
                f"({lit(uuid.uuid4().hex)}, {lit(p)}, {lit(c)}, 'link_broken', 'false', 'true', "
                f"current_user(), current_timestamp())" for p, c in to_break)
            run(f"INSERT INTO {t_link_aud} (id, projeto, chave_canonica, campo, valor_antigo, "
                f"valor_novo, ator, ts) VALUES\n{vals}", want_rows=False)
            print(f"  [apply] {len(to_break)} vínculos quebrados.")

    if not args.apply:
        print("\n(dry-run — nada foi escrito; rode com --apply para gravar no sandbox, "
              "ou --apply --prod-confirm --schema monitoramento_sas para produção)")


if __name__ == "__main__":
    main()

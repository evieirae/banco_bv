#!/usr/bin/env python3
"""EGPs que geram os próprios inputs — escopo indi_deps, dados do app (prod).

READ-ONLY em bv_dev_db.monitoramento_sas. Replica:
  - _frontier_egps("indi_deps", []) do backend (poda por produtor canônico +
    vias resolvidas + no_expand dos despriorizados);
  - o match input↔output do app ("canon puro": strip do prefixo 'categoria::');
  - o export da aba Inputs (uma linha por input×EGP, mesmas colunas, ';'+BOM).

Saída: CSV com os pares (input × EGP) em que o PRÓPRIO EGP produz o input.
"""
import json
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

CATALOG = "bv_dev_db"
SCHEMA = os.environ.get("MONITOR_SCHEMA", "monitoramento_sas")
FQ = f"{CATALOG}.{SCHEMA}"
WAREHOUSE_ID = "5922c26f81f1bbdd"

T_IN = f"{FQ}.sas_inputs_monitor"
T_ND = f"{FQ}.sas_lineage_nodes"
T_ED = f"{FQ}.sas_lineage_edges"
T_EGP = f"{FQ}.sas_egp_inputs"
T_EGP_OUT = f"{FQ}.sas_egp_outputs"
T_LINK = f"{FQ}.sas_egp_input_link"
T_CHOICE = f"{FQ}.sas_output_producer_choice"
T_PIPE = f"{FQ}.sas_egp_pipeline"
T_RES = f"{FQ}.sas_resumo_inputs"

wc = WorkspaceClient()


def sql(stmt, want_rows=True):
    r = wc.statement_execution.execute_statement(
        statement=stmt, warehouse_id=WAREHOUSE_ID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = wc.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL falhou ({r.status.state}): {r.status.error}\n  {stmt}")
    if not want_rows or not r.result:
        return []
    cols = [c.name for c in r.manifest.schema.columns]
    rows = []
    chunk = r.result
    while True:
        for row in (chunk.data_array or []):
            rows.append(dict(zip(cols, row)))
        nxt = chunk.next_chunk_index
        if nxt is None:
            break
        chunk = wc.statement_execution.get_statement_result_chunk_n(r.statement_id, nxt)
    return rows


def sql_lit(s):
    # Aspa escapada com \' e NÃO com '' : no Spark SQL `'O''Brien'` é lido como DOIS
    # literais adjacentes concatenados ("O" + "Brien"), então o apóstrofo some em
    # silêncio — não dá erro, grava o texto errado. Verificado no warehouse:
    #   SELECT 'O''Brien'  -> OBrien      (errado)
    #   SELECT 'O\'Brien'  -> O'Brien     (certo)
    # A contrabarra é escapada ANTES da aspa, senão a barra introduzida por \' seria
    # duplicada. Não confundir com sas_quote() em egps_extractor.py: aquilo gera código
    # SAS, onde '' É o escape correto.
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


# --- SQL de status efetivo / modernizado (cópia fiel de main.py) ---
def _eff_status(sh="status_humano", auto="modernizada_auto"):
    norm = (f"CASE {sh} WHEN 'Disponível' THEN 'Modernizado' WHEN 'Sanitizada' THEN 'Sanitizado' "
            f"WHEN 'Descartada' THEN 'Sanitizado' WHEN 'Descartado' THEN 'Sanitizado' "
            f"WHEN 'Em análise' THEN 'Recebido' WHEN 'A ingerir' THEN 'A receber' "
            f"WHEN 'Não recebido' THEN 'A receber' WHEN 'Priorizado' THEN 'Recebido' "
            f"ELSE {sh} END")
    auto_def = (f"CASE {auto} WHEN 'Disponível' THEN 'Modernizado' "
                f"WHEN 'A ingerir' THEN 'A receber' ELSE 'Recebido' END")
    return f"coalesce(nullif({norm}, ''), {auto_def})"


def _modern():
    return f"({_eff_status()} IN ('Modernizado','Sanitizado'))"


# --- réplica de _prune_edges / _filter_vias_resolvidas_res / _dep_of_map / _transitive_upstream ---
def _prune_edges(rows, choices):
    if not choices:
        return rows
    prod_by_via = {}
    for e in rows:
        for t in (e.get("via_tabelas") or "").split(" | "):
            t = t.strip()
            if t:
                prod_by_via.setdefault(t, set()).add(e.get("depende_do"))
    eff = {t: p for t, p in choices.items() if p in prod_by_via.get(t, ())}
    if not eff:
        return rows
    out = []
    for e in rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        keep = [t for t in vias if not (t in eff and eff[t] != e.get("depende_do"))]
        if keep:
            out.append({**e, "via_tabelas": " | ".join(keep)})
    return out


def _filter_vias_resolvidas_res(rows, res):
    if not res:
        return rows
    out = []
    for e in rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        if not vias:
            out.append(e)
            continue
        keep = [t for t in vias if t.upper() not in res]
        if keep:
            out.append({**e, "via_tabelas": " | ".join(keep)})
    return out


def _dep_of_map(edges):
    dep_of = {}
    for e in edges:
        a, d = e["projeto_alvo"], e["depende_do"]
        if a and d and a != d:
            dep_of.setdefault(a, set()).add(d)
    return dep_of


def _transitive_upstream(base_set, dep_of, no_expand=frozenset()):
    level = {p: 0 for p in base_set}
    frontier = set(base_set) - set(no_expand)
    hop = 0
    while frontier:
        hop += 1
        nxt = set()
        for p in frontier:
            for dep in dep_of.get(p, ()):
                if dep not in level:
                    level[dep] = hop
                    if dep not in no_expand:
                        nxt.add(dep)
        frontier = nxt
    return level


def main():
    out_csv = sys.argv[1]

    print("1/5 frontier indi_deps ...", flush=True)
    edges = sql(f"SELECT projeto_alvo, depende_do, via_tabelas FROM {T_ED}")
    try:
        choices = {r["chave_canonica"]: r["projeto_escolhido"]
                   for r in sql(f"SELECT chave_canonica, projeto_escolhido FROM {T_CHOICE}")
                   if r.get("chave_canonica") and r.get("projeto_escolhido")}
    except RuntimeError:
        choices = {}
    res = {(r.get("artifact") or "").strip().upper()
           for r in sql(f"SELECT artifact FROM {T_IN} WHERE categoria = 'tabela' AND ({_modern()})")
           if (r.get("artifact") or "").strip()}
    base = {r["projeto"] for r in sql(f"SELECT projeto FROM {T_ND} WHERE escopo_indi = true")
            if r.get("projeto")}
    try:
        no_expand = {r["projeto"] for r in sql(
            f"SELECT projeto FROM {T_PIPE} WHERE status_migracao = 'Despriorizado e Contabilizado'")
            if r.get("projeto")}
    except RuntimeError:
        no_expand = set()
    pruned = _filter_vias_resolvidas_res(_prune_edges(edges, choices), res)
    level = _transitive_upstream(base, _dep_of_map(pruned), no_expand=no_expand)
    frontier = set(level)
    print(f"   base={len(base)}  frontier={len(frontier)}  deps={len(frontier)-len(base)}  "
          f"choices={len(choices)}  vias_resolvidas={len(res)}  despriorizados={len(no_expand)}",
          flush=True)

    print("2/5 pares input×EGP em que o EGP produz o próprio input ...", flush=True)
    # match canon puro: chave de input tem prefixo 'categoria::'; a de output não.
    # vínculo quebrado (sas_egp_input_link) fora — mesmo critério do export do app.
    pairs = sql(
        f"SELECT e.projeto, e.chave_canonica, "
        f"       regexp_replace(e.chave_canonica, '^[^:]*::', '') AS canon "
        f"FROM {T_EGP} e "
        f"JOIN {T_EGP_OUT} o ON o.projeto = e.projeto "
        f"  AND regexp_replace(e.chave_canonica, '^[^:]*::', '') = o.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE NOT coalesce(l.link_broken, false)")
    pairs_all = len(pairs)
    pairs = [p for p in pairs if p["projeto"] in frontier]
    print(f"   pares (base completa)={pairs_all}  pares no indi_deps={len(pairs)}", flush=True)

    print("3/5 outros produtores de cada input auto-gerado ...", flush=True)
    canons = sorted({p["canon"] for p in pairs})
    other_prod = {}
    for i in range(0, len(canons), 400):
        inl = ", ".join(sql_lit(c) for c in canons[i:i + 400])
        for r in sql(f"SELECT chave_canonica, projeto FROM {T_EGP_OUT} "
                     f"WHERE chave_canonica IN ({inl})"):
            other_prod.setdefault(r["chave_canonica"], set()).add(r["projeto"])

    print("4/5 inventário (colunas do export da aba Inputs) ...", flush=True)
    chaves = sorted({p["chave_canonica"] for p in pairs})
    inv = {}
    for i in range(0, len(chaves), 400):
        inl = ", ".join(sql_lit(c) for c in chaves[i:i + 400])
        for r in sql(
            f"SELECT chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, "
            f"areas, modernizada_auto, status_humano, responsavel, observacao, "
            f"paths_fisicos, n_paths_fisicos, {_eff_status()} AS status_efetivo, "
            f"(SELECT max(r.area_principal) FROM {T_RES} r "
            f" WHERE r.chave_canonica = i.chave_canonica) AS area_principal "
            f"FROM {T_IN} i WHERE chave_canonica IN ({inl})"):
            inv[r["chave_canonica"]] = r

    print("5/5 CSV ...", flush=True)

    def egp_short(pid):
        return pid.split("__", 1)[1] if "__" in pid else pid

    def esc(v):
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in '";\n\r') else s

    header = ["EGP", "Artefato", "Categoria", "Origem", "Áreas", "Tipos de fonte",
              "Qtd projetos", "Status efetivo", "Status (humano)", "Modernizada (auto)",
              "Responsável", "Tbl. Corresp.", "Nº paths físicos", "Paths físicos",
              "Chave canônica",
              # colunas extras da análise (mesma granularidade, não existem no export do app)
              "EGP (id completo)", "Nível dep (0=escopo Indicium)", "Outros produtores do input",
              "Qtd outros produtores"]

    def sort_key(p):
        r = inv.get(p["chave_canonica"], {})
        try:
            q = -int(r.get("qtd_projetos") or 0)
        except (TypeError, ValueError):
            q = 0
        return (q, r.get("artifact") or "", p["projeto"])

    lines = [";".join(esc(h) for h in header)]
    for p in sorted(pairs, key=sort_key):
        r = inv.get(p["chave_canonica"], {})
        others = sorted(other_prod.get(p["canon"], set()) - {p["projeto"]})
        lines.append(";".join(esc(v) for v in [
            egp_short(p["projeto"]),
            r.get("artifact"), r.get("categoria"), r.get("origem"), r.get("areas"),
            r.get("source_types"), r.get("qtd_projetos"), r.get("status_efetivo"),
            r.get("status_humano") or "", r.get("modernizada_auto"),
            r.get("responsavel") or "", r.get("observacao") or "",
            r.get("n_paths_fisicos"), r.get("paths_fisicos"), p["chave_canonica"],
            p["projeto"], level.get(p["projeto"], ""),
            " | ".join(egp_short(o) for o in others), len(others),
        ]))
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("﻿" + "\r\n".join(lines) + "\r\n")
    print(f"   {out_csv}  ({len(lines)-1} linhas)", flush=True)

    # ---- resumo p/ análise ----
    egps = {p["projeto"] for p in pairs}
    inputs_set = {p["chave_canonica"] for p in pairs}
    excl = [p for p in pairs if not (other_prod.get(p["canon"], set()) - {p["projeto"]})]
    st = {}
    for ch in inputs_set:
        s = inv.get(ch, {}).get("status_efetivo") or "?"
        st[s] = st.get(s, 0) + 1
    orig = {}
    for ch in inputs_set:
        o = inv.get(ch, {}).get("origem") or "?"
        orig[o] = orig.get(o, 0) + 1
    top = {}
    for p in pairs:
        top[p["projeto"]] = top.get(p["projeto"], 0) + 1
    summary = {
        "frontier": len(frontier), "base": len(base),
        "pares": len(pairs), "egps_auto": len(egps), "inputs_auto": len(inputs_set),
        "pares_produtor_exclusivo": len(excl),
        "inputs_produtor_exclusivo": len({p["chave_canonica"] for p in excl}),
        "status_por_input": st, "origem_por_input": orig,
        "top_egps": sorted(top.items(), key=lambda x: -x[1])[:15],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

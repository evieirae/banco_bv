#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checagem READ-ONLY da regra de família de safras contra um schema real.

Dois papéis, re-rodáveis a cada ticket da esteira de famílias:
  1. PARIDADE — a forma Python (`familias.familia_candidata`) e a forma SQL
     (`familias.familia_efetiva_sql`) têm que devolver a MESMA chave para as mesmas linhas.
     Divergência aqui é bug de sincronia entre as duas cópias da regra, e é o que mais
     silenciosamente produziria número errado em relatório.
  2. CONTAGENS — linhas -> unidades, famílias e pendentes, no universo e no escopo Indicium.

Números ESTRUTURAIS (linhas, unidades, famílias) vêm do pipeline e só mudam em publish.
Números VIVOS (pendentes) mudam todo dia com a edição dos analistas — re-meça na hora de
validar, não compare com um número escrito num ticket dias antes.

Uso (só SELECT; nunca escreve):
  egps_analysis/venv/bin/python egps_analysis/scripts/verifica_familias.py \
      --profile bv --catalog bv_dev_db --schema monitoramento_sas
"""
import argparse
import collections
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "app", "backend"))
import familias as F  # noqa: E402

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState, Disposition, Format  # noqa: E402

# Predicados de fila — CÓPIA FIEL de app/backend/main.py::_eff_etapa/_eff_status_input/_modern.
# "Pendente" (a ingerir) NÃO é "status não terminal": `status='Concluído'` numa etapa
# intermediária significa "essa etapa acabou", não "input resolvido". Resolvido = chegou na
# etapa Modernizado OU status Sanitizado/Autoprodutor. MANTENHA EM SINCRONIA com main.py.


def _q(w, wid, sql):
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=wid, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "estado desconhecido")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest else []
    # Segue next_chunk_index: com INLINE só o PRIMEIRO chunk vem na resposta. Aqui o
    # truncamento é especialmente traiçoeiro — este script existe para comparar a regra
    # de família em Python com a em SQL, e ler meia tabela faria as duas "divergirem"
    # (ou pior, "convergirem") por um motivo que não tem nada a ver com a regra.
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    return [dict(zip(cols, row)) for row in linhas]


def _eff_etapa(r):
    et = (r.get("etapa") or "").strip()
    if et:
        return et
    return "Modernizado" if r.get("modernizada_auto") == "Disponível" else "A Receber"


def _eff_status(r):
    st = (r.get("status") or "").strip()
    if st:
        return st
    return "Concluído" if _eff_etapa(r) == "Modernizado" else "A Iniciar"


def _a_ingerir(r):
    """Pendente = não resolvido (main.py::_aingerir). Vínculo quebrado é per-(EGP, input),
    não entra aqui — esta função olha o input no grão do monitor."""
    return not (_eff_etapa(r) == "Modernizado"
                or _eff_status(r) in ("Sanitizado", "Autoprodutor"))


def _resumo(label, subset, chave, e_familia=None):
    """`e_familia(categoria, chave)` diz se a unidade é família SEGUNDO O CORPUS.

    Sem ela, a contagem cairia em "unidades com ≥2 membros NESTE recorte", que é outra
    régua: uma família com 5 safras no corpus e 1 no escopo é família (a API a mostra como
    tal), mas apareceria como input solto aqui. Medir por réguas diferentes nos dois lados
    do gate produz divergência que não existe."""
    unidades = collections.defaultdict(list)
    for r in subset:
        unidades[(r["categoria"], chave(r))].append(r)
    familias_n = (sum(1 for k in unidades if e_familia(*k)) if e_familia
                  else sum(1 for v in unidades.values() if len(v) > 1))
    pend_linhas = sum(1 for r in subset if _a_ingerir(r))
    # família pendente = QUALQUER membro pendente (roll-up do ADR 0002: membro
    # terminal não conta nem segura; se todos resolvidos, a família sai da fila)
    pend_unid = sum(1 for v in unidades.values() if any(_a_ingerir(x) for x in v))
    print(f"  {label}: {len(subset)} linhas -> {len(unidades)} unidades "
          f"({familias_n} famílias) | pendentes {pend_linhas} -> {pend_unid}")
    return {"linhas": len(subset), "unidades": len(unidades), "familias": familias_n,
            "pendentes_linha": pend_linhas, "pendentes_unidade": pend_unid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="bv")
    ap.add_argument("--catalog", default="bv_dev_db")
    ap.add_argument("--schema", default="monitoramento_sas_dev")
    ap.add_argument("--warehouse-id", default=os.environ.get(
        "DATABRICKS_WAREHOUSE_ID", "5922c26f81f1bbdd"))
    args = ap.parse_args()
    fq = f"{args.catalog}.{args.schema}"
    w = WorkspaceClient(profile=args.profile)

    # a janela da guarda dos ≥2 membros roda DENTRO do CTE, sobre o corpus inteiro (não-órfãs):
    # filtrar por escopo antes dela quebraria a invariante de identidade independente do filtro
    rows = _q(w, args.warehouse_id, f"""WITH corpus AS (
  SELECT artifact, categoria, escopo_indi, etapa, status, modernizada_auto,
         {F.familia_efetiva_sql()} AS fam_sql
  FROM {fq}.sas_inputs_monitor WHERE orfao = false)
SELECT * FROM corpus""")
    print(f"== {fq} — {len(rows)} linhas não-órfãs ==")
    if not rows:
        print("  (vazio: schema sem dados publicados)")
        return 0

    res = F.resolve(rows)

    def chave(r):
        return res["chave"][(r["categoria"], (r["artifact"] or "").strip().upper())]

    div = [(r["categoria"], r["artifact"], r["fam_sql"], chave(r))
           for r in rows if chave(r) != r["fam_sql"]]
    print(f"\nparidade Python x SQL: {len(div)} divergência(s) em {len(rows)} linhas")
    for d in div[:10]:
        print("   ", d)

    membros = res["membros"]

    def e_familia(cat, k):
        return len(membros.get((cat, k), ())) > 1

    print("\ncontagens (família = ≥2 membros NO CORPUS, mesma régua da API):")
    print("  nota: `pendentes` aqui é grão MONITOR (sem o filtro de vínculo ativo nem a")
    print("        exclusão de ex-dependência). O card da landing conta o UNIVERSO POR")
    print("        VÍNCULO e por isso é igual ou MENOR — a diferença não é divergência.")
    _resumo("universo", rows, chave, e_familia)
    _resumo("escopo  ", [r for r in rows if r["escopo_indi"] in (True, "true")], chave,
            e_familia)

    maiores = sorted(((len(v), k[1]) for k, v in res["membros"].items() if len(v) > 1),
                     reverse=True)[:5]
    print("\nmaiores famílias:", ", ".join(f"{n}× {k}" for n, k in maiores))
    return 1 if div else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Levantamento READ-ONLY (prod): inputs `.sas7bdat` classificados como `arquivo` que
SÃO, de fato, TABELAS SAS — `.sas7bdat` é o arquivo físico de um dataset SAS.

Por que isso importa (ponto cego estrutural, não bug de dado):

  orchestrator_inventory.py:1270 → toda a árvore de decisão de modernização
  (Chameleon → RepMap → Inventário Transacional → override autoritativo) está sob
  `if cat in ('table_in', 'table_out')`. Um `file_in` terminado em `.sas7bdat` NUNCA
  entra nesse ramo: `status` fica "Não Encontrado" → `modernizada_auto = 'A ingerir'`
  PARA SEMPRE, mesmo quando a MESMA tabela SAS já existe modernizada no BigQuery.

  publish_to_databricks.py:366 (`_sas7bdat_dedup_members`) colapsa o `file_in`
  '<membro>.sas7bdat' no `table_in` 'lib.membro' apenas DENTRO DO MESMO PROJETO. Se o
  arquivo é lido no EGP A e a tabela via libname no EGP B, sobram DUAS chaves canônicas
  no monitor ('arquivo::X.SAS7BDAT' + 'tabela::LIB.X') para o mesmo dataset físico.

O script cruza a população-alvo com (a) o universo de inputs `tabela`, (b) os outputs
do corpus e (c) a árvore de modernização REAL (importada do orchestrator, rodada sobre
o nome do MEMBRO) e classifica cada linha num bucket com ação sugerida.

Só SELECT — não escreve nada em prod.

Uso:
    egps_analysis/venv/bin/python \
        egps_analysis/docs/analises/levantamento_sas7bdat_arquivo_vs_tabela.py
"""
import collections
import csv
import datetime
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_EGPS = os.path.dirname(os.path.dirname(_HERE))          # egps_analysis/
sys.path.insert(0, _EGPS)

from orchestrator_inventory import (                      # noqa: E402
    is_strict_match,
    load_chameleon_data,
    load_modernization_override,
)

# as constantes do orchestrator são relativas ao CWD (`./src/...`); aqui ancoramos
# em egps_analysis/ para o script rodar de qualquer diretório
CHAMELEON_CSV_PATH = os.path.join(_EGPS, "src", "chameleon.csv")
MODERN_OVERRIDE_CSV_PATH = os.path.join(_EGPS, "src", "inputs_modernizados.csv")

WID = "5922c26f81f1bbdd"
FQ = "bv_dev_db.monitoramento_sas"
PROFILE = os.environ.get("DBX_PROFILE", "bv")
STAMP = datetime.date.today().isoformat()
OUT_CSV = os.path.join(_HERE, f"BV_Migracao_SAS_Inputs_sas7bdat_como_Tabela_{STAMP}.csv")
# sufixo _auto: o relatório curado (RELATORIO_INPUTS_SAS7BDAT_COMO_TABELA_*.md) é escrito
# à mão a partir deste esqueleto — re-rodar o script não pode sobrescrever a análise
OUT_MD = os.path.join(_HERE, f"RELATORIO_INPUTS_SAS7BDAT_COMO_TABELA_{STAMP}_auto.md")


# ---------------------------------------------------------------- prod (read-only)
def connect():
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState, Disposition, Format

    w = WorkspaceClient(profile=PROFILE)

    def q(sql):
        r = w.statement_execution.execute_statement(
            statement=sql, warehouse_id=WID, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
        sid = r.statement_id
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = w.statement_execution.get_statement(statement_id=sid)
        if not r.status or r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if (r.status and r.status.error) else "?"
            raise RuntimeError(f"SQL falhou: {msg}\n--SQL--\n{sql[:400]}")
        cols = [c.name for c in r.manifest.schema.columns]
        rows, chunk = [], r.result
        while chunk is not None:                            # pagina os chunks
            rows.extend(chunk.data_array or [])
            nxt = chunk.next_chunk_index
            if nxt is None:
                break
            chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
        return [dict(zip(cols, row)) for row in rows]

    return q


# ------------------------------------------------- status efetivo (espelha main.py)
def eff_etapa(etapa, auto):
    """main.py::_eff_etapa — etapa humana prevalece; sem humana, deriva do auto."""
    return (etapa or "").strip() or ("Modernizado" if auto == "Disponível" else "A Receber")


def eff_status(status, etapa, auto):
    """main.py::_eff_status_input — status humano prevalece; sem humano, deriva da etapa."""
    return (status or "").strip() or (
        "Concluído" if eff_etapa(etapa, auto) == "Modernizado" else "A Iniciar")


def is_modern(etapa, auto, status):
    """main.py::_modern — resolvido = etapa terminal OU Sanitizado."""
    return (eff_etapa(etapa, auto) == "Modernizado"
            or eff_status(status, etapa, auto) == "Sanitizado")


def membro(art):
    """publish_to_databricks::_memb_sas7 — membro UPPER, sem diretório nem extensão."""
    b = (art or "").replace("\\", "/").rsplit("/", 1)[-1]
    if b.lower().endswith(".sas7bdat"):
        b = b[:-len(".sas7bdat")]
    return b.strip().upper()


def membro_tabela(art):
    """Membro de um artefato 'LIB.MEMBRO' (ou 'db..tabela' de pass-through)."""
    return (art or "").strip().upper().rsplit(".", 1)[-1]


# ------------------------------------------- árvore de modernização (só p/ simulação)
def simula_modernizacao(memb, cham, override):
    """Roda a MESMA decisão de orchestrator_inventory.py sobre o nome do MEMBRO — a
    pergunta é 'se este .sas7bdat fosse classificado como tabela, ele casaria?'.
    Devolve (rotulo, destino) ou (None, '')."""
    for row in cham:
        if is_strict_match(memb, row.get("NmTabelaDestino", "")):
            return "Modernizada (Chameleon: destino)", row.get("NmTabelaDestino", "")
        if is_strict_match(memb, row.get("NmTabelaOrigem", "")):
            return "Ajuste identificado (Chameleon: origem)", row.get("NmTabelaDestino", "")
    dst = override.get(memb)
    if dst:
        return "Modernizada (lista autoritativa)", dst
    return None, ""


def main():
    print(f"== Levantamento .sas7bdat-como-tabela — prod {FQ} (READ-ONLY) ==\n")
    q = connect()

    alvo = q(
        "SELECT chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, "
        "areas, escopo_indi, modernizada_auto, etapa, status, responsavel, observacao, orfao "
        f"FROM {FQ}.sas_inputs_monitor "
        "WHERE categoria = 'arquivo' AND lower(artifact) LIKE '%.sas7bdat'")
    tabelas = q(
        "SELECT chave_canonica, artifact, escopo_indi, modernizada_auto, etapa, status, "
        "qtd_projetos, areas "
        f"FROM {FQ}.sas_inputs_monitor WHERE categoria = 'tabela'")
    outputs = q(
        "SELECT chave_canonica, artifact, qtd_produtores, qtd_criadores, areas "
        f"FROM {FQ}.sas_outputs_monitor")
    egp_in = q(
        "SELECT chave_canonica, projeto, area, escopo_indi "
        f"FROM {FQ}.sas_egp_inputs WHERE categoria = 'arquivo'")
    try:
        links = q(f"SELECT chave_canonica, projeto, link_broken FROM {FQ}.sas_egp_input_link")
    except Exception as e:                                   # tabela pode não existir
        print(f"  (sas_egp_input_link indisponível: {e})")
        links = []

    print(f"  população .sas7bdat como 'arquivo' : {len(alvo)}")
    print(f"  universo de inputs 'tabela'        : {len(tabelas)}")
    print(f"  outputs do corpus                  : {len(outputs)}")

    cham = load_chameleon_data(CHAMELEON_CSV_PATH)
    override = load_modernization_override(MODERN_OVERRIDE_CSV_PATH)

    # índices por MEMBRO
    tab_por_memb = collections.defaultdict(list)
    for r in tabelas:
        tab_por_memb[membro_tabela(r["artifact"])].append(r)
    out_por_memb = collections.defaultdict(list)
    for r in outputs:
        out_por_memb[membro_tabela(r["artifact"])].append(r)
    egps_por_chave = collections.defaultdict(list)
    for r in egp_in:
        egps_por_chave[r["chave_canonica"]].append(r)
    quebrados = collections.defaultdict(lambda: [0, 0])      # chave -> [quebrados, total]
    for r in links:
        st = quebrados[r["chave_canonica"]]
        st[1] += 1
        if str(r.get("link_broken")).lower() in ("true", "1"):
            st[0] += 1

    linhas, buckets = [], collections.Counter()
    for r in alvo:
        auto = r.get("modernizada_auto") or ""
        etapa, status = r.get("etapa") or "", r.get("status") or ""
        resolvido = is_modern(etapa, auto, status)
        memb = membro(r["artifact"])
        qb, qt = quebrados.get(r["chave_canonica"], [0, 0])
        sem_vinculo_ativo = qt > 0 and qb >= qt

        gemeos = tab_por_memb.get(memb, [])
        gemeos_mod = [g for g in gemeos
                      if is_modern(g.get("etapa") or "", g.get("modernizada_auto") or "",
                                   g.get("status") or "")]
        prods = out_por_memb.get(memb, [])
        criado = [p for p in prods if int(p.get("qtd_criadores") or 0) > 0]
        cham_rot, cham_dst = simula_modernizacao(memb, cham, override)

        # bucket (prioridade: sinal mais forte de "já resolvido em outro lugar")
        if resolvido:
            bucket, acao = "0. já resolvido", "nenhuma (já modernizado/sanitizado)"
        elif cham_rot and cham_rot.startswith("Modernizada"):
            bucket = "A. modernizada invisível"
            acao = f"reclassificar p/ tabela → vira Disponível ({cham_dst}); ou Sanitizar"
        elif gemeos_mod:
            bucket = "B. gêmeo tabela já resolvido"
            acao = "Sanitizar o arquivo (mesma tabela já resolvida como 'tabela')"
        elif gemeos:
            bucket = "C. gêmeo tabela pendente"
            acao = "desduplicar: Sanitizar o arquivo, manter a linha 'tabela'"
        elif criado:
            bucket = "D. produzida no corpus"
            acao = "é dependência intra-corpus (EGP→EGP), não arquivo externo"
        elif cham_rot:
            bucket = "E. ajuste identificado"
            acao = f"existe modernizada correspondente ({cham_dst}) — decidir remap"
        else:
            bucket = "F. tabela SAS externa"
            acao = "reclassificar p/ tabela SAS e entrar na esteira de ingestão"
        buckets[bucket] += 1

        linhas.append({
            "bucket": bucket,
            "acao_sugerida": acao,
            "chave_canonica": r["chave_canonica"],
            "artifact": r["artifact"],
            "membro": memb,
            "origem": r.get("origem") or "",
            "escopo_indi": r.get("escopo_indi"),
            "qtd_projetos": r.get("qtd_projetos"),
            "areas": r.get("areas") or "",
            "modernizada_auto": auto,
            "etapa_humana": etapa,
            "status_humano": status,
            "etapa_efetiva": eff_etapa(etapa, auto),
            "status_efetivo": eff_status(status, etapa, auto),
            "resolvido": resolvido,
            "sem_vinculo_ativo": sem_vinculo_ativo,
            "orfao": r.get("orfao"),
            "gemeo_tabela_n": len(gemeos),
            "gemeo_tabela": " | ".join(sorted({g["artifact"] for g in gemeos})[:5]),
            "gemeo_resolvido_n": len(gemeos_mod),
            "produzido_no_corpus": bool(criado),
            "produtores": " | ".join(sorted({p["artifact"] for p in criado})[:5]),
            "chameleon_veredito": cham_rot or "",
            "chameleon_destino": cham_dst,
            "egps_consumidores": len(egps_por_chave.get(r["chave_canonica"], [])),
        })

    linhas.sort(key=lambda x: (x["bucket"], -int(x["qtd_projetos"] or 0), x["artifact"]))
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=";")
        wr.writeheader()
        wr.writerows(linhas)

    # ------------------------------------------------------------------ sumário
    pend = [x for x in linhas if not x["resolvido"]]
    pend_esc = [x for x in pend if x["escopo_indi"] in (True, "true", "True")]
    print(f"\n{'='*72}")
    print(f"TOTAL .sas7bdat como 'arquivo' : {len(linhas)}")
    print(f"  pendentes (não modernizados) : {len(pend)}")
    print(f"  └ dentro do escopo Indicium  : {len(pend_esc)}")
    print(f"  auto='Disponível' entre eles : "
          f"{sum(1 for x in linhas if x['modernizada_auto'] == 'Disponível')}  "
          f"(esperado 0 — file_in não entra na árvore de modernização)")
    print(f"\n{'bucket':<32} {'total':>6} {'pend':>6} {'escopo':>7}")
    for b in sorted(buckets):
        tot = buckets[b]
        p = sum(1 for x in pend if x["bucket"] == b)
        e = sum(1 for x in pend_esc if x["bucket"] == b)
        print(f"{b:<32} {tot:>6} {p:>6} {e:>7}")
    print(f"\nCSV → {OUT_CSV}")

    # ------------------------------------------------------------------ markdown
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(f"# Inputs `.sas7bdat` classificados como arquivo — na verdade tabelas SAS\n\n")
        f.write(f"Fonte: **prod** `{FQ}` (read-only) · {STAMP}\n\n")
        f.write("## Causa raiz\n\n")
        f.write("`orchestrator_inventory.py:1270` — a árvore de decisão de modernização "
                "(Chameleon → RepMap → Inventário → override) roda só para "
                "`cat in ('table_in','table_out')`. Um `file_in` `.sas7bdat` nunca entra: "
                "`modernizada_auto` fica `'A ingerir'` mesmo com a tabela já no BigQuery.\n\n")
        f.write("`publish_to_databricks.py:366` — o dedup `.sas7bdat` ↔ `lib.membro` só "
                "colapsa DENTRO do mesmo projeto; arquivo no EGP A + tabela no EGP B "
                "viram duas chaves para o mesmo dataset.\n\n")
        f.write("## Números\n\n")
        f.write(f"| recorte | n |\n|---|---|\n")
        f.write(f"| `.sas7bdat` como `arquivo` | {len(linhas)} |\n")
        f.write(f"| pendentes (não modernizados) | {len(pend)} |\n")
        f.write(f"| pendentes no escopo Indicium | {len(pend_esc)} |\n\n")
        f.write("## Buckets\n\n| bucket | total | pendentes | no escopo | ação |\n")
        f.write("|---|---:|---:|---:|---|\n")
        acoes = {x["bucket"]: x["acao_sugerida"] for x in linhas}
        for b in sorted(buckets):
            p = sum(1 for x in pend if x["bucket"] == b)
            e = sum(1 for x in pend_esc if x["bucket"] == b)
            f.write(f"| {b} | {buckets[b]} | {p} | {e} | {acoes.get(b, '')} |\n")
        f.write(f"\n## Amostra (pendentes, por nº de EGPs)\n\n")
        f.write("| artifact | membro | EGPs | escopo | bucket | gêmeo tabela |\n")
        f.write("|---|---|---:|:-:|---|---|\n")
        for x in sorted(pend, key=lambda r: -int(r["qtd_projetos"] or 0))[:40]:
            esc = "✓" if x["escopo_indi"] in (True, "true", "True") else ""
            f.write(f"| `{x['artifact']}` | {x['membro']} | {x['qtd_projetos']} | {esc} | "
                    f"{x['bucket']} | {x['gemeo_tabela'] or '—'} |\n")
        f.write(f"\nDetalhe completo: `{os.path.basename(OUT_CSV)}`\n")
    print(f"MD  → {OUT_MD}")


if __name__ == "__main__":
    main()

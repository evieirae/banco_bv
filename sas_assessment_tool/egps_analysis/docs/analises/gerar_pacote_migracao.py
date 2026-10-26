# -*- coding: utf-8 -*-
"""Gera o pacote de comunicação da migração SAS a partir dos dados de PRODUÇÃO do app.

Saídas (em docs/analises/):
  BV_Migracao_SAS_Ondas_Destravamento_<data>.html / .pdf   -> plano de 3 ondas
  BV_Migracao_SAS_Pacote_Reunioes_<data>.html   / .pdf     -> uma página por responsável BV
  BV_Migracao_SAS_QuickWins_Ingestao_<data>.csv            -> os 108 EGPs com a coluna `onda`

Os HTML são autocontidos (abrem em qualquer navegador, sem Claude) e já vêm com CSS de
impressão: Ctrl+P -> "Salvar como PDF" reproduz o PDF. O PDF é gerado direto se o
WeasyPrint estiver disponível (opcional):

    pip install --target /tmp/pylibs weasyprint
    PYTHONPATH=/tmp/pylibs python gerar_pacote_migracao.py

Uso:
    python gerar_pacote_migracao.py [--data 2026-08-29] [--profile bv]

Requer `databricks-sdk` (está em egps_analysis/venv) e o profile do Databricks com acesso a
bv_dev_db.monitoramento_sas. Ver docs/analises/ para as demais análises.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import csv
import html
import os
import sys

WAREHOUSE_ID = "5922c26f81f1bbdd"
CATALOG, SCHEMA = "bv_dev_db", "monitoramento_sas"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_BACKEND = os.environ.get("APP_BACKEND", os.path.join(OUT_DIR, "..", "..", "app", "backend"))

# Pastas da onda 2: já têm item em UAT, logo acesso/dono/caminho estão resolvidos.
LIBS_ONDA2 = {"CARNEIRO", "PERF_CL", "MOVTO"}
ETAPAS_EM_VOO = {"Recebido", "Ingestão UAT", "Ingestão PRD", "Aplicação de Grant", "Pré-Working"}


# --------------------------------------------------------------------------- dados
def carrega(profile: str) -> dict:
    """Lê o recorte pelo BACKEND DO APP (`_frontier_egps('indi_deps')`), não por SQL próprio.

    Garante que o universo é exatamente o que o app mostra: escopo Indicium ∪ dependências
    transitivas (arestas podadas por produtor canônico e vias resolvidas, sem expandir
    despriorizados) ∪ ex-dependências contabilizadas. Também herda a semântica de
    pendência do app (`_aingerir`), que trata vínculo quebrado e Sanitizado como resolvidos.
    """
    os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile)
    os.environ.setdefault("PUBLISH_SCHEMA", SCHEMA)
    os.environ.setdefault("DATABRICKS_WAREHOUSE_ID", WAREHOUSE_ID)
    sys.path.insert(0, os.path.abspath(APP_BACKEND))
    import main as M  # noqa: PLC0415

    frontier, base = M._frontier_egps("indi_deps", [])
    plano = set(frontier) | set(M._ex_deps_contab(frontier, base))
    desprior = plano & M._egps_fora_backlog()          # 'Despriorizado e Contabilizado'
    nivel = M._transitive_upstream(base, M._dep_of_map(M._edges_pruned()),
                                  no_expand=M._egps_fora_backlog())

    pipe = {r["projeto"]: r for r in M.run_sql(
        f"SELECT projeto, coalesce(etapa_migracao,'') etapa, coalesce(status_migracao,'') status, "
        f"coalesce(cast(mes_prioridade as string),'0') mes, coalesce(responsavel_bv,'') resp_bv "
        f"FROM {M.T_PIPE}")}
    # ATENÇÃO: etapa 'Migrado' é só o NOME da última casa da esteira — não significa concluído.
    # Em 31/08/2026: 66 EGPs em Migrado/'Despriorizado e Contabilizado', 9 em Migrado/Migrado e
    # 1 em Migrado/'Em Andamento'. Concluído exige etapa E status; nunca inferir pela etapa.
    migrados = {p for p in plano
                if pipe.get(p, {}).get("etapa") == "Migrado" and pipe.get(p, {}).get("status") == "Migrado"}
    alvo_ids = plano - desprior - migrados

    lnk = "coalesce(l.link_broken, false)"
    pend_rows = M.run_sql(
        f"SELECT e.projeto, i.artifact, i.categoria, "
        f"{M._eff_etapa('i.etapa', 'e.modernizada_auto')} AS etapa, "
        f"{M._eff_status_input('i.status', 'i.etapa', 'e.modernizada_auto')} AS status, "
        f"coalesce(i.paths_fisicos, '') AS path, i.qtd_projetos "
        f"FROM {M.T_EGP} e JOIN {M.T_IN} i ON i.chave_canonica = e.chave_canonica "
        f"LEFT JOIN {M.T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE {M._aingerir('i.etapa', 'e.modernizada_auto', 'i.status', lnk)}")
    tot_rows = M.run_sql(
        f"SELECT e.projeto, count(DISTINCT e.chave_canonica) AS n "
        f"FROM {M.T_EGP} e LEFT JOIN {M.T_IN} i ON i.chave_canonica = e.chave_canonica "
        f"LEFT JOIN {M.T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE NOT {M._sanitizado('i.etapa', 'e.modernizada_auto', 'i.status', lnk)} "
        f"GROUP BY e.projeto")
    inputs_total = {r["projeto"]: int(r["n"] or 0) for r in tot_rows}

    # despriorizado que ainda produz tabela lida por EGP vivo = a única exceção em que
    # "não atuar" é falso (a decisão dele segura outro EGP).
    bloqueia_vivos = collections.defaultdict(set)
    for e in M._edges_pruned():
        if e.get("depende_do") in desprior and e.get("projeto_alvo") in alvo_ids:
            bloqueia_vivos[e["depende_do"]].add(e["projeto_alvo"])

    egps = {}
    for p in sorted(plano):
        pi = pipe.get(p, {})
        egps[p] = dict(projeto=p, etapa=pi.get("etapa") or "(sem etapa)",
                       status=pi.get("status") or "(sem status)", mes=pi.get("mes") or "0",
                       resp_bv=pi.get("resp_bv") or "(sem responsável)",
                       inputs_total=str(inputs_total.get(p, 0)),
                       dep_nivel=int(nivel.get(p, 0) or 0))
    matriz = collections.Counter((egps_etapa := pipe.get(p, {}).get("etapa") or "(vazia)",
                                  pipe.get(p, {}).get("status") or "(vazio)") for p in plano)
    return dict(egps=egps, plano=plano, desprior=desprior, migrados=migrados, alvo_ids=alvo_ids,
                pend_rows=pend_rows, bloqueia_vivos=bloqueia_vivos, base=base, matriz=matriz)


def em_voo(r: dict) -> bool:
    return r["etapa"] in ETAPAS_EM_VOO


def eh_arquivo(r: dict) -> bool:
    """Sem pasta para liberar: arquivo, ou tabela sem caminho físico no inventário."""
    return not (r["categoria"] == "tabela" and r["path"])


def libname(r: dict) -> str:
    return r["artifact"].split(".")[0].upper() if r["categoria"] == "tabela" else ""


def calcula(d: dict) -> dict:
    """Deriva as ondas sobre o UNIVERSO DE ATUAÇÃO = plano − despriorizados − migrados."""
    egps, alvo_ids = d["egps"], d["alvo_ids"]
    alvo = {p: e for p, e in egps.items() if p in alvo_ids}
    pend = collections.defaultdict(list)
    for r in d["pend_rows"]:
        if r["projeto"] in alvo_ids:
            pend[r["projeto"]].append(r)

    def na_onda12(r: dict) -> bool:
        return em_voo(r) or libname(r) in LIBS_ONDA2

    # Onda 3 = pendências que sobram nos EGPs que ficam a <=2 itens depois das ondas 1 e 2.
    onda3 = set()
    for p, ps in pend.items():
        falta = [r for r in ps if not na_onda12(r)]
        if 0 < len(falta) <= 2:
            onda3.update(r["artifact"] for r in falta)

    def coberto(r: dict) -> bool:
        return na_onda12(r) or r["artifact"] in onda3

    def onda_de(ps: list[dict]) -> int:
        if not ps:
            return 0
        if all(em_voo(r) for r in ps):
            return 1
        if all(na_onda12(r) for r in ps):
            return 2
        if all(coberto(r) for r in ps):
            return 3
        return 4

    return dict(egps=egps, alvo=alvo, pend=pend, onda3=onda3, coberto=coberto, onda_de=onda_de,
                na_onda12=na_onda12, desprior=d["desprior"], migrados=d["migrados"],
                plano=d["plano"], bloqueia_vivos=d["bloqueia_vivos"])


# --------------------------------------------------------------------------- CSS
def css(data_br: str) -> str:
    return """
:root{
  --ground:#EFF2F5; --surface:#FFFFFF; --surface-2:#F5F7F9;
  --line:#D6DDE4; --line-soft:#E6EBF0;
  --ink:#111820; --ink-2:#47555F; --ink-3:#6B7A86;
  --accent:#B4531A; --voo:#0C6C60; --voo-soft:#DBEDE9;
  --espera:#8A6206; --espera-soft:#F4E9CE;
  --grave:#993030; --grave-soft:#F3DEDE;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0E1216; --surface:#161B21; --surface-2:#1C232A;
    --line:#2B343D; --line-soft:#222A32;
    --ink:#E5EAEF; --ink-2:#A8B5C0; --ink-3:#84929F;
    --accent:#E4874A; --voo:#6ECFBF; --voo-soft:#12332E;
    --espera:#DDB055; --espera-soft:#332913;
    --grave:#E28C8C; --grave-soft:#351D1D;
  }
}
:root[data-theme="dark"]{
  --ground:#0E1216; --surface:#161B21; --surface-2:#1C232A;
  --line:#2B343D; --line-soft:#222A32;
  --ink:#E5EAEF; --ink-2:#A8B5C0; --ink-3:#84929F;
  --accent:#E4874A; --voo:#6ECFBF; --voo-soft:#12332E;
  --espera:#DDB055; --espera-soft:#332913;
  --grave:#E28C8C; --grave-soft:#351D1D;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"IBM Plex Sans","Segoe UI",system-ui,"DejaVu Sans",sans-serif;
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1020px;margin:0 auto;padding:44px 22px 90px;display:flex;flex-direction:column;gap:34px}
h1,h2,h3{font-family:"Bricolage Grotesque","IBM Plex Sans","Segoe UI",sans-serif;margin:0;line-height:1.12;text-wrap:balance}
h1{font-size:clamp(2rem,5vw,3rem);font-weight:800;letter-spacing:-.02em}
h2{font-size:1.6rem;font-weight:800;letter-spacing:-.02em}
h3{font-size:.98rem;font-weight:600;color:var(--ink)}
p{margin:0}
.eyebrow{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.7rem;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.sub{color:var(--ink-3);font-size:.85rem}
.pad{padding:0 22px 4px}
.mono{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.83rem}
header.capa{display:flex;flex-direction:column;gap:14px;border-bottom:1px solid var(--line);padding-bottom:30px}
header.capa p.lede{font-size:1.05rem;color:var(--ink-2);max-width:66ch}
header.capa strong{color:var(--ink);font-weight:600}
.indice{display:flex;flex-wrap:wrap;gap:8px;font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.78rem}
.indice a{color:var(--ink-2);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:4px 11px;background:var(--surface)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:12px;overflow:hidden}
.metric{background:var(--surface);padding:16px 18px;display:flex;flex-direction:column;gap:4px}
.metric .n{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;font-size:1.95rem;font-weight:800;
  line-height:1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.metric .n.hi{color:var(--accent)}
.metric .k{font-size:.8rem;color:var(--ink-3);line-height:1.35}
section.bloco{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.cab{display:flex;gap:16px;align-items:flex-start;padding:22px 22px 18px;flex-wrap:wrap}
.numeral{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;font-size:2.3rem;font-weight:800;
  line-height:.9;color:var(--accent);min-width:40px;font-variant-numeric:tabular-nums}
.cab .txt{flex:1 1 360px;display:flex;flex-direction:column;gap:7px}
.cab .txt p{font-size:.95rem;color:var(--ink-2);max-width:64ch}
.ledger{display:flex;gap:14px;flex-wrap:wrap;font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;
  font-size:.79rem;font-variant-numeric:tabular-nums}
.ledger .cost{color:var(--ink-3)}
.ledger .gain{color:var(--accent);font-weight:500}
.placar{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:1px;background:var(--line-soft);
  border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line-soft)}
.placar .m{background:var(--surface);padding:14px 16px;display:flex;flex-direction:column;gap:2px}
.placar .n{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;font-size:1.65rem;font-weight:800;
  line-height:1;font-variant-numeric:tabular-nums}
.placar .n.hi{color:var(--accent)}
.placar .k{font-size:.75rem;color:var(--ink-3);line-height:1.3}
section.bloco h3{padding:20px 22px 9px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th{text-align:left;font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-weight:500;font-size:.68rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);padding:9px 22px;background:var(--surface-2);
  border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line-soft);white-space:nowrap}
td{padding:11px 22px;border-bottom:1px solid var(--line-soft);vertical-align:top}
tr:last-child td{border-bottom:0}
td.egp{font-weight:500;min-width:220px}
td.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;color:var(--ink-2)}
td.mono{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.8rem;color:var(--ink-2);
  overflow-wrap:anywhere;word-break:break-word}
.chip{display:inline-block;font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.67rem;
  padding:2px 7px;border-radius:4px;white-space:nowrap}
.c-voo{background:var(--voo-soft);color:var(--voo)}
.c-esp{background:var(--espera-soft);color:var(--espera)}
.c-gra{background:var(--grave-soft);color:var(--grave)}
.c-mes{background:var(--surface-2);color:var(--ink-3);border:1px solid var(--line-soft)}
.dirs{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:1px;background:var(--line-soft)}
.dir{background:var(--surface);padding:16px 22px;display:flex;flex-direction:column;gap:7px}
.dir .lib{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.7rem;letter-spacing:.1em;
  color:var(--accent);text-transform:uppercase}
.dir .path{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.82rem;word-break:break-all}
.dir .stat{font-size:.84rem;color:var(--ink-3);font-variant-numeric:tabular-nums}
.note{padding:16px 22px;background:var(--surface-2);border-top:1px solid var(--line-soft);
  font-size:.87rem;color:var(--ink-2)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:24px 22px;
  display:flex;flex-direction:column;gap:13px}
.panel p{font-size:.94rem;color:var(--ink-2);max-width:70ch}
.panel ul,.fechar ol{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:8px;
  font-size:.94rem;color:var(--ink-2);max-width:70ch}
.panel li strong{color:var(--ink);font-weight:600}
section.pessoa{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
section.pessoa .cabp{padding:24px 22px 2px;display:flex;flex-direction:column;gap:6px}
.tese{padding:12px 22px 20px;font-size:.95rem;color:var(--ink-2);max-width:70ch}
section.pessoa h3{padding:20px 22px 9px}
.fechar{background:var(--surface-2);border-top:1px solid var(--line-soft);padding:20px 22px 22px;margin-top:20px}
.fechar h3{padding:0 0 8px}
footer{font-size:.83rem;color:var(--ink-3);border-top:1px solid var(--line);padding-top:20px;
  display:flex;flex-direction:column;gap:7px;max-width:78ch}
footer code{font-family:"IBM Plex Mono","DejaVu Sans Mono",monospace;font-size:.79rem;color:var(--ink-2)}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* ---------- impressão / PDF ---------- */
@page{
  size:A4; margin:14mm 13mm 16mm;
  @bottom-center{
    content:"Migração SAS · Cobrança · dados de __DATA__ · página " counter(page) " de " counter(pages);
    font-family:"IBM Plex Sans","DejaVu Sans",sans-serif; font-size:7.5pt; color:#6B7A86;
  }
}
@media print{
  :root{--ground:#FFFFFF;--surface:#FFFFFF;--surface-2:#F7F9FA;--line:#C9D2DA;--line-soft:#E2E8ED;
        --ink:#0F161D;--ink-2:#3E4C56;--ink-3:#69777F}
  body{background:#fff;font-size:9.5pt;line-height:1.45}
  .wrap{max-width:none;margin:0;padding:0;display:block}
  .wrap > *{margin-bottom:11pt}
  h1{font-size:21pt} h2{font-size:14pt} h3{font-size:10pt;padding:14pt 9pt 6pt}
  header.capa p.lede,.tese,.cab .txt p,.panel p{font-size:9.6pt}
  .metrics,.placar,.dirs{break-inside:avoid}
  tr,.dir,.metric,.ledger{break-inside:avoid}
  h1,h2,h3,.cab,.cabp{break-after:avoid}
  .fechar{break-inside:avoid}
  section.pessoa{break-before:page}
  .indice{display:none}
  .metrics,.placar,.dirs{display:table;width:100%;table-layout:fixed;border-collapse:collapse;border-radius:0}
  .metric,.placar .m,.dir{display:table-cell;vertical-align:top;padding:7pt 9pt;border:1px solid #E2E8ED}
  .metric > span,.placar .m > span,.dir > span{display:block}
  .metric .n,.placar .n{font-size:14pt}
  .metric .k,.placar .k{font-size:7pt}
  .cab{padding:16pt 9pt 12pt} .numeral{font-size:19pt}
  .tese{padding:9pt 9pt 14pt}
  section.pessoa .cabp{padding:16pt 9pt 0}
  .note,.pad,.fechar,.panel{padding-left:9pt;padding-right:9pt}
  table{font-size:8.3pt;table-layout:fixed;width:100%} th{padding:5pt 9pt;font-size:6.6pt} td{padding:5pt 9pt}
  td,th{overflow-wrap:anywhere;word-break:break-word}
  td.egp{min-width:0} .mono,td.mono,.chip,.dir .path{font-size:7.5pt}
  .scroll{overflow:visible}
  .fechar ol,.panel ul{font-size:9.2pt}
  footer{font-size:7.6pt;break-inside:avoid}
  a{text-decoration:none}
}
""".replace("__DATA__", data_br)


def pagina(titulo: str, corpo: str, data_br: str) -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titulo)} · Migração SAS BV</title>
<meta name="description" content="Análise dos dados do app de monitoramento da migração SAS — Cobrança, {data_br}.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{css(data_br)}</style>
</head>
<body>
{corpo}
</body>
</html>
"""


E = lambda s: html.escape(str(s))


def fmt(n) -> str:
    """1267 -> '1.267' (padrão pt-BR)."""
    return f"{int(n):,}".replace(",", ".")


def chips_mes(mes) -> str:
    m = str(mes)
    return f"<span class='chip c-mes'>{'sem mês' if m in ('0', '') else 'mês ' + m}</span>"


def tabela(cabecalho: list[str], linhas: list[str]) -> str:
    ths = "".join(f"<th>{E(c)}</th>" for c in cabecalho)
    return f"<div class='scroll'><table><thead><tr>{ths}</tr></thead><tbody>{''.join(linhas)}</tbody></table></div>"


# --------------------------------------------------------------------- página 1: ondas
def _lista_curta(nomes, lim=64) -> str:
    """Nomes de EGP encurtados para caber na coluna do PDF, com '+N' no lugar do resto."""
    itens = sorted(x.replace("Cobranças__", "") for x in nomes)
    out, usado = [], 0
    for it in itens:
        if usado + len(it) > lim and out:
            return ", ".join(out) + f" +{len(itens) - len(out)}"
        out.append(it)
        usado += len(it) + 2
    return ", ".join(out)


def pagina_ondas(c: dict, data_br: str) -> tuple[str, dict]:
    alvo, pend, onda_de, na_onda12 = c["alvo"], c["pend"], c["onda_de"], c["na_onda12"]
    ondas = collections.defaultdict(list)
    for p, e in alvo.items():
        ondas[onda_de(pend.get(p, []))].append(p)

    n_alvo = len(alvo)
    n_desprior, n_migrados, n_plano = len(c["desprior"]), len(c["migrados"]), len(c["plano"])
    n_deps = sum(1 for e in alvo.values() if e["dep_nivel"] > 0)
    n_pend_total = len({r["artifact"] for ps in pend.values() for r in ps})
    prontos_final = len(ondas[0]) + len(ondas[1]) + len(ondas[2]) + len(ondas[3])
    uniao = {r["artifact"] for p in ondas[1] + ondas[2] + ondas[3] for r in pend[p]}
    uniao |= {r["artifact"] for ps in pend.values() for r in ps if libname(r) in LIBS_ONDA2}
    inputs_onda1 = {r["artifact"] for p in ondas[1] for r in pend[p]}
    tabelas_onda2 = {r["artifact"] for ps in pend.values() for r in ps if libname(r) in LIBS_ONDA2}
    em_voo_onda2 = {a for a in tabelas_onda2
                    if any(em_voo(r) for ps in pend.values() for r in ps if r["artifact"] == a)}

    # ---- onda 1
    l1 = []
    for p in sorted(ondas[1], key=lambda p: (int(alvo[p]["mes"] or 99), p)):
        itens = "<br>".join(
            f"<span class='mono'>{E(r['artifact'])}</span> <span class='chip c-voo'>{E(r['etapa'])}</span>"
            for r in sorted(pend[p], key=lambda r: r["artifact"]))
        l1.append(f"<tr><td class='egp'>{E(p.replace('Cobranças__', ''))}</td>"
                  f"<td class='num'>{chips_mes(alvo[p]['mes'])}</td><td>{itens}</td></tr>")

    # ---- onda 2
    dirs2 = {}
    for ps in pend.values():
        for r in ps:
            if libname(r) in LIBS_ONDA2:
                d = dirs2.setdefault(r["path"], dict(lib=libname(r), tab=set(), voo=set()))
                d["tab"].add(r["artifact"])
                if em_voo(r):
                    d["voo"].add(r["artifact"])
    cards = "".join(
        f"<div class='dir'><span class='lib'>{E(d['lib'])}</span><span class='path'>{E(path)}</span>"
        f"<span class='stat'>{len(d['tab'])} tabelas pendentes · {len(d['voo'])} já em voo</span></div>"
        for path, d in sorted(dirs2.items(), key=lambda kv: -len(kv[1]["tab"])))
    l2 = [f"<tr><td class='egp'>{E(p.replace('Cobranças__', ''))}</td>"
          f"<td class='num'>{chips_mes(alvo[p]['mes'])}</td><td class='num'>{len(pend[p])}</td></tr>"
          for p in sorted(ondas[2], key=lambda p: (int(alvo[p]["mes"] or 99), -len(pend[p])))]

    # ---- onda 3
    l3, inputs_onda3 = [], set()
    for p in sorted(ondas[3], key=lambda p: (int(alvo[p]["mes"] or 99), p)):
        falta = [r for r in pend[p] if not na_onda12(r)]
        inputs_onda3.update(r["artifact"] for r in falta)
        art = "<br>".join(f"<span class='mono'>{E(r['artifact'])}</span>"
                          + (" <span class='chip c-esp'>arquivo</span>" if eh_arquivo(r) else "")
                          for r in falta)
        onde = "<br>".join(dict.fromkeys(E(r["path"]) if r["path"] else "pedir à área" for r in falta))
        l3.append(f"<tr><td class='egp'>{E(p.replace('Cobranças__', ''))}</td>"
                  f"<td class='num'>{chips_mes(alvo[p]['mes'])}</td><td>{art}</td>"
                  f"<td class='mono'>{onde}</td></tr>")
    arq_onda3 = sum(1 for a in inputs_onda3 if "." not in a.split("/")[-1] or not a.isupper())

    # ---- cauda longa
    libs = collections.Counter()
    tabs_por_lib = collections.defaultdict(set)
    egps_por_lib = collections.defaultdict(set)
    paths_por_lib = {}
    for p in ondas[4]:
        for r in pend[p]:
            if r["categoria"] == "tabela" and r["path"]:
                lb = libname(r)
                libs[lb] += 1
                tabs_por_lib[lb].add(r["artifact"])
                egps_por_lib[lb].add(p)
                paths_por_lib[lb] = r["path"]
    top_libs = sorted(tabs_por_lib, key=lambda k: -len(tabs_por_lib[k]))[:3]
    itens_libs = "".join(
        f"<li><strong>{E(lb)}</strong> — {len(tabs_por_lib[lb])} tabelas em "
        f"<span class='mono'>{E(paths_por_lib[lb])}</span>, servindo {len(egps_por_lib[lb])} EGPs.</li>"
        for lb in top_libs)
    resta_inputs = n_pend_total - len(uniao)

    # ---- input de maior alcance na onda 1
    alcance = collections.Counter()
    for p, ps in pend.items():
        for r in ps:
            alcance[r["artifact"]] += 1
    maior = max(inputs_onda1, key=lambda a: alcance[a]) if inputs_onda1 else ""

    bv = {p2: v for p2, v in c["bloqueia_vivos"].items() if v}
    if bv:
        linhas_bv = "".join(
            f"<tr><td class='egp'>{E(p2.replace('Cobranças__', ''))}</td>"
            f"<td class='num'>{len(v)}</td>"
            f"<td class='mono'>{E(_lista_curta(v))}</td></tr>"
            for p2, v in sorted(bv.items(), key=lambda kv: -len(kv[1])))
        excecao = (f"<p>A exceção, e é a única: <strong>{len(bv)} desses despriorizados ainda produzem tabela lida "
                   f"por EGP vivo</strong>. Aqui “não atuar” é falso — não é ingestão, é uma decisão: ou o consumidor "
                   f"passa a receber a tabela por ingestão, ou o produtor volta ao escopo.</p>"
                   + tabela(["Despriorizado", "EGPs vivos que dependem dele", "Quais"], linhas_bv))
    else:
        excecao = "<p>Nenhum despriorizado produz tabela lida por EGP vivo — não há exceção a tratar.</p>"

    painel_desprior = f"""<div class="panel">
    <h2>Os {n_desprior} despriorizados: não requer atuação</h2>
    <p>Estão fora de todas as contas deste documento — não entram no universo de {n_alvo}, não aparecem nas ondas
    e não somam pendência. São os EGPs com status <em>Despriorizado e Contabilizado</em>: seguem no plano para efeito
    de contabilização de esforço, mas não puxam dependência (regra <span class="mono">no_expand</span> do app) e não
    voltam ao backlog de conversão. Continuam no CSV, marcados na coluna <span class="mono">universo</span>, para
    auditoria — nunca somem sem rastro.</p>
    {excecao}
  </div>

  """
    corpo = f"""<div class="wrap">
  <header class="capa">
    <p class="eyebrow">Migração SAS · Cobrança · dados do app em {E(data_br)}</p>
    <h1>Ondas de destravamento</h1>
    <p class="lede">Recorte: <strong>escopo Indicium + dependências</strong> ({fmt(n_plano)} EGPs no plano), menos
    {n_migrados} já migrados e {n_desprior} despriorizados — sobram <strong>{n_alvo} EGPs em que atuar</strong>
    ({n_alvo - n_deps} do escopo indicado, {n_deps} puxados como dependência).</p>
    <p class="lede">Desses {n_alvo}, apenas {len(ondas[0])} têm todos os inputs disponíveis; os outros
    {n_alvo - len(ondas[0])} esperam por <strong>{fmt(n_pend_total)} inputs</strong>. Mas a fila não é plana:
    <strong>{len(uniao)} inputs bem escolhidos deixam {prontos_final} EGPs prontos para conversão</strong> —
    e {len(inputs_onda1)} deles já estão em movimento no funil de ingestão.</p>
  </header>

  <div class="metrics">
    <div class="metric"><span class="n">{n_alvo}</span><span class="k">EGPs em que atuar — escopo Indicium + dependências, fora migrados e despriorizados</span></div>
    <div class="metric"><span class="n">{len(ondas[0])}</span><span class="k">prontos hoje — sem nenhuma pendência de input</span></div>
    <div class="metric"><span class="n hi">{prontos_final}</span><span class="k">prontos ao fim das 3 ondas abaixo</span></div>
    <div class="metric"><span class="n hi">{len(uniao)}</span><span class="k">inputs a ingerir para chegar lá, de {fmt(n_pend_total)} pendentes</span></div>
  </div>

  <section class="bloco">
    <div class="cab"><span class="numeral">1</span><div class="txt">
      <h2>Terminar o que já está em voo</h2>
      <p>{len(inputs_onda1)} inputs já saíram do “A Receber” e estão em UAT, Grant ou recebidos. Nenhum EGP abaixo
      precisa de nada além deles: fechar essas pendências converte trabalho já pago em {len(ondas[1])} EGPs liberados.</p>
      <div class="ledger"><span class="cost">custo: {len(inputs_onda1)} inputs, todos já iniciados</span>
      <span class="gain">ganho: +{len(ondas[1])} EGPs → {len(ondas[0]) + len(ondas[1])} prontos</span></div>
    </div></div>
    {tabela(["EGP", "Mês", "Falta"], l1)}
    <p class="note"><span class="mono">{E(maior)}</span> é esperado por {alcance[maior]} EGPs do escopo e já está em voo —
    é o input isolado de maior alcance da fila inteira.</p>
  </section>

  <section class="bloco">
    <div class="cab"><span class="numeral">2</span><div class="txt">
      <h2>Fechar três diretórios inteiros</h2>
      <p>Cada libname pendente aponta para exatamente um diretório físico — a ingestão pode ser negociada por pasta,
      não por tabela. Estas três já têm itens em UAT, ou seja: acesso, dono e caminho já resolvidos. Levar as
      {len(tabelas_onda2) - len(em_voo_onda2)} tabelas restantes junto custa pouco a mais do que o que já está sendo feito.</p>
      <div class="ledger"><span class="cost">custo: {len(tabelas_onda2)} tabelas em 3 pastas ({len(em_voo_onda2)} já em voo)</span>
      <span class="gain">ganho: +{len(ondas[2])} EGPs → {len(ondas[0]) + len(ondas[1]) + len(ondas[2])} prontos</span></div>
    </div></div>
    <div class="dirs">{cards}</div>
    {tabela(["EGP que fecha com as três pastas", "Mês", "Pendências"], l2)}
  </section>

  <section class="bloco">
    <div class="cab"><span class="numeral">3</span><div class="txt">
      <h2>{len(inputs_onda3)} inputs avulsos</h2>
      <p>{len(ondas[3])} EGPs estão a uma ou duas tabelas de ficar livres. Nenhuma delas é compartilhada o bastante para
      aparecer no topo de um ranking por alcance — por isso vivem no ponto cego de qualquer priorização por volume,
      e por isso rendem tanto por unidade de esforço.</p>
      <div class="ledger"><span class="cost">custo: {len(inputs_onda3)} inputs</span>
      <span class="gain">ganho: +{len(ondas[3])} EGPs → {prontos_final} prontos</span></div>
    </div></div>
    {tabela(["EGP", "Mês", "Falta", "Onde está"], l3)}
    <p class="note">Os itens marcados como <span class="chip c-esp">arquivo</span> não têm caminho físico no inventário —
    chegam por planilha ou CSV de mão. São o único grupo da lista que depende de conversa com a área, não de acesso a diretório.</p>
  </section>

  <div class="panel">
    <h2>E os outros {len(ondas[4])} EGPs</h2>
    <p>Depois da onda 3 o retorno despenca. Fora das três ondas sobram {fmt(resta_inputs)} dos {fmt(n_pend_total)} inputs pendentes,
    espalhados pelos {len(ondas[4])} EGPs restantes — a maior parte em bibliotecas pessoais de analista, com uma pasta e um dono cada.</p>
    <ul>{itens_libs}</ul>
    <p>Para esses, ingerir tabela a tabela é o caminho mais caro possível. A decisão que realmente move o ponteiro é
    anterior à ingestão: ou a área confirma que o EGP continua no escopo (e aí se ingere a pasta inteira de uma vez),
    ou ele entra na fila de despriorização — que, hoje, é o que de fato vem esvaziando o backlog.</p>
  </div>

  {painel_desprior}<div class="panel">
    <h2>Como esta lista foi montada</h2>
    <ul>
      <li><strong>Recorte:</strong> escopo Indicium ∪ dependências transitivas ∪ ex-dependências contabilizadas —
      o mesmo <span class="mono">indi_deps</span> do app, lido do próprio backend (arestas podadas por produtor
      canônico e vias resolvidas). {fmt(n_plano)} EGPs no plano.</li>
      <li><strong>Universo de atuação:</strong> o plano menos {n_migrados} migrados e {n_desprior} despriorizados —
      {n_alvo} EGPs, dos quais {n_deps} entraram como dependência, não como indicação.</li>
      <li><strong>Pendência:</strong> input do EGP cuja etapa no app não é “Modernizado”. Inputs com status <em>Sanitizado</em> ficam de fora, como o app faz.</li>
      <li><strong>Ordem das ondas:</strong> cobertura gulosa — a cada passo entra a fonte que fecha o maior número de EGPs por esforço, não a que aparece em mais EGPs.</li>
      <li><strong>Em voo:</strong> input em Recebido, Pré-Working, Aplicação de Grant, Ingestão UAT ou Ingestão PRD.</li>
    </ul>
  </div>

  <footer>
    <p>Fonte: <code>{CATALOG}.{SCHEMA}</code> (produção) — <code>sas_escopo</code>, <code>sas_egp_pipeline</code>,
    <code>sas_egp_inputs</code>, <code>sas_inputs_monitor</code>. Consultado em {E(data_br)}.</p>
    <p>Lista completa dos {n_alvo} EGPs, com ondas e pendências item a item, no CSV que acompanha este documento.</p>
    <p>Os meses vêm do plano congelado em <code>sas_egp_pipeline.mes_prioridade</code>; se o plano for repriorizado,
    as ondas continuam válidas, mas a ordem dentro delas muda.</p>
  </footer>
</div>"""
    resumo = dict(n_alvo=n_alvo, prontos_hoje=len(ondas[0]), prontos_final=prontos_final,
                  inputs_uniao=len(uniao), n_pend_total=n_pend_total,
                  onda1=len(ondas[1]), onda2=len(ondas[2]), onda3=len(ondas[3]), cauda=len(ondas[4]),
                  inputs_onda1=len(inputs_onda1), inputs_onda3=len(inputs_onda3),
                  tabelas_onda2=len(tabelas_onda2))
    return corpo, resumo


# ------------------------------------------------------------------ página 2: reuniões
# Roteiro das conversas (29/08/2026). A ordem é: primeiro quem destrava terceiros, depois
# quem fecha a própria carteira, e por último quem só tem decisão de escopo a tomar.
ROTEIRO = [
    ("Rafael Vasconcelos Ribeiro", "Reunião 1", "pauta de acesso", "30 min",
     "A única carteira cujo desbloqueio transborda. Liberar a pasta <span class='mono'>contatos</span> resolve os EGPs "
     "dele e alcança outros 16 EGPs de carteiras de terceiros — <span class='mono'>CONTATOS.AUX_BASE_CYBER</span> "
     "sozinha é esperada por 16 EGPs do escopo ativo.",
     ["Autorização nominal das pastas abaixo, com quem executa e até quando.",
      "Confirmar se as tabelas de <span class='mono'>contatos</span> podem ir em lote único, sem triagem tabela a tabela.",
      "Os arquivos sem caminho físico: quem entrega e em que formato."]),
    ("Cristiano", "Reunião 2", "reunião de fechamento", "20 min",
     "Quase toda a carteira fecha com o que já está em voo — nenhuma ação nova é necessária para esses EGPs. A reunião "
     "existe para resolver o que sobra e encerrar a carteira: primeira carteira 100% concluída do projeto.",
     ["Do EGP restante, quase todas as pendências são arquivos: decidir entrega ou despriorização, na hora.",
      "Confirmar que os EGPs em voo não têm bloqueio de negócio esperando do lado da área."]),
    ("Cleber William De Jesus Saure", "Reunião 3", "piloto do fluxo de arquivos", "45 min",
     "Carteira mais rasa dos grandes — menor mediana de pendências por EGP —, mas boa parte do que resta são arquivos "
     "sem caminho físico. É o menor caso de teste para consertar o fluxo de entrega de arquivo, que hoje trava 219 "
     "itens em todas as carteiras.",
     ["Definir o fluxo de arquivo: quem entrega, onde deposita, com que frequência, quem confirma o recebimento.",
      "Autorizar as pastas próprias (<span class='mono'>csaure/*</span>) e as de <span class='mono'>dpompei</span>/"
      "<span class='mono'>erocha</span> que aparecem na carteira.",
      "Escolher 3 EGPs para servir de piloto do fluxo novo, com data de retorno."]),
    ("Joao Carneiro", "Reunião 4", "acesso + escopo", "60 min",
     "Pauta dupla, e as duas metades precisam ser anunciadas como coisas diferentes. A pasta "
     "<span class='mono'>jcarneiro</span> já entra na onda 2 e rende vários EGPs. O resto da carteira está em "
     "<span class='mono'>grimaldi</span> e <span class='mono'>gh16</span>, sustentando EGPs de mês 5 que não serão "
     "migrados com o funil atual.",
     ["Metade A — confirmar a ingestão em lote de <span class='mono'>/riscosbv/cobranca/jcarneiro</span> (já em andamento).",
      "Metade B — decidir os EGPs da tabela de decisões. Os cinco maiores somam 286 das pendências restantes.",
      "Para os que ficarem no escopo: assumir a ingestão da pasta inteira, não tabela a tabela."]),
    ("Leticia Domingos Duarte", "Reunião 5", "pauta de escopo", "60 min",
     "A maior carteira do projeto e a maior parte das pendências restantes. Nenhuma pasta desta carteira fecha mais de "
     "um EGP sozinha, então pedido de acesso aqui não move o ponteiro. Esta reunião é de decisão, não de liberação.",
     ["As quatro maiores decisões valem 393 pendências — quase metade da carteira. Começar por elas.",
      "Aplicar a regra: acima de 40 pendências e mês ≥ 4, o padrão é despriorizar, salvo justificativa de uso na hora.",
      "Os arquivos sem caminho entram no fluxo definido com o Cleber ou saem do escopo."]),
]
REGRA_PEND, REGRA_MES = 40, 4


def dados_por_responsavel(c: dict) -> dict:
    alvo, pend, onda_de = c["alvo"], c["pend"], c["onda_de"]
    out = {}
    for p, e in alvo.items():
        d = out.setdefault(e["resp_bv"], dict(nome=e["resp_bv"], alvo=0, pronto=[], fecha=[], resta=[],
                                              dirs=collections.Counter(), dirs_tab=collections.defaultdict(set),
                                              arq=0, arq_ex=[], pend_resta=0))
        d["alvo"] += 1
        ps = pend.get(p, [])
        falta = [r for r in ps if not c["coberto"](r)]
        nome = p.replace("Cobranças__", "")
        if not ps:
            d["pronto"].append(dict(egp=nome, mes=e["mes"], etapa=f"{e['etapa']}/{e['status']}"))
        elif not falta:
            d["fecha"].append(dict(egp=nome, mes=e["mes"], n=len(ps),
                                   voo=sorted({r["artifact"] for r in ps if em_voo(r)}),
                                   onda=sorted({r["artifact"] for r in ps if not em_voo(r)})))
        else:
            d["resta"].append(dict(egp=nome, mes=e["mes"], n=len(falta),
                                   arq=sum(1 for r in falta if eh_arquivo(r)),
                                   dirs=sorted({r["path"] for r in falta if not eh_arquivo(r)})))
            d["pend_resta"] += len(falta)
            for r in falta:
                if eh_arquivo(r):
                    d["arq"] += 1
                    if len(d["arq_ex"]) < 5:
                        d["arq_ex"].append(r["artifact"])
                else:
                    d["dirs"][r["path"]] += 1
                    d["dirs_tab"][r["path"]].add(r["artifact"])
    for d in out.values():
        d["pronto"].sort(key=lambda x: int(x["mes"] or 99))
        d["fecha"].sort(key=lambda x: (int(x["mes"] or 99), -x["n"]))
        d["resta"].sort(key=lambda x: -x["n"])
        d["dirs_top"] = [dict(path=k, tabelas=len(d["dirs_tab"][k]), vinculos=v) for k, v in d["dirs"].most_common(6)]
    return out


def pagina_reunioes(c: dict, data_br: str) -> str:
    porresp = dados_por_responsavel(c)
    fora_resp = collections.defaultdict(lambda: [0, 0])   # resp -> [despriorizados, migrados]
    for p2 in c["desprior"]:
        fora_resp[c["egps"][p2]["resp_bv"]][0] += 1
    for p2 in c["migrados"]:
        fora_resp[c["egps"][p2]["resp_bv"]][1] += 1

    def nota_fora(nome):
        d2, m2 = fora_resp.get(nome, [0, 0])
        if not d2 and not m2:
            return ""
        partes = []
        if d2:
            partes.append(f"{d2} despriorizado(s) — fora do backlog, não requer atuação")
        if m2:
            partes.append(f"{m2} já migrado(s)")
        return (f"<p class='sub pad'>Fora dos números acima: {'; '.join(partes)}. "
                f"Aparecem no CSV marcados na coluna <span class='mono'>universo</span>.</p>")
    roteiro = [r for r in ROTEIRO if r[0] in porresp]
    faltantes = sorted(set(porresp) - {r[0] for r in roteiro},
                       key=lambda k: -(len(porresp[k]["pronto"]) + len(porresp[k]["fecha"])))
    secoes = []

    def placar(d):
        itens = [("EGPs na carteira", d["alvo"], ""), ("Prontos hoje", len(d["pronto"]), ""),
                 ("Fecham nas ondas 1-3", len(d["fecha"]), "hi"), ("Seguem travados", len(d["resta"]), ""),
                 ("Pendências restantes", d["pend_resta"], "")]
        return "<div class='placar'>" + "".join(
            f"<div class='m'><span class='n {cl}'>{v}</span><span class='k'>{E(t)}</span></div>"
            for t, v, cl in itens) + "</div>"

    def resolvidos(d):
        linhas = []
        for x in d["pronto"]:
            linhas.append(f"<tr><td class='egp'>{E(x['egp'])}</td><td class='num'>{chips_mes(x['mes'])}</td>"
                          f"<td><span class='chip c-voo'>pronto</span> <span class='sub'>{E(x['etapa'])}</span></td></tr>")
        for x in d["fecha"]:
            det = []
            if x["voo"]:
                det.append("<span class='sub'>em voo:</span> " + ", ".join(f"<span class='mono'>{E(a)}</span>" for a in x["voo"]))
            if x["onda"]:
                det.append("<span class='sub'>nas ondas:</span> " + ", ".join(f"<span class='mono'>{E(a)}</span>" for a in x["onda"]))
            linhas.append(f"<tr><td class='egp'>{E(x['egp'])}</td><td class='num'>{chips_mes(x['mes'])}</td>"
                          f"<td>{'<br>'.join(det)}</td></tr>")
        if not linhas:
            return ""
        return ("<h3>Já resolvido ou a caminho — não precisa de ação nesta reunião</h3>"
                + tabela(["EGP", "Mês", "Situação"], linhas))

    def pedido(d):
        if not d["dirs_top"]:
            return ""
        linhas = [f"<tr><td class='mono'>{E(x['path'])}</td><td class='num'>{x['tabelas']}</td>"
                  f"<td class='num'>{x['vinculos']}</td></tr>" for x in d["dirs_top"]]
        return ("<h3>O pedido — pastas a liberar em lote</h3>"
                + tabela(["Diretório físico", "Tabelas", "Vínculos"], linhas)
                + "<p class='sub pad'>“Vínculos” = quantas vezes a pasta aparece como pendência de um EGP da carteira; "
                  "“tabelas” = itens distintos a ingerir.</p>")

    def decisoes(d, n=6):
        if not d["resta"]:
            return ""
        linhas = []
        for x in d["resta"][:n]:
            marca = ("<span class='chip c-gra'>despriorizar por padrão</span>"
                     if x["n"] > REGRA_PEND and int(x["mes"] or 0) >= REGRA_MES else "")
            pastas = ", ".join(p.split("/")[-1] for p in x["dirs"][:3]) or "—"
            linhas.append(f"<tr><td class='egp'>{E(x['egp'])} {marca}</td><td class='num'>{chips_mes(x['mes'])}</td>"
                          f"<td class='num'>{x['n']}</td><td class='num'>{x['arq']}</td>"
                          f"<td class='mono'>{E(pastas)}</td></tr>")
        extra = ""
        if len(d["resta"]) > n:
            resto = sum(x["n"] for x in d["resta"][n:])
            extra = (f"<p class='sub pad'>Mais {len(d['resta']) - n} EGPs somando {resto} pendências — "
                     f"a lista completa está no CSV.</p>")
        return ("<h3>As decisões — EGPs que seguem travados</h3>"
                + tabela(["EGP", "Mês", "Pend.", "Arq.", "Pastas"], linhas) + extra)

    def arquivos(d):
        if not d["arq"]:
            return ""
        ex = ", ".join(f"<span class='mono'>{E(a)}</span>" for a in d["arq_ex"])
        return (f"<h3>Arquivos sem caminho físico — {d['arq']} itens</h3>"
                f"<p class='sub pad'>Não há pasta para liberar: chegam por planilha ou CSV de mão. Exemplos: {ex}.</p>")

    for i, (nome, ordem, pauta, dur, tese, fechar) in enumerate(roteiro):
        d = porresp[nome]
        ped = pedido(d) if pauta != "pauta de escopo" else ""
        itens = "".join(f"<li>{t}</li>" for t in fechar)
        secoes.append(f"""
<section class="pessoa" id="p{i}">
  <div class="cabp"><p class="eyebrow">{E(ordem)} · {E(pauta)} · {E(dur)}</p><h2>{E(nome)}</h2></div>
  <p class="tese">{tese}</p>
  {placar(d)}
  {nota_fora(nome)}
  {resolvidos(d)}
  {ped}
  {decisoes(d, 5 if len(d['resta']) > 6 else 6)}
  {arquivos(d)}
  <div class="fechar"><h3>Fechar a reunião com</h3><ol>{itens}</ol></div>
</section>""")

    for nome in faltantes:
        d = porresp[nome]
        maior = d["resta"][0] if d["resta"] else None
        det = ""
        if maior:
            pastas = ", ".join(p.split("/")[-1] for p in maior["dirs"]) or "arquivos sem caminho"
            det = (f" O maior item é <span class='mono'>{E(maior['egp'])}</span>, mês {E(maior['mes'])}, com "
                   f"{maior['n']} pendências em <span class='mono'>{E(pastas)}</span>.")
        secoes.append(f"""
<section class="pessoa" id="x{E(nome).replace(' ', '-')}">
  <div class="cabp"><p class="eyebrow">Sem reunião · resolver por mensagem</p><h2>{E(nome)}</h2></div>
  <p class="tese">Carteira de {d['alvo']} EGP(s), {d['pend_resta']} pendências.{det} Pela regra dos
  {REGRA_PEND} pendências e mês ≥ {REGRA_MES}, o padrão é despriorizar: não vale uma reunião, vale uma pergunta.</p>
  {placar(d)}
  {nota_fora(nome)}
  {decisoes(d, 4)}
</section>""")

    nav = "".join(f"<a href='#p{i}'>{E(n.split()[0])}</a>" for i, (n, *_) in enumerate(roteiro))
    nav += "".join(f"<a href='#x{E(n).replace(' ', '-')}'>{E(n.split()[0])}</a>" for n in faltantes)
    total_alvo = sum(d["alvo"] for d in porresp.values())
    return f"""<div class="wrap">
<header class="capa">
  <p class="eyebrow">Migração SAS · Cobrança · dados do app em {E(data_br)}</p>
  <h1>Reuniões de desbloqueio</h1>
  <p class="lede">Recorte: <strong>escopo Indicium + dependências</strong> ({len(c["plano"])} EGPs no plano), menos
  {len(c["migrados"])} migrados e {len(c["desprior"])} despriorizados — as carteiras abaixo somam os
  {sum(d["alvo"] for d in porresp.values())} EGPs em que há o que fazer. Despriorizado não entra em nenhuma conta
  desta página: está fora do backlog e não requer atuação.</p>
  <p class="lede">Uma página por responsável BV, na ordem sugerida para as conversas. O que sustenta o formato 1-a-1:
  <strong>99% a 100% dos inputs pendentes de cada carteira são exclusivos dela</strong> — nenhuma decisão de um
  responsável trava a de outro, e cada reunião pode fechar sozinha.</p>
  <p class="lede">Duas pautas, de naturezas opostas: <strong>acesso</strong> (liberar uma pasta, decisão de minutos) e
  <strong>escopo</strong> (este EGP vale a migração?). Misturar as duas é o que faz esse tipo de conversa render pouco.</p>
  <nav class="indice">{nav}</nav>
</header>
{''.join(secoes)}
<footer>
  <p>Universo: {total_alvo} EGPs em que atuar, do plano <span class="mono">indi_deps</span> (escopo Indicium ∪
  dependências transitivas ∪ ex-dependências contabilizadas), lido do próprio backend do app. Fora: migrados e
  despriorizados. Pendência usa a régua do app (<span class="mono">_aingerir</span>): Sanitizado e vínculo
  quebrado contam como resolvidos.</p>
  <p>“Fecham nas ondas 1-3” = EGPs que ficam sem pendência ao concluir os inputs já em voo, as três pastas da onda 2
  (<code>jcarneiro</code>, <code>erocha/cartao/cl/mis</code>, <code>erocha/cartao/movto</code>) e os inputs avulsos da onda 3.</p>
  <p>Fonte: <code>{CATALOG}.{SCHEMA}</code> — <code>sas_escopo</code>, <code>sas_egp_pipeline</code>,
  <code>sas_egp_inputs</code>, <code>sas_inputs_monitor</code>. Consultado em {E(data_br)}.</p>
</footer>
</div>"""


# --------------------------------------------------------------------------- CSV
def escreve_csv(c: dict, caminho: str) -> int:
    """Escreve TODO o plano indi_deps. Despriorizado e migrado entram marcados na coluna
    `universo` (nunca somem sem rastro); só o universo 'atuacao' recebe onda."""
    egps, pend, onda_de = c["egps"], c["pend"], c["onda_de"]
    rotulos = {0: "0 - sem pendencia", 1: "1 - concluir o que ja esta em voo",
               2: "2 - 3 diretorios (jcarneiro, cl/mis, cartao/movto)",
               3: "3 - ate 2 inputs avulsos", 4: "4 - cauda longa"}
    linhas = []
    for p, e in egps.items():
        if p in c["desprior"]:
            universo, onda = "despriorizado (fora do backlog - nao atuar)", ""
        elif p in c["migrados"]:
            universo, onda = "migrado (concluido)", ""
        else:
            universo, onda = "atuacao", rotulos[onda_de(pend.get(p, []))]
        ps = pend.get(p, []) if universo == "atuacao" else []
        linhas.append(dict(
            universo=universo, onda=onda, projeto=p,
            origem=("escopo indicium" if e["dep_nivel"] == 0 else f"dependencia nivel {e['dep_nivel']}"),
            etapa_migracao=e["etapa"], status_migracao=e["status"], mes_plano=int(e["mes"] or 0),
            responsavel_bv=e["resp_bv"], inputs_total=int(e["inputs_total"] or 0),
            pendencias=len(ps),
            segura_egps_vivos=" | ".join(sorted(c["bloqueia_vivos"].get(p, ()))),
            pend_em_voo=sum(1 for r in ps if em_voo(r)),
            pend_tabela=sum(1 for r in ps if r["categoria"] == "tabela"),
            pend_arquivo=sum(1 for r in ps if r["categoria"] != "tabela"),
            pend_sem_path=sum(1 for r in ps if eh_arquivo(r)),
            libs=" | ".join(sorted({libname(r) for r in ps if libname(r)})),
            pastas=" | ".join(sorted({r["path"] for r in ps if r["path"]})),
            inputs_pendentes=" | ".join(sorted(f"{r['artifact']} [{r['etapa']}]" for r in ps))))
    linhas.sort(key=lambda r: (r["universo"] != "atuacao", r["onda"], -r["pendencias"], r["projeto"]))
    for i, r in enumerate(linhas, 1):
        r["rank"] = i
    cols = ["rank", "universo", "onda", "projeto", "origem", "responsavel_bv", "etapa_migracao",
            "status_migracao", "mes_plano", "inputs_total", "pendencias", "segura_egps_vivos",
            "pend_em_voo", "pend_tabela", "pend_arquivo", "pend_sem_path", "libs", "pastas",
            "inputs_pendentes"]
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        for r in linhas:
            w.writerow({k: r[k] for k in cols})
    return len(linhas)


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="bv", help="profile do Databricks CLI (default: bv)")
    ap.add_argument("--data", default=datetime.date.today().isoformat(), help="data do snapshot, formato AAAA-MM-DD")
    ap.add_argument("--sem-pdf", action="store_true", help="não tentar gerar PDF")
    a = ap.parse_args()
    data_br = "/".join(reversed(a.data.split("-")))

    print(f"consultando {CATALOG}.{SCHEMA} via backend do app (profile {a.profile})…")
    dados = carrega(a.profile)
    c = calcula(dados)
    # a matriz etapa×status vai impressa em toda rodada: é o que impede ler 'Migrado' (etapa)
    # como concluído — a maioria dos 'Migrado' é despriorizado.
    print("  etapa × status no plano:")
    for (et, st), n in sorted(dados["matriz"].items(), key=lambda kv: -kv[1])[:8]:
        print(f"     {n:>4}  {et} / {st}")
    print(f"  plano indi_deps: {len(c['plano'])} EGPs | migrados: {len(c['migrados'])} | "
          f"despriorizados: {len(c['desprior'])} | universo de atuação: {len(c['alvo'])}")

    saidas = []
    corpo, resumo = pagina_ondas(c, data_br)
    corpo_dir = os.environ.get("CORPO_ARTIFACT_DIR")
    for nome, titulo, html_corpo in (
        (f"BV_Migracao_SAS_Ondas_Destravamento_{a.data}.html", "Ondas de Destravamento SAS", corpo),
        (f"BV_Migracao_SAS_Pacote_Reunioes_{a.data}.html", "Reuniões de Desbloqueio SAS", pagina_reunioes(c, data_br)),
    ):
        caminho = os.path.join(OUT_DIR, nome)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(pagina(titulo, html_corpo, data_br))
        saidas.append(caminho)
        print(f"  html: {nome}")
        if corpo_dir:
            alvo_corpo = os.path.join(corpo_dir, "ondas.html" if "Ondas" in nome else "reunioes.html")
            with open(alvo_corpo, "w", encoding="utf-8") as f:
                f.write(f"<title>{titulo}</title>\n"
                        f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                        f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family='
                        f'Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=IBM+Plex+Mono:wght@400;500'
                        f'&family=IBM+Plex+Sans:wght@400;500;600&display=swap">\n'
                        f"<style>{css(data_br)}</style>\n{html_corpo}\n")

    csv_path = os.path.join(OUT_DIR, f"BV_Migracao_SAS_QuickWins_Ingestao_{a.data}.csv")
    print(f"  csv:  {os.path.basename(csv_path)} ({escreve_csv(c, csv_path)} EGPs)")

    print("resumo:", ", ".join(f"{k}={v}" for k, v in resumo.items()))

    if not a.sem_pdf:
        try:
            from weasyprint import HTML  # noqa: PLC0415
        except ImportError:
            print("  (weasyprint ausente — abra o HTML e use Ctrl+P → Salvar como PDF)")
            return 0
        for src in saidas:
            pdf = src[:-5] + ".pdf"
            HTML(filename=src).write_pdf(pdf, presentational_hints=True)
            print(f"  pdf:  {os.path.basename(pdf)} ({os.path.getsize(pdf) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

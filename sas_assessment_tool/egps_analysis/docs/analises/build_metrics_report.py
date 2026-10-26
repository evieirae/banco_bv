#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Relatório de métricas da migração SAS → stack moderna.

Fontes:
  - egps_analysis/06_prontidao_tabela.csv  (extração do pipeline: inputs E outputs)
  - egps_analysis/docs/analises/indi_231_vs_extracao_06.csv (mapa Indicium -> project do 06)

Duas visões:
  A) BASE COMPLETA  — todos os projetos extraídos (received_egps: .egp + .sas)
  B) ESCOPO INDICIUM    — os 231 priorizados p/ consultoria (225 casados com o 06)

Métricas: EGPs únicos, inputs únicos, outputs únicos, tabelas intermediárias
(input de um projeto e output de outro), modernização (status_validacao),
inputs compartilhados, top fan-out, quebra por área.

Ruído excluído das contagens de tabelas: WORK./DICTIONARY./SASHELP./SASUSER.,
placeholders de macro ({...}, &var) e *.sas7(bdat) sem libname resolvido.

Uso (do root do projeto):
  python egps_analysis/docs/analises/build_metrics_report.py
Saída:
  egps_analysis/docs/analises/RELATORIO_METRICAS_MIGRACAO.md (e resumo no stdout)
"""
import csv
import collections
import os
import datetime

R06 = "egps_analysis/06_prontidao_tabela.csv"
INDI = "egps_analysis/docs/analises/indi_231_vs_extracao_06.csv"
OUT = "egps_analysis/docs/analises/RELATORIO_METRICAS_MIGRACAO.md"

# Override de área: projeto cuja área no extrator diverge da área "dona" na lista Indicium.
AREA_OVERRIDE = {"Banco Relacional__Processo de bonificação - taxas_v35 (2)": "Cartões"}
IN_CATS = {"table_in", "file_in", "script_in"}
# libname_in NAO conta como input (decisao 2026-06-12): o libref sozinho nao e dado concreto —
# as tabelas importadas da libname ja entram individualmente como table_in.
CTX_CATS = {"libname_in"}
OUT_CATS = {"table_out", "file_out", "libname_out"}
MODERN_STATUSES = {
    "Nativa BigQuery (Identificada no EGP)",
    "[Modernizada] Tabela utilizada presente no BigQuery",
    "[Identificado ajuste] Existe uma modernizada no BigQuery correspondente a esta tabela",
}


def is_noise_table(art):
    a = art.upper()
    if a.startswith(("WORK.", "DICTIONARY.", "SASHELP.", "SASUSER.")):
        return True
    if "{" in a or "}" in a or "&" in a:
        return True
    if a.endswith((".SAS7", ".SAS7BDAT")):
        return True
    return False


def load_rows():
    with open(R06, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cat = (r.get("category") or "").strip()
            if cat not in IN_CATS | CTX_CATS | OUT_CATS:
                continue
            art = (r.get("artifact") or "").strip()
            if not art:
                continue
            proj = (r.get("project") or "").strip()
            yield {
                "project": proj,
                "area": AREA_OVERRIDE.get(proj, (r.get("area") or "").strip() or "(sem área)"),
                "art": art,
                "artU": art.upper(),
                "cat": cat,
                "src": (r.get("source_type") or "").strip(),
                "status": (r.get("status_validacao") or "").strip(),
                "ext": (r.get("project_extension") or "").strip(),
            }


def load_indi_projects():
    """projects (nomes do 06) dos EGPs Indicium casados (exato/variante/provável)."""
    projs = set()
    if not os.path.exists(INDI):
        return projs
    with open(INDI, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            st = r["status_extracao"]
            val = r["project_no_06 / observacao"]
            if st in ("exato", "variante"):
                projs.add(val.strip())
            elif st in ("provavel", "confirmado_area", "ingerido_extraido"):
                # formatos: "<project> — OBS" · "<project> (obs)" · "...: <project>"
                cand = val.split(" — ")[0].split(" (")[0].strip()
                if ":" in cand:
                    cand = cand.split(":")[-1].strip()
                projs.add(cand)
    return projs


def compute(rows):
    m = {}
    projects = {}                       # project -> (area, ext)
    tin, tout = set(), set()            # tabelas únicas (sem ruído)
    fin, fout = set(), set()
    libin, libout, scrin = set(), set(), set()
    noise_in, noise_out = set(), set()
    tin_modern = set()
    fin_modern, scrin_modern = set(), set()
    tin_to_projs = collections.defaultdict(set)
    tout_to_projs = collections.defaultdict(set)
    area_proj = collections.Counter()
    area_tin = collections.defaultdict(set)

    for r in rows:
        projects.setdefault(r["project"], (r["area"], r["ext"]))
        cat, aU = r["cat"], r["artU"]
        if cat == "table_in":
            if is_noise_table(r["art"]):
                noise_in.add(aU)
                continue
            tin.add(aU)
            tin_to_projs[aU].add(r["project"])
            area_tin[r["area"]].add(aU)
            if r["status"] in MODERN_STATUSES:
                tin_modern.add(aU)
        elif cat == "table_out":
            if is_noise_table(r["art"]):
                noise_out.add(aU)
                continue
            tout.add(aU)
            tout_to_projs[aU].add(r["project"])
        elif cat == "file_in":
            fin.add(aU)
            if r["status"] in MODERN_STATUSES:
                fin_modern.add(aU)
        elif cat == "file_out":
            fout.add(aU)
        elif cat == "libname_in":
            libin.add(aU)
        elif cat == "libname_out":
            libout.add(aU)
        elif cat == "script_in":
            scrin.add(aU)
            if r["status"] in MODERN_STATUSES:
                scrin_modern.add(aU)

    for pj, (area, _e) in projects.items():
        area_proj[area] += 1

    inter = tin & tout                  # intermediárias (encadeiam projetos)
    shared = {a for a, ps in tin_to_projs.items() if len(ps) >= 2}
    ext = collections.Counter(e for _a, e in projects.values())

    m["projects"] = projects
    m["n_proj"] = len(projects)
    m["ext"] = dict(ext)
    m["area_proj"] = area_proj
    m["tin"], m["tout"] = tin, tout
    m["fin"], m["fout"] = fin, fout
    m["libin"], m["libout"], m["scrin"] = libin, libout, scrin
    m["noise"] = len(noise_in | noise_out)
    m["inter"] = inter
    m["shared"] = shared
    m["tin_modern"] = tin_modern
    m["fin_modern"], m["scrin_modern"] = fin_modern, scrin_modern
    m["tin_to_projs"] = tin_to_projs
    m["tout_to_projs"] = tout_to_projs
    m["area_tin"] = area_tin
    return m


def fmt(n):
    return f"{n:,}".replace(",", ".")


def section(m, title, note=""):
    tin, tout = m["tin"], m["tout"]
    modern = m["tin_modern"]
    nao_mod = tin - modern
    L = []
    L.append(f"## {title}\n")
    if note:
        L.append(note + "\n")
    L.append("| Métrica | Valor |")
    L.append("|---|---:|")
    L.append(f"| **Projetos únicos (EGP/SAS)** | **{fmt(m['n_proj'])}** |")
    for e, c in sorted(m["ext"].items(), key=lambda x: -x[1]):
        L.append(f"| &nbsp;&nbsp;— extensão `{e or '?'}` | {fmt(c)} |")
    # INPUT = table_in + file_in + script_in. "tabela" (table_in) é só um subconjunto —
    # não confundir "ingestão de inputs" (as 3 categorias) com "ingestão de tabelas".
    fin, scrin = m["fin"], m["scrin"]
    fin_mod, scrin_mod = m["fin_modern"], m["scrin_modern"]
    in_total = len(tin) + len(fin) + len(scrin)
    in_modern = len(modern) + len(fin_mod) + len(scrin_mod)
    in_ingerir = in_total - in_modern
    L.append(f"| **Inputs de entrada distintos** (`table_in`+`file_in`+`script_in`) | **{fmt(in_total)}** |")
    L.append(f"| &nbsp;&nbsp;— **a ingerir / modernizar (total de inputs)** | **{fmt(in_ingerir)}** |")
    L.append(f"| &nbsp;&nbsp;— já disponíveis (BigQuery) | {fmt(in_modern)} |")
    L.append("| &nbsp;&nbsp;*detalhe por categoria (distintos → a ingerir):* | |")
    L.append(f"| &nbsp;&nbsp;&nbsp;&nbsp;tabelas (`table_in`) | {fmt(len(tin))} → **{fmt(len(nao_mod))}** |")
    L.append(f"| &nbsp;&nbsp;&nbsp;&nbsp;arquivos (`file_in`) | {fmt(len(fin))} → {fmt(len(fin) - len(fin_mod))} |")
    L.append(f"| &nbsp;&nbsp;&nbsp;&nbsp;scripts (`script_in`) | {fmt(len(scrin))} → {fmt(len(scrin) - len(scrin_mod))} |")
    L.append(f"| &nbsp;&nbsp;tabelas compartilhadas (≥2 projetos) | {fmt(len(m['shared']))} |")
    L.append(f"| **Tabelas de SAÍDA únicas** (outputs) | **{fmt(len(tout))}** |")
    L.append(f"| Tabelas intermediárias (saída de um, entrada de outro) | {fmt(len(m['inter']))} |")
    L.append(f"| Arquivos de saída únicos (file_out) | {fmt(len(m['fout']))} |")
    L.append(f"| Libnames detectados (in / out) — *contexto, não contam como input* | {fmt(len(m['libin']))} / {fmt(len(m['libout']))} |")
    L.append(f"| Ruído excluído (WORK/macro/metadado) | {fmt(m['noise'])} |")
    pct = (in_modern / in_total * 100) if in_total else 0
    L.append(f"| % de inputs já modernizados | {pct:.1f}% |")
    L.append("")
    # áreas
    L.append("**Projetos e inputs únicos por área:**\n")
    L.append("| Área | Projetos | Inputs únicos (tabelas) |")
    L.append("|---|---:|---:|")
    for a, c in m["area_proj"].most_common():
        L.append(f"| {a} | {fmt(c)} | {fmt(len(m['area_tin'].get(a, set())))} |")
    L.append("")
    # top fan-out
    L.append("**Top 10 inputs por nº de projetos consumidores:**\n")
    L.append("| Tabela | Projetos | Modernizada? |")
    L.append("|---|---:|---|")
    top = sorted(m["tin_to_projs"].items(), key=lambda x: -len(x[1]))[:10]
    for a, ps in top:
        mod = "Sim" if a in m["tin_modern"] else "Não"
        L.append(f"| `{a}` | {fmt(len(ps))} | {mod} |")
    L.append("")
    return "\n".join(L)


def count_all_projects():
    s = set()
    with open(R06, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s.add((r.get("project") or "").strip())
    s.discard("")
    return len(s)


def main():
    all_rows = list(load_rows())
    indi = load_indi_projects()
    m_all = compute(all_rows)
    n_total = count_all_projects()
    n_sem_io = n_total - m_all["n_proj"]
    valid_indi = indi & set(m_all["projects"])
    m_indi = compute([r for r in all_rows if r["project"] in valid_indi])

    today = datetime.date.today().isoformat()
    doc = [
        "# Relatório de Métricas — Migração SAS",
        "",
        f"> Gerado em **{today}** por `build_metrics_report.py` a partir de "
        f"`06_prontidao_tabela.csv` (pipeline) + `indi_231_vs_extracao_06.csv` (escopo Indicium).",
        "",
        "Tabelas únicas = nome normalizado (maiúsculas), excluindo ruído "
        "(`WORK.*`, `DICTIONARY.*`, placeholders de macro). "
        "“Modernizada” = `status_validacao` indica presença no BigQuery.",
        "",
        section(m_all, "A) Base completa (todos os projetos extraídos)",
                f"Tudo que está em `received_egps/` — EGPs de todas as áreas + jobs SAS de produção (UC4). "
                f"A extração cobre **{fmt(n_total)}** projetos; **{fmt(n_sem_io)}** não têm nenhum I/O "
                f"detectado (projetos vazios/só visualização — candidatos a auditoria) e ficam fora das métricas."),
        section(m_indi, "B) Escopo Indicium — 231 priorizados para a consultoria",
                f"Subconjunto casado com a extração: **{fmt(len(valid_indi))}** projetos "
                f"(2 EGPs ainda não recebidos; demais divergências de nome documentadas em "
                f"`indi_231_vs_extracao_06.csv`)."),
    ]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(doc))
    print("escrito:", OUT)
    # resumo no stdout
    for nome, m in (("BASE COMPLETA", m_all), ("INDICIUM", m_indi)):
        tin = m["tin"]
        in_total = len(tin) + len(m["fin"]) + len(m["scrin"])
        in_ing = (len(tin) - len(m["tin_modern"])) + (len(m["fin"]) - len(m["fin_modern"])) \
            + (len(m["scrin"]) - len(m["scrin_modern"]))
        print(f"\n[{nome}] projetos={m['n_proj']}  "
              f"INPUTS (tab+arq+script)={in_total} (a ingerir={in_ing})  "
              f"| tabelas={len(tin)} (a ingerir={len(tin - m['tin_modern'])}, mod={len(m['tin_modern'])})  "
              f"outputs={len(m['tout'])}  intermediárias={len(m['inter'])}  compart.={len(m['shared'])}")


if __name__ == "__main__":
    main()

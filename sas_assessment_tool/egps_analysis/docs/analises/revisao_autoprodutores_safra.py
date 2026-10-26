#!/usr/bin/env python3
"""Revisão dos EGPs auto-produtores com lente de SAFRA — o que ingerir vs sanitizar.

Complementa `script_inputs_autogerados.py` (que roda no app/Databricks e só pega
auto-produção de MESMA chave). Aqui a detecção é local (`text_egps/` + 06_prontidao)
e acrescenta o caso que aquela análise não vê:

    o EGP cria PERF_CL.PAGOS_CYBER_202502 e LÊ PERF_CL.PAGOS_CYBER_202602
    -> chaves canônicas distintas, mesma FAMÍLIA; o produtor é o próprio EGP
       numa execução anterior. Não é ingestão recorrente, é backfill único.

Identidade path-aware: a chave é (path físico, membro), nunca o alias do libname
(ver docs/analises/REFAZ_LINHAGEM_PATH.md). O path vem do 06_prontidao_tabela.csv
(coluna `path`, já resolvida pelo orquestrador) com fallback em DETECTED_LIBNAMES.

Saídas (docs/analises/):
  revisao_autoprodutores_pares_<data>.csv   1 linha por (EGP × input)
  revisao_autoprodutores_triagem_<data>.csv 1 linha por input distinto (ação)

Uso: python docs/analises/revisao_autoprodutores_safra.py [AAAA-MM-DD]
Rodar de egps_analysis/.
"""
from __future__ import annotations

import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict

TEXT_DIR = "text_egps"
PRONTIDAO = "06_prontidao_tabela.csv"
OUT_DIR = "docs/analises"

# ---------------------------------------------------------------- parsing

SECTIONS = {
    "EXTERNAL INPUTS (Requires Ingestion):": "ext_in",
    "PERMANENT OUTPUTS (Target Marts):": "cria",
    "APPEND_ONLY_OUTPUTS:": "apensa",
    "NON_CREATOR_OUTPUTS (apensa/atualiza, nunca cria):": "nao_cria",
    "INTERNAL READS (Temp/Local):": "int_read",
    "DETECTED_LIBNAMES:": "libnames",
}
NONE_TOKENS = {"(none)", "(nenhum)", "", "(NONE)"}


def parse_header(path: str) -> dict:
    """Lê só o bloco START_METADATA..END_METADATA e devolve as listas por seção."""
    out = {v: [] for v in SECTIONS.values()}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("END_METADATA"):
                break
            for prefix, key in SECTIONS.items():
                if line.startswith(prefix):
                    body = line[len(prefix):].strip()
                    if body in NONE_TOKENS:
                        break
                    sep = "; " if key == "libnames" else ", "
                    out[key] = [x.strip() for x in body.split(sep) if x.strip()]
                    break
    return out


def strip_tag(item: str) -> tuple[str, str]:
    """'PERF_CL.X [SAS/Local]' -> ('PERF_CL.X', 'SAS/Local')."""
    m = re.match(r"^(.*?)\s*\[([^\]]*)\]\s*$", item)
    return (m.group(1).strip(), m.group(2).strip()) if m else (item.strip(), "")


def is_file_ref(a: str) -> bool:
    return a.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:[\\/]", a)) or "\\" in a


def split_libmember(a: str) -> tuple[str, str] | None:
    m = re.match(r"^([A-Za-z_][\w]{0,31})\.(.+)$", a)
    return (m.group(1).upper(), m.group(2).upper()) if m else None


# ------------------------------------------------------- família / safra

# YYYYMM ou YYYYMMDD com mês válido — evita casar 4041, 1820405 etc.
DATE_TOK = re.compile(r"(?<!\d)(20\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])?)(?!\d)")


def family(member: str) -> tuple[str, tuple[str, ...]]:
    """'PAGOS_CYBER_202502' -> ('PAGOS_CYBER_<D>', ('202502',))."""
    safras = tuple(DATE_TOK.findall(member))
    return (DATE_TOK.sub("<D>", member), safras)


CAL_PAT = re.compile(
    r"^(DIAS_UTEIS|DIAS_UTEIS_\w*|FIM_DE_SEMANA|FERIADOS?|CALENDARIO\w*|"
    r"TB_?CALENDARIO\w*|DATAS_UTEIS|DU_\w*|BASE_DU)$")

MACRO_PAT = re.compile(r"[&{]")


# ---------------------------------------------------------------- carga


def load_paths() -> dict[tuple[str, str], str]:
    """(project, artifact_upper) -> path físico, do 06_prontidao_tabela.csv."""
    out: dict[tuple[str, str], str] = {}
    if not os.path.exists(PRONTIDAO):
        return out
    with open(PRONTIDAO, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["category"] not in ("table_in", "table_out"):
                continue
            p = (r["path"] or "").strip()
            if not p or MACRO_PAT.search(p):
                continue
            out.setdefault((r["project"], (r["artifact"] or "").upper()), p.rstrip("/").upper())
    return out


def load_escopo_indi() -> set[str]:
    """Nomes curtos dos EGPs do recorte Indicium (para separar o que está no plano)."""
    f = os.path.join(OUT_DIR, "indicium_scope_222_projetos.csv")
    if not os.path.exists(f):
        return set()
    with open(f, encoding="utf-8-sig") as fh:
        return {(r["project"] or "").strip().upper() for r in csv.DictReader(fh) if r.get("project")}


def main() -> None:
    data = sys.argv[1] if len(sys.argv) > 1 else "hoje"
    paths06 = load_paths()
    escopo = load_escopo_indi()

    def in_escopo(proj: str) -> bool:
        short = proj.split("__", 1)[1] if "__" in proj else proj
        return short.strip().upper() in escopo

    projects: dict[str, dict] = {}
    for f in sorted(glob.glob(os.path.join(TEXT_DIR, "*.txt"))):
        proj = os.path.basename(f)[:-4]
        h = parse_header(f)
        libmap = {}
        for entry in h["libnames"]:
            if "=" in entry:
                alias, p = entry.split("=", 1)
                p = p.strip().rstrip("/").upper()
                if p and not MACRO_PAT.search(p):
                    libmap[alias.strip().upper()] = p
        projects[proj] = {"h": h, "libmap": libmap}

    def canon(proj: str, artifact: str) -> tuple[str, str, str] | None:
        """-> (path_ou_alias, membro, 'path'|'alias'). None se não é lib.membro."""
        lm = split_libmember(artifact)
        if not lm:
            return None
        alias, member = lm
        p = paths06.get((proj, artifact.upper())) or projects[proj]["libmap"].get(alias)
        return (p, member, "path") if p else (alias, member, "alias")

    # --- índice global de escritas (por chave e por família) -------------
    # REGRA DO CRIADOR: PERMANENT OUTPUTS é o conjunto de TODAS as escritas
    # permanentes; NON_CREATOR_OUTPUTS é o subconjunto que só apensa/atualiza
    # (INSERT INTO / PROC APPEND / UPDATE / MODIFY / DELETE, sem nenhum sinal de
    # criação). Criador real = cria − nao_cria. Ver egps_extractor.py
    # detect_non_creator_outputs() e docs/analises regra do criador (2026-08-12).
    def write_sets(proj: str) -> tuple[set, set]:
        d = projects[proj]
        perm, noncre = set(), set()
        for kind, bucket in (("cria", perm), ("nao_cria", noncre)):
            for item in d["h"][kind]:
                a, _ = strip_tag(item)
                c = canon(proj, a)
                if c:
                    bucket.add((c[0], c[1]))
        return perm - noncre, noncre

    creators: dict[tuple[str, str], set[str]] = defaultdict(set)
    appenders: dict[tuple[str, str], set[str]] = defaultdict(set)
    creators_fam: dict[tuple[str, str], set[str]] = defaultdict(set)
    writes: dict[str, tuple[set, set]] = {}
    for proj in projects:
        cria_real, noncre = write_sets(proj)
        writes[proj] = (cria_real, noncre)
        for key in cria_real:
            creators[key].add(proj)
            creators_fam[(key[0], family(key[1])[0])].add(proj)
        for key in noncre:
            appenders[key].add(proj)

    # --- classificação dos inputs --------------------------------------
    pares = []
    for proj, d in projects.items():
        own_keys, own_noncre = writes[proj]
        own_fams = {(k[0], family(k[1])[0]) for k in own_keys}

        # ext_in  = fila de ingestão do inventário (já sem os same-script re-reads)
        # int_read = tabelas permanentes que o EGP lê E escreve; o extractor as
        #            exclui de ext_in, mas o inventário de inputs do app as mantém
        #            (é a população dos 243 de script_inputs_autogerados.py).
        for origem_hdr, item in ([("ext_in", i) for i in d["h"]["ext_in"]]
                                 + [("int_read", i) for i in d["h"]["int_read"]]):
            a, tag = strip_tag(item)
            if is_file_ref(a):
                continue                       # arquivos: bucket separado, ver relatório
            if tag.upper() not in ("SAS/LOCAL", ""):
                continue                       # BIGQUERY/etc já disponível
            if a.upper().startswith("WORK."):
                continue
            c = canon(proj, a)
            if not c:
                continue
            pkey, member, keytype = c
            key = (pkey, member)
            fam_stem, safras = family(member)
            famkey = (pkey, fam_stem)
            others_key = creators[key] - {proj}
            others_fam = creators_fam.get(famkey, set()) - {proj}

            if key in own_keys:
                cls, acao = "auto_mesmo_run", "Sanitizar"
            elif key in own_noncre and not others_key:
                cls, acao = ("acumulador_compartilhado",
                             "Carga inicial (NÃO sanitizar) — o próprio EGP só apensa")
            elif famkey in own_fams:
                cls, acao = "auto_safra_irma", "Backfill único (não ingestão recorrente)"
            elif others_key:
                cls, acao = "outro_egp_cria", "ref() — migrar o produtor"
            elif others_fam:
                cls, acao = "outro_egp_cria_safra_irma", "Backfill único + ref() do produtor"
            elif CAL_PAT.match(member):
                cls, acao = "calendario", "Sanitizar (recriar como date spine no dbt)"
            elif MACRO_PAT.search(member):
                cls, acao = "membro_dinamico", "Resolver macro antes de decidir"
            elif key in appenders:
                cls, acao = "acumulador_compartilhado", "Carga inicial (NÃO sanitizar)"
            elif safras:
                cls, acao = "ingestao_snapshot_datado", "Ingerir 1x (candidato a seed)"
            else:
                cls, acao = "ingestao_recorrente", "Ingerir (fonte real)"

            pares.append({
                "EGP": proj,
                "Escopo Indicium": "sim" if in_escopo(proj) else "não",
                "Seção do header": origem_hdr,
                "Input": a,
                "Membro": member,
                "Familia": fam_stem,
                "Safras no nome": " | ".join(safras),
                "Chave (path|alias)": f"{pkey}::{member}",
                "Tipo de chave": keytype,
                "Classificação": cls,
                "Ação": acao,
                "Outros criadores (chave exata)": " | ".join(sorted(others_key)),
                "Outros criadores (mesma família)": " | ".join(sorted(others_fam)),
            })

    # --- CSVs -----------------------------------------------------------
    # Sem pares não há o que escrever — e `list(pares[0].keys())` abaixo estouraria
    # IndexError, que num relatório de leitura parece defeito do script e não
    # "a cascata de filtros não deixou nada" (text_egps/ vazio, por exemplo).
    if not pares:
        print("nenhum par autoprodutor encontrado — nada a escrever "
              "(confira se text_egps/ está populado e os filtros de escopo).")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    f_pares = os.path.join(OUT_DIR, f"revisao_autoprodutores_pares_{data}.csv")
    with open(f_pares, "w", encoding="utf-8", newline="") as fh:
        fh.write("﻿")
        w = csv.DictWriter(fh, fieldnames=list(pares[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(sorted(pares, key=lambda r: (r["Classificação"], r["Input"], r["EGP"])))

    # triagem por input distinto (a ação mais "forte" ganha)
    RANK = ["ingestao_recorrente", "acumulador_compartilhado", "ingestao_snapshot_datado",
            "membro_dinamico", "outro_egp_cria_safra_irma", "outro_egp_cria",
            "auto_safra_irma", "calendario", "auto_mesmo_run"]
    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pares:
        by_key[p["Chave (path|alias)"]].append(p)
    triagem = []
    for k, rows in by_key.items():
        best = min(rows, key=lambda r: RANK.index(r["Classificação"]))
        triagem.append({
            "Chave (path|alias)": k,
            "Input (exemplo)": best["Input"],
            "Familia": best["Familia"],
            "Classificação": best["Classificação"],
            "Ação": best["Ação"],
            "Lido por EGP do escopo Indicium": (
                "sim" if any(r["Escopo Indicium"] == "sim" for r in rows) else "não"),
            "Qtd EGPs que leem": len({r["EGP"] for r in rows}),
            "EGPs que leem": " | ".join(sorted({r["EGP"] for r in rows})),
            "Outros criadores (chave exata)": best["Outros criadores (chave exata)"],
            "Outros criadores (mesma família)": best["Outros criadores (mesma família)"],
        })
    f_tri = os.path.join(OUT_DIR, f"revisao_autoprodutores_triagem_{data}.csv")
    with open(f_tri, "w", encoding="utf-8", newline="") as fh:
        fh.write("﻿")
        w = csv.DictWriter(fh, fieldnames=list(triagem[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(sorted(triagem, key=lambda r: (RANK.index(r["Classificação"]),
                                                   -r["Qtd EGPs que leem"], r["Input (exemplo)"])))

    # --- resumo ---------------------------------------------------------
    print(f"EGPs no corpus: {len(projects)}")
    print(f"pares (EGP × input tabela SAS/Local externo): {len(pares)}")
    print(f"inputs distintos: {len(by_key)}\n")
    auto = {p["EGP"] for p in pares
            if p["Classificação"] in ("auto_mesmo_run", "auto_safra_irma")}
    print(f"EGPs auto-produtores (mesma chave ou safra irmã): {len(auto)}\n")
    cp = Counter(p["Classificação"] for p in pares)
    ct = Counter(t["Classificação"] for t in triagem)
    ce = Counter(t["Classificação"] for t in triagem
                 if t["Lido por EGP do escopo Indicium"] == "sim")
    print(f"{'classificação':32s} {'pares':>7s} {'inputs':>7s} {'indi':>7s}")
    for c in RANK:
        print(f"{c:32s} {cp.get(c, 0):7d} {ct.get(c, 0):7d} {ce.get(c, 0):7d}")
    print(f"\nchaves por path: {Counter(p['Tipo de chave'] for p in pares)}")
    print(f"por seção do header: {Counter(p['Seção do header'] for p in pares)}")
    print("\npares por seção × classificação:")
    for c in RANK:
        e = sum(1 for p in pares if p["Classificação"] == c and p["Seção do header"] == "ext_in")
        i = sum(1 for p in pares if p["Classificação"] == c and p["Seção do header"] == "int_read")
        if e or i:
            print(f"  {c:34s} ext_in={e:5d}  int_read={i:5d}")
    print(f"\n{f_pares}\n{f_tri}")


if __name__ == "__main__":
    main()

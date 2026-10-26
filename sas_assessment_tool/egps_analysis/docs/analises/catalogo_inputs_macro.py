#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catálogo dos inputs de ARQUIVO que dependem de macro — os que o app não vê.

Por que existe: o publish DESCARTA `file_in` cujo artefato é padrão de macro
(`&DT_ARQ._BASE.csv`) — 161 artefatos em 17/09/2026 — porque um nome com macro não
identifica arquivo nenhum. O descarte é correto, mas apaga informação de ingestão: o padrão
diz QUE pasta, QUE esqueleto de nome e QUAL variável varia. Quando a variável é de data, o
arquivo é **safra por construção** (um arquivo por execução/mês na mesma pasta) e o app
nunca soube que existia.

De onde vem o dado (nada é inferido daqui): o extrator já escreve, por EGP, a seção
`[[ FILE_REFS_MACRO ]]` com `direção|path bruto|dir resolvido|esqueleto (# = macro)|vars|status`
e a seção `[[ PROJECT LETS (Global Parameters) ]]` com os `%LET` do projeto. Este script só
agrega as duas e classifica a variável (data / caminho / outra).

Saída: `BV_Migracao_SAS_Catalogo_Inputs_Macro_<data>.csv` nesta pasta, uma linha por
referência, ordenada por (tipo, pasta, esqueleto) — membros da mesma safra ficam juntos.

Uso:
    cd egps_analysis && venv/bin/python docs/analises/catalogo_inputs_macro.py
    venv/bin/python docs/analises/catalogo_inputs_macro.py --só-data   # filtra safra
"""
import argparse
import collections
import csv
import datetime
import glob
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "..", "..")
TXT = os.path.join(BASE, "text_egps")
INDI = os.path.join(AQUI, "indi_231_vs_extracao_06.csv")

# Variável cujo nome indica DATA: o arquivo é safra por construção. Lista pelo nome porque é
# o que existe — o valor do %LET muitas vezes é `TODAY()-10` ou `%scan(&meses,&i)`, que só
# resolve em execução. Casa DT_ARQ, DATA_REF, ANOMES, ANOMESDIA, MES, DIA_EXEC, SAFRA...
VAR_DATA = re.compile(r"(DT|DATA|ANOMES|ANO|MES|DIA|REF|SAFRA|PERIODO|COMPET)", re.I)
# Variável de CAMINHO: falta o diretório, não a safra (&DIR, &C, &CAMINHO, &PATH, &ROOT).
VAR_PATH = re.compile(r"^(DIR|C|CAMINHO|PATH|ROOT|PASTA|LOCAL)[0-9_]*$", re.I)


def classifica(vars_):
    if any(VAR_DATA.search(v) for v in vars_):
        return "data"
    if all(VAR_PATH.match(v) for v in vars_ if v):
        return "caminho"
    return "outra"


def le_egp(path):
    """(lets, refs) de um `text_egps/*.txt`; seção ausente devolve vazio."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    lets = {}
    m = re.search(r"\[\[ PROJECT LETS \(Global Parameters\) \]\]\n(.*?)\n\n", txt, re.S)
    if m:
        for g in re.finditer(r"%LET\s+([A-Z0-9_]+)\s*=\s*([^;]*);", m.group(1), re.I):
            lets[g.group(1).upper()] = g.group(2).strip()
    refs = []
    m = re.search(r"\[\[ FILE_REFS_MACRO \]\]\n(.*?)\n\n", txt, re.S)
    if m:
        for linha in m.group(1).splitlines():
            p = linha.split("|")
            if len(p) >= 6:
                refs.append({"direcao": p[0], "path_bruto": p[1], "dir_resolvido": p[2],
                             "esqueleto": p[3], "vars": [v.strip().upper() for v in p[4].split(",") if v.strip()],
                             "status": p[5]})
    return lets, refs


def resolve_pelo_log(egp, esqueleto, received=None):
    """Nomes REAIS que o log interno do `.egp` mostra para aquele esqueleto.

    O `.egp` é um ZIP e carrega os `*/result.log` da última execução salva: o log imprime
    `Filename=/riscosbv/.../BASE_COLLECTION_GH_20260123.CSV` com a macro JÁ resolvida,
    enquanto o código traz `..._&MES_ref..CSV`. Serve para confirmar pasta e prefixo sem
    precisar de acesso ao `N:` — mas é UMA execução, não o histórico: devolve as safras que
    aquele log viu, não todas as que existem na pasta.
    """
    received = received or os.path.join(BASE, "received_egps")
    area, _, nome = egp.partition("__")
    cam = os.path.join(received, area, nome + ".egp")
    if not os.path.exists(cam):
        return []
    # esqueleto -> regex: `#` (a macro) vira curinga, o resto é literal
    lits = esqueleto.split("#")
    if len(lits) < 2:
        return []
    # Esqueleto que é só extensão (`#.SAS7BDAT`) casa com QUALQUER arquivo daquele tipo:
    # devolveria o log inteiro em vez da safra. Exige literal discriminante (>=6 chars
    # fora do ponto/extensão) — sem isso o nome real não é dedutível, e dizer "não sei" é
    # a resposta correta.
    disc = "".join(lits).rsplit(".", 1)[0]
    if len(re.sub(r"[^A-Z0-9]", "", disc.upper())) < 6:
        return []
    partes = [re.escape(x) for x in lits]
    # Cada `#` é UMA macro-var: o curinga não atravessa `_`, senão `SUSPENSAO_#2.XLSX`
    # casaria `SUSPENSAO_COVID_161020252.XLSX` (irmão, não safra). Padrão `#_#` continua
    # funcionando, porque ali os separadores são literais do esqueleto.
    alvo = re.compile(r"[^\s\"']*" + r"[^\s\"'/\\_]*".join(partes) + r"[^\s\"']*", re.I)
    achados = set()
    try:
        import zipfile
        with zipfile.ZipFile(cam) as z:
            for n in z.namelist():
                if "log" not in n.lower():
                    continue
                try:
                    txt = z.read(n).decode("latin-1", errors="replace")
                except Exception:
                    continue
                for m in alvo.finditer(txt):
                    s = m.group(0).strip().strip(".,;\"'")
                    if "&" in s or "#" in s:      # ainda não resolvido: não é achado
                        continue
                    achados.add(os.path.basename(s.replace("\\", "/")).upper())
                    if len(achados) > 40:      # log de uma execução não tem 40 safras:
                        return sorted(achados)[:40]   # casou largo, corta e não mente
    except Exception:
        return []
    return sorted(achados)


def carrega_indi():
    """EGPs do escopo Indicium — REUSA `load_indi_projects()` do publish.

    A lista (`indi_231_vs_extracao_06.csv`) tem a coluna `egp_dor1` com o nome curto e
    `project_no_06 / observacao` com a chave inteira, às vezes sufixada (" — ", " (") ou
    prefixada por área. Reimplementar essa extração aqui daria duas regras para a mesma
    lista — e a minha primeira tentativa, lendo colunas que não existem, devolveu escopo
    vazio sem erro nenhum.
    """
    import sys
    sys.path.insert(0, os.path.abspath(BASE))
    import publish_to_databricks as pub
    return set(pub.load_indi_projects())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-data", action="store_true", help="só referências com variável de data")
    ap.add_argument("--com-log", action="store_true",
                    help="abre o .egp e resolve o esqueleto pelo log interno (mais lento)")
    ap.add_argument("--received", default=os.path.join(BASE, "received_egps"),
                    help="pasta dos .egp (binários NÃO versionados; num worktree, aponte "
                         "para a árvore principal)")
    args = ap.parse_args()
    indi = carrega_indi()
    linhas = []
    for f in sorted(glob.glob(os.path.join(TXT, "*.txt"))):
        egp = os.path.basename(f)[:-4]
        lets, refs = le_egp(f)
        for r in refs:
            if not r["vars"]:
                continue                      # sem macro: o path já é literal, o app o vê
            tipo = classifica(r["vars"])
            if args.so_data and tipo != "data":
                continue
            linhas.append({
                "egp": egp,
                "no_escopo_indi": egp in indi,
                "direcao": r["direcao"],
                "tipo_macro": tipo,
                "dir_resolvido": r["dir_resolvido"],
                "esqueleto": r["esqueleto"],
                "macro_vars": ",".join(r["vars"]),
                # valor do %LET quando o PRÓPRIO EGP declara; vazio = resolve só em execução
                "let_valores": " | ".join(f"&{v}={lets[v]}" for v in r["vars"] if v in lets),
                "vars_sem_let": ",".join(v for v in r["vars"] if v not in lets),
                "status_extrator": r["status"],
                "path_bruto": r["path_bruto"],
                # nomes reais vistos no log interno do .egp (uma execução, não o histórico)
                "nomes_no_log": " | ".join(resolve_pelo_log(egp, r["esqueleto"], args.received))
                                if args.com_log and tipo == "data" else "",
            })
    linhas.sort(key=lambda r: (r["tipo_macro"], r["dir_resolvido"], r["esqueleto"], r["egp"]))
    hoje = datetime.date.today().isoformat()
    out = os.path.join(AQUI, f"BV_Migracao_SAS_Catalogo_Inputs_Macro_{hoje}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()) if linhas else ["egp"])
        w.writeheader()
        w.writerows(linhas)

    ins = [r for r in linhas if r["direcao"] == "IN"]
    print(f"catálogo: {len(linhas)} referências com macro ({len(ins)} IN, {len(linhas) - len(ins)} OUT)")
    for tipo, n in collections.Counter(r["tipo_macro"] for r in linhas).most_common():
        nin = sum(1 for r in linhas if r["tipo_macro"] == tipo and r["direcao"] == "IN")
        print(f"  {tipo:8s} {n:5d}  (IN {nin})")
    dat = [r for r in ins if r["tipo_macro"] == "data"]
    pares = {(r["dir_resolvido"], r["esqueleto"]) for r in dat}
    print(f"\nSAFRA POR MACRO (input com variável de data): {len(dat)} referências, "
          f"{len(pares)} pares (pasta, padrão), {len({r['egp'] for r in dat})} EGPs")
    print(f"  no escopo Indicium: {sum(1 for r in dat if r['no_escopo_indi'])} referências, "
          f"{len({r['egp'] for r in dat if r['no_escopo_indi']})} EGPs")
    print(f"  com %LET no próprio EGP: {sum(1 for r in dat if r['let_valores'])}")
    print(f"  pasta não resolvida (dir vazio): {sum(1 for r in dat if not r['dir_resolvido'])}")
    if args.com_log:
        tods = [r for r in linhas if r["tipo_macro"] == "data"]
        cin = [r for r in dat if r["nomes_no_log"]]
        cout = [r for r in tods if r["direcao"] == "OUT" and r["nomes_no_log"]]
        print(f"  com nome REAL resolvido no log do .egp: {len(cin)} de {len(dat)} IN"
              f" · {len(cout)} de {sum(1 for r in tods if r['direcao'] == 'OUT')} OUT")
        print(f"  (OUT interessa porque arquivo escrito por um EGP e lido por outro é"
              f" handoff — o log resolve o nome nas duas pontas)")
    print(f"\n-> {out}")


if __name__ == "__main__":
    raise SystemExit(main())

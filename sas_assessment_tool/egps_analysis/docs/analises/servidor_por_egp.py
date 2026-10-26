#!/usr/bin/env python3
"""Em qual servidor SAS cada EGP roda — extraído dos logs de execução dentro do .egp.

O SAS Enterprise Guide grava, junto do resultado de cada tarefa, um `result.log` que
carrega o contexto de execução. Quatro campos interessam:

  • nó de computação  — de `SASWORKLOCATION` (`/saswork/SAS_work<hex>_<NÓ>/...`): é a
    máquina que de fato executou o código (ex.: `srv-sasprd04n1`);
  • host cliente      — `_CLIENTPROJECTPATHHOST`: a estação que abriu o EG (notebook
    `NBK*` = pessoa; `VD-PRDROBO*` = robô/VDI de execução agendada);
  • caminho do .egp   — `_CLIENTPROJECTPATH`: onde o PROJETO mora na rede (`N:\\...` ou
    `\\\\bvnet\\global\\...`). É a origem de rede do .egp, que NÃO está no project.xml;
  • data do log       — cabeçalho "The SAS System  HH:MM Weekday, Month D, YYYY".

Um .egp costuma ter vários logs (um por tarefa, de execuções diferentes), então cada
campo é coletado como CONJUNTO e o valor "predominante" é a moda.

    python docs/analises/servidor_por_egp.py [YYYY-MM-DD]

Com `--plano`, restringe o corpus aos EGPs do recorte vigente (frontier `indi_deps` lido
de prod) — precisa das credenciais do app:

    . app/venv/bin/activate
    PUBLISH_SCHEMA=monitoramento_sas DATABRICKS_CONFIG_PROFILE=bv \
      DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd \
      python docs/analises/servidor_por_egp.py 2026-08-31 --plano
"""
import collections
import csv
import datetime
import glob
import os
import re
import sys
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SO_PLANO = "--plano" in sys.argv
DIA = ARGS[0] if ARGS else "2026-08-31"
EGPS = os.path.join(RAIZ, "received_egps", "*", "*.egp")
OUT = os.path.join(AQUI, "BV_Migracao_SAS_Servidor_Por_EGP"
                   + ("_Plano" if SO_PLANO else "") + f"_{DIA}.csv")
MAX_BYTES = 400_000          # o contexto está no topo do log; não precisa ler tudo

RX_NODE = re.compile(rb"SAS_work[0-9A-Fa-f]+_([A-Za-z0-9\-]+)")
RX_PATH = re.compile(rb"_CLIENTPROJECTPATH\s*=\s*'([^']{1,400})'", re.S)
RX_HOST = re.compile(rb"_CLIENTPROJECTPATHHOST\s*=\s*'([^']{1,60})'")
RX_DATA = re.compile(rb"The SAS System\s+(\d{1,2}:\d{2})\s+([A-Za-z]+, [A-Za-z]+ \d{1,2}, \d{4})")
# o log quebra linha longa com um marcador de continuação: "\ns 5        ! resto"
RX_CONT = re.compile(rb"\r?\n[a-z]?\s*\d+\s*!\s?")
MESES = {m: i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}


def desdobra(raw):
    """Remove as quebras de continuação do log e devolve a string inteira."""
    return RX_CONT.sub(b"", raw).decode("latin1", "replace").strip()


def data_iso(dstr):
    try:
        _wd, resto = dstr.split(", ", 1)
        mes, dia_ano = resto.split(" ", 1)
        dia, ano = dia_ano.split(", ")
        return datetime.date(int(ano), MESES[mes], int(dia)).isoformat()
    except (ValueError, KeyError):
        return ""


# (nó, data) POR LOG — o inventário por nó precisa desse par. Agregar a data no grão do
# EGP inflaria a janela de cada nó (um EGP que rodou em 3 nós doaria seu range inteiro aos
# três), o que faz um nó desativado parecer ativo.
POR_NO = collections.defaultdict(lambda: {"logs": 0, "egps": set(), "datas": []})


def varre_egp(fp):
    nodes, hosts, paths, datas = collections.Counter(), collections.Counter(), collections.Counter(), []
    n_logs = 0
    try:
        z = zipfile.ZipFile(fp)
    except (zipfile.BadZipFile, OSError):
        return None
    for nm in z.namelist():
        if not re.search(r"(?i)\.log$|log\.txt$", nm):
            continue
        try:
            d = z.read(nm)[:MAX_BYTES]
        except (KeyError, OSError, zipfile.BadZipFile):
            continue
        n_logs += 1
        for m in RX_NODE.finditer(d):
            nodes[m.group(1).decode("latin1")] += 1
        m = RX_HOST.search(d)
        if m:
            hosts[desdobra(m.group(1))] += 1
        m = RX_PATH.search(d)
        if m:
            p = desdobra(m.group(1))
            if p:
                paths[p] += 1
        m = RX_DATA.search(d)
        iso = data_iso(m.group(2).decode("latin1")) if m else ""
        if iso:
            datas.append(iso)
        for no in {mm.group(1).decode("latin1") for mm in RX_NODE.finditer(d)}:
            POR_NO[no]["logs"] += 1
            POR_NO[no]["egps"].add(fp)
            if iso:
                POR_NO[no]["datas"].append(iso)
    return {"n_logs": n_logs, "nodes": nodes, "hosts": hosts, "paths": paths, "datas": datas}


def egps_do_plano(arquivos):
    """Casa o frontier `indi_deps` (chaves 'Área__Projeto') com os arquivos .egp por
    (área da pasta, nome sem extensão), com fallback só pelo nome. Devolve
    (arquivos_do_plano, chaves_sem_arquivo)."""
    sys.path.insert(0, os.path.join(RAIZ, "app", "backend"))
    import main as M
    frontier = M._frontier_egps("indi_deps", [])[0]
    idx = {}
    for fp in arquivos:
        stem = os.path.splitext(os.path.basename(fp))[0]
        idx[(os.path.basename(os.path.dirname(fp)), stem)] = fp
        idx.setdefault(stem, fp)
    sel, orfas = {}, []
    for chave in sorted(frontier):
        area, _, tail = chave.partition("__")
        fp = idx.get((area, tail)) or idx.get(tail)
        if fp:
            sel[fp] = chave
        else:
            orfas.append(chave)
    print(f"[plano] frontier {len(frontier)} EGPs | .egp encontrado para {len(sel)} "
          f"| sem arquivo: {len(orfas)}{' -> ' + ', '.join(orfas) if orfas else ''}")
    return sorted(sel), orfas


def main():
    arquivos = sorted(glob.glob(EGPS))
    print(f"[egps] {len(arquivos)} arquivos .egp no corpus")
    if SO_PLANO:
        arquivos, _orfas = egps_do_plano(arquivos)
    rows, sem_log, ilegivel = [], 0, 0
    for fp in arquivos:
        r = varre_egp(fp)
        if r is None:
            ilegivel += 1
            continue
        if not r["n_logs"]:
            sem_log += 1
        nodes, hosts, paths, datas = r["nodes"], r["hosts"], r["paths"], r["datas"]
        rows.append({
            "area": os.path.basename(os.path.dirname(fp)),
            "egp": os.path.basename(fp),
            "n_logs": r["n_logs"],
            "no_predominante": nodes.most_common(1)[0][0] if nodes else "",
            "n_nos": len(nodes),
            "nos": " | ".join(sorted(nodes)),
            "host_cliente": hosts.most_common(1)[0][0] if hosts else "",
            "hosts_clientes": " | ".join(sorted(hosts)),
            "caminho_do_egp": paths.most_common(1)[0][0] if paths else "",
            "log_mais_antigo": min(datas) if datas else "",
            "log_mais_recente": max(datas) if datas else "",
        })
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    com_no = [r for r in rows if r["no_predominante"]]
    print(f"[cobertura] {len(com_no)}/{len(rows)} EGPs com nó identificado "
          f"| {sem_log} sem nenhum log | {ilegivel} .egp ilegível")
    print(f"[cobertura] caminho de rede do .egp: "
          f"{sum(1 for r in rows if r['caminho_do_egp'])} | host cliente: "
          f"{sum(1 for r in rows if r['host_cliente'])}")
    print("\n== INVENTÁRIO DE NÓS (par nó↔data no MESMO log)")
    print(f"   {'nó':18s} {'logs':>6s} {'EGPs':>6s}  1ª execução .. última")
    for no, v in sorted(POR_NO.items(), key=lambda kv: -kv[1]["logs"]):
        ds = sorted(v["datas"])
        print(f"   {no:18s} {v['logs']:6d} {len(v['egps']):6d}  "
              f"{ds[0] if ds else '-'} .. {ds[-1] if ds else '-'}")

    print("\n== nó de computação predominante")
    for k, v in collections.Counter(r["no_predominante"] for r in com_no).most_common():
        print(f"   {v:5d}  {k}")
    print("\n== EGPs que rodaram em mais de um nó")
    print(f"   {sum(1 for r in com_no if r['n_nos'] > 1)} de {len(com_no)}")
    print("\n== tipo de host cliente")
    def tipo(h):
        if h.upper().startswith("VD-PRDROBO"):
            return "VD-PRDROBO* (robô/VDI de execução)"
        if h.upper().startswith("NBK"):
            return "NBK* (notebook de pessoa)"
        return "outro" if h else "(sem host)"
    for k, v in collections.Counter(tipo(r["host_cliente"]) for r in rows).most_common():
        print(f"   {v:5d}  {k}")
    print(f"\n[csv] {os.path.basename(OUT)} ({len(rows)} linhas)")


if __name__ == "__main__":
    main()

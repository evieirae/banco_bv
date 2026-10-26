#!/usr/bin/env python3
"""Quais grupos de acesso AD pedir para ler os inputs dos EGPs no servidor SAS.

Cruza os diretórios físicos dos inputs (coluna `path` do inventário) com a tabela
diretório→grupo do guia "GRUPOS DE ACESSO SAS" do BV, versionada em
`src/grupos_acesso_sas.csv` (109 diretórios; extraída do PDF do guia).

Casamento por PREFIXO MAIS LONGO: a pasta herda o grupo do diretório mais específico
que a contém — `/riscosbv/cobranca/erocha/CARTAO/MOVTO` → `/riscosbv/cobranca` →
`rski-cobrbc-prd-rw`. Diretório de tabela/lib JÁ é o diretório (o LIBNAME aponta para
a pasta); só arquivo/script tem o nome do arquivo removido.

Duas visões:
  1. recorte do plano (escopo Indicium + dependências), a partir do CSV gerado por
     `inputs_escopo_deps_caminhos_rede.py` — é o que se pede AGORA;
  2. corpus inteiro (todos os EGPs inventariados) — para pedir de uma vez só.

Fora do escopo deste script: `N:\\...`/UNC (share Windows, outro processo de acesso) e
`C:\\Users\\...` (máquina do analista, sem rota de acesso).

    python docs/analises/grupos_acesso_por_input.py [YYYY-MM-DD]
"""
import collections
import csv
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
DIA = sys.argv[1] if len(sys.argv) > 1 else "2026-08-31"
MAPA = os.path.join(RAIZ, "src", "grupos_acesso_sas.csv")
INVENTARIO = os.path.join(RAIZ, "06_prontidao_tabela.csv")
RECORTE = os.path.join(AQUI, f"BV_Migracao_SAS_Inputs_Escopo_Deps_Caminhos_Rede_{DIA}.csv")
OUT_GRUPOS = os.path.join(AQUI, f"BV_Migracao_SAS_Grupos_Acesso_SAS_{DIA}.csv")
OUT_SEM = os.path.join(AQUI, f"BV_Migracao_SAS_Diretorios_Sem_Grupo_{DIA}.csv")

CATS = {"table_in": "tabela", "file_in": "arquivo", "script_in": "script",
        "libname_in": "lib"}


def carrega_mapa():
    with open(MAPA, encoding="utf-8-sig") as fh:
        return {r["diretorio"]: r["grupo_ad"] for r in csv.DictReader(fh, delimiter=";")}


def dir_do_input(path, categoria):
    """tabela/lib: o path do LIBNAME já É o diretório. arquivo/script: tira o arquivo."""
    if categoria in ("tabela", "lib"):
        return path
    return path.rsplit("/", 1)[0] if "/" in path[1:] else path


def casa(mapa, d):
    """Prefixo mais longo presente no guia. Devolve (raiz_do_guia, grupo).

    Colapsa `//` — o corpus tem paths com barra dupla (`//riscosbv/cobranca/...`, que o
    SAS aceita); sem colapsar, o prefixo nunca casa e a pasta cai em "sem grupo"."""
    d = re.sub(r"/+", "/", d.lower()).rstrip("/")
    while d and d != "/":
        if d in mapa:
            return d, mapa[d]
        d = d.rsplit("/", 1)[0]
    return None, None


def novo():
    return {"inp": set(), "pend": set(), "egps": set(), "dirs": set(), "raizes": set()}


def agrega(mapa, registros):
    """registros: iterável de (path, categoria, artifact, egps:set, pendente:bool)."""
    ag, sem = collections.defaultdict(novo), collections.defaultdict(novo)
    for path, categoria, artifact, egps, pendente in registros:
        if not path.startswith("/") or "&" in path:
            continue
        d = dir_do_input(path, categoria)
        raiz, grupo = casa(mapa, d)
        alvo = ag[grupo] if grupo else sem[d]
        alvo["inp"].add(artifact)
        alvo["egps"] |= egps
        alvo["dirs"].add(d)
        if pendente:
            alvo["pend"].add(artifact)
        if raiz:
            alvo["raizes"].add(raiz)
    return ag, sem


def do_recorte():
    if not os.path.exists(RECORTE):
        print(f"[aviso] {os.path.basename(RECORTE)} não existe — rode primeiro "
              f"inputs_escopo_deps_caminhos_rede.py")
        return None
    with open(RECORTE, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            if not r["tipo_caminho"].startswith("servidor SAS"):
                continue
            pendente = (r["modernizada_auto"] != "Disponível"
                        and r["etapa"] != "Modernizado" and r["status"] != "Sanitizado")
            egps = set(r["egps_plano"].split(" | "))
            for p in r["caminhos"].split(" | "):
                yield p, r["categoria"], r["artifact"], egps, pendente


def do_corpus():
    with open(INVENTARIO, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cat = CATS.get(r["category"])
            if not cat:
                continue
            yield ((r["path"] or "").strip(), cat, r["artifact"],
                   {r["project"]}, False)


def imprime(titulo, ag, sem, com_pend=True):
    print(f"\n=== {titulo}")
    print(f"    grupos a pedir: {len(ag)} | inputs cobertos: "
          f"{sum(len(v['inp']) for v in ag.values())} | sem grupo no guia: "
          f"{sum(len(v['inp']) for v in sem.values())} inputs em {len(sem)} diretórios")
    cab = f"    {'grupo AD':32s} {'inputs':>7s}" + (f" {'pend':>5s}" if com_pend else "")
    print(cab + f" {'EGPs':>5s}  raiz(es) no guia")
    chave = (lambda kv: -len(kv[1]["pend"])) if com_pend else (lambda kv: -len(kv[1]["inp"]))
    for g, v in sorted(ag.items(), key=chave):
        linha = f"    {g:32s} {len(v['inp']):7d}"
        if com_pend:
            linha += f" {len(v['pend']):5d}"
        print(linha + f" {len(v['egps']):5d}  {', '.join(sorted(v['raizes']))}")


def main():
    mapa = carrega_mapa()
    print(f"[guia] {len(mapa)} diretórios em {os.path.relpath(MAPA, RAIZ)}")

    ag_r, sem_r = agrega(mapa, do_recorte() or ())
    imprime("RECORTE DO PLANO (escopo Indicium + dependências)", ag_r, sem_r)
    ag_c, sem_c = agrega(mapa, do_corpus())
    imprime("CORPUS INTEIRO (todos os EGPs inventariados)", ag_c, sem_c, com_pend=False)

    with open(OUT_GRUPOS, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["universo", "grupo_ad", "raizes_no_guia", "inputs", "inputs_pendentes",
                    "egps", "n_diretorios", "diretorios"])
        for uni, ag in (("plano", ag_r), ("corpus", ag_c)):
            chave = (lambda kv: -len(kv[1]["pend"])) if uni == "plano" else (lambda kv: -len(kv[1]["inp"]))
            for g, v in sorted(ag.items(), key=chave):
                w.writerow([uni, g, " | ".join(sorted(v["raizes"])), len(v["inp"]),
                            len(v["pend"]), len(v["egps"]), len(v["dirs"]),
                            " | ".join(sorted(v["dirs"]))])
    with open(OUT_SEM, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["universo", "diretorio", "inputs", "inputs_pendentes", "egps"])
        for uni, sem in (("plano", sem_r), ("corpus", sem_c)):
            for d, v in sorted(sem.items(), key=lambda kv: -len(kv[1]["inp"])):
                w.writerow([uni, d, len(v["inp"]), len(v["pend"]), len(v["egps"])])
    print(f"\n[csv] {os.path.basename(OUT_GRUPOS)}")
    print(f"[csv] {os.path.basename(OUT_SEM)}")


if __name__ == "__main__":
    main()

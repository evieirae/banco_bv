#!/usr/bin/env python3
"""Onde (fisicamente) moram os inputs do recorte "escopo Indicium + dependências".

Responde à pergunta da gestão: para os EGPs que vamos migrar, em que pasta de rede
(`N:\\...` = `\\\\bvnet\\global`), UNC, drive local ou diretório do servidor SAS está
cada input que ainda falta receber?

Por que um script novo: o app publica `paths_fisicos` SÓ para input SAS/Local-**tabela**
(resolução libref→path, publish_to_databricks.py:660-709). Para input `arquivo` a chave
é o basename, então o caminho — que o extrator capturou e o inventário guarda — não
chega ao Databricks. `gerar_pacote_migracao.py` reflete isso escrevendo "pedir à área"
no lugar do caminho. Aqui o caminho vem do inventário local (coluna `path` de
06_prontidao_tabela.csv) e é cruzado com o recorte vigente lido do app.

Recorte = o MESMO da aba Inputs com escopo "Indicium + Dependências": frontier
(_frontier_egps('indi_deps')) e a régua dos cards (vínculo ativo, sem ex-dependência).

    . app/venv/bin/activate
    PUBLISH_SCHEMA=monitoramento_sas DATABRICKS_CONFIG_PROFILE=bv \
      DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd \
      python docs/analises/inputs_escopo_deps_caminhos_rede.py [YYYY-MM-DD]
"""
import collections
import csv
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
DIA = sys.argv[1] if len(sys.argv) > 1 else "2026-08-31"
APP_BACKEND = os.environ.get("APP_BACKEND", os.path.join(RAIZ, "app", "backend"))
INVENTARIO = os.path.join(RAIZ, "06_prontidao_tabela.csv")
CSV_OUT = os.path.join(AQUI, f"BV_Migracao_SAS_Inputs_Escopo_Deps_Caminhos_Rede_{DIA}.csv")

# categoria do inventário -> categoria do monitor (IN_CATS do publish; libname_in fica
# fora porque o artefato dele é o libref, não um input do grão do monitor)
CATS_IN = {"table_in", "file_in", "script_in"}


def chave_art(art):
    """Artefato normalizado p/ o join local×prod. Prod grava a variante de planilha SEM
    aspas (`X.xlsx[SHEET=Plan1]`) e o inventário local COM (`X.xlsx[SHEET='Plan1']`) —
    sem tirar as aspas, 172 inputs `arquivo` (os xlsx com aba) ficavam sem caminho."""
    return (art or "").strip().upper().replace("'", "").replace('"', "")


def tipo_caminho(p):
    """Bucket do caminho físico — o eixo da pergunta "onde está o arquivo?".

    Letra de drive NÃO implica máquina local: no corpus, `N:`, `J:` e `M:` são
    mapeamentos do mesmo compartilhamento corporativo (`N:\\DVMD\\...` e
    `J:\\DVMD\\...` = `\\\\bvnet\\global\\DVMD\\...`; `M:\\COBRANCA`). O que
    caracteriza arquivo na máquina do analista é a raiz `Users` (C:\\Users\\<login>\\
    Downloads|OneDrive|Área de Trabalho), não a letra."""
    p = (p or "").strip()
    if not p:
        return "sem caminho"
    u = p.upper().replace("\\", "/")
    if re.match(r"^&|/&", u):
        return "macro-var não resolvida"
    if u.startswith("//"):
        return "UNC \\\\servidor"
    m = re.match(r"^([A-Z]):/*([^/]*)", u)
    if m:
        if m.group(2) == "USERS":
            return "drive local do usuário (C:\\Users)"
        return ("N: (pasta de rede)" if m.group(1) == "N"
                else f"outro drive mapeado ({m.group(1)}:)")
    if u.startswith("/"):
        return "servidor SAS (/...)"
    return "outro"


def drive(p):
    m = re.match(r"^([A-Za-z]):", (p or "").strip())
    return f"{m.group(1).upper()}:" if m else ("UNC" if (p or "").startswith("\\\\") else "")


def diretoria(p):
    """1º nível sob N:/UNC — a diretoria dona da pasta (DRSC, DVMD, DJUD...)."""
    u = (p or "").replace("\\", "/")
    partes = [x for x in u.split("/") if x and not x.endswith(":")]
    if u.upper().startswith("N:"):
        return partes[0] if partes else ""
    if u.startswith("//"):                      # //servidor/share/DIRETORIA/...
        return partes[2] if len(partes) > 2 else (partes[-1] if partes else "")
    if re.match(r"^[A-Za-z]:", u):              # J:/DVMD, M:/COBRANCA...
        return partes[0] if partes else ""
    return ""


def pasta(p):
    """Diretório do arquivo (sem o nome do arquivo e sem o sufixo [SHEET='...'])."""
    p = re.sub(r"\[SHEET=.*$", "", (p or "").strip())
    sep = "\\" if "\\" in p else "/"
    return p.rsplit(sep, 1)[0] if sep in p else p


def carrega_paths_locais():
    """(projeto, ARTEFATO) -> {caminhos} a partir do inventário local. O grão é
    projeto×artefato porque o mesmo nome de arquivo aparece em pastas diferentes
    conforme o EGP que o lê (mesma razão da identidade por (path, membro))."""
    idx = collections.defaultdict(set)
    with open(INVENTARIO, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["category"] not in CATS_IN:
                continue
            p = (r["path"] or "").strip()
            if p:
                idx[(r["project"], chave_art(r["artifact"]))].add(p)
    return idx


def main():
    sys.path.insert(0, os.path.abspath(APP_BACKEND))
    import main as M
    print(f"[backend] {os.path.realpath(APP_BACKEND)}")

    frontier, base = M._frontier_egps("indi_deps", [])
    linhas = M.inputs(scope="indi_deps", categoria=[], area=[])["rows"]
    # régua dos CARDS da aba Inputs: fora quem tem todos os vínculos quebrados e fora
    # input que só ex-dependência consome (mesmo critério de inputs_sem_ingestao_escopo_deps.py)
    cards = [r for r in linhas
             if r.get("vinculo_ativo") is not False and not r.get("ex_dependencia")]
    universo = {r["chave_canonica"]: r for r in cards}
    print(f"[recorte] frontier {len(frontier)} EGPs (base {len(base)}) | "
          f"{len(linhas)} linhas na tabela | {len(universo)} inputs no universo dos cards")

    fin = ", ".join(M.sql_lit(p) for p in frontier)
    vinculos = [r for r in M.run_sql(
        f"SELECT projeto, chave_canonica, artifact, categoria FROM {M.T_EGP} "
        f"WHERE projeto IN ({fin})") if r["chave_canonica"] in universo]
    area_de = {r["projeto"]: r["area"] for r in
               M.run_sql(f"SELECT projeto, area FROM {M.T_ND}")}
    print(f"[vínculos] {len(vinculos)} pares EGP×input dentro do recorte")

    locais = carrega_paths_locais()
    agg = {}          # chave_canonica -> registro consolidado
    sem_match = collections.Counter()
    for v in vinculos:
        ch, proj = v["chave_canonica"], v["projeto"]
        art = (v["artifact"] or "").strip()
        rec = agg.setdefault(ch, {"paths": set(), "egps": set(), "areas": set(),
                                  "artifact": art, "fonte": set()})
        rec["egps"].add(proj)
        rec["areas"].add(area_de.get(proj) or "(sem área)")
        ps = locais.get((proj, chave_art(art)))
        if ps:
            rec["paths"] |= ps
            rec["fonte"].add("inventário local")
        else:
            sem_match[ch] += 1
    # complemento: para tabela SAS/Local o app já publica paths_fisicos (libref→path)
    for ch, rec in agg.items():
        if not rec["paths"]:
            pf = (universo[ch].get("paths_fisicos") or "").strip()
            if pf:
                rec["paths"] = {x.strip() for x in pf.split("|") if x.strip()}
                rec["fonte"].add("paths_fisicos (prod)")

    rows = []
    for ch, rec in agg.items():
        u = universo[ch]
        ps = sorted(rec["paths"])
        tipos = collections.Counter(tipo_caminho(p) for p in ps) or {"sem caminho": 1}
        # tipo dominante = o mais específico p/ pedir acesso: rede > UNC > local > servidor
        ordem = ["N: (pasta de rede)", "outro drive mapeado", "UNC \\\\servidor",
                 "drive local do usuário (C:\\Users)", "servidor SAS (/...)",
                 "macro-var não resolvida", "outro", "sem caminho"]
        def _rank(t):
            for i, o in enumerate(ordem):
                if t.startswith(o):
                    return i
            return 99
        tipo = sorted(tipos, key=_rank)[0]
        dirs = sorted({diretoria(p) for p in ps if diretoria(p)})
        rows.append({
            "artifact": rec["artifact"],
            "categoria": u.get("categoria") or "",
            "origem": u.get("origem") or "",
            "etapa": u.get("etapa") or "",
            "status": u.get("status") or "",
            "modernizada_auto": u.get("modernizada_auto") or "",
            "tipo_caminho": tipo,
            "drives": " | ".join(sorted({drive(p) for p in ps if drive(p)})),
            "diretoria": " | ".join(dirs),
            "pastas": " | ".join(sorted({pasta(p) for p in ps})),
            "caminhos": " | ".join(ps),
            "n_caminhos": len(ps),
            "fonte_do_caminho": " | ".join(sorted(rec["fonte"])),
            "qtd_egps_plano": len(rec["egps"]),
            "areas": " | ".join(sorted(rec["areas"])),
            "egps_plano": " | ".join(sorted(rec["egps"])),
        })
    rows.sort(key=lambda r: (r["tipo_caminho"], -r["qtd_egps_plano"], r["artifact"]))

    with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    # ---- relatório ----
    def bloco(titulo, sel):
        sel = [r for r in sel]
        c = collections.Counter(r["tipo_caminho"] for r in sel)
        print(f"\n== {titulo} ({len(sel)} inputs)")
        for t, n in c.most_common():
            print(f"   {n:6d}  {t}")

    bloco("TODOS os inputs do escopo + dependências", rows)
    naofile = [r for r in rows if r["tipo_caminho"] == "sem caminho"
               and r["origem"] in ("BigQuery", "Transacional")]
    lacuna = [r for r in rows if r["tipo_caminho"] == "sem caminho" and r not in naofile]
    print(f"   (dos 'sem caminho': {len(naofile)} são tabela de banco/BigQuery — não têm "
          f"caminho de arquivo, é o esperado; {len(lacuna)} são lacuna real)")
    falta = [r for r in rows if r["modernizada_auto"] != "Disponível"
             and r["etapa"] not in ("Modernizado",) and r["status"] != "Sanitizado"]
    bloco("Só os que ainda faltam (não Disponível/Modernizado/Sanitizado)", falta)

    rede = [r for r in rows if r["tipo_caminho"].startswith(("N: (", "outro drive", "UNC"))]
    print(f"\n== Diretorias donas das pastas de rede ({len(rede)} inputs)")
    for d, n in collections.Counter(r["diretoria"] or "(?)" for r in rede).most_common():
        print(f"   {n:6d}  {d}")
    print("\n== Top pastas de rede por nº de inputs")
    pc = collections.Counter()
    for r in rede:
        for p in r["pastas"].split(" | "):
            if p:
                pc[p] += 1
    for p, n in pc.most_common(15):
        print(f"   {n:5d}  {p[:110]}")
    zerados = [r for r in rows if r["tipo_caminho"] == "sem caminho"]
    print(f"\n[join] {len(sem_match)} pares EGP×input sem caminho no inventário local; "
          f"{len(zerados)} inputs terminaram sem nenhum caminho (os outros foram cobertos "
          f"por outro EGP consumidor ou por paths_fisicos de prod)")
    print(f"\n[csv] {os.path.basename(CSV_OUT)} ({len(rows)} linhas)")


if __name__ == "__main__":
    main()

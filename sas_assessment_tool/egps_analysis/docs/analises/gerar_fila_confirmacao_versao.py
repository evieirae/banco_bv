# -*- coding: utf-8 -*-
"""Fila de CONFIRMAÇÃO DE VERSÃO — a quem perguntar, por qual EGP, antes de ingerir.

O corpus foi extraído em março/2026; a versão que temos de cada `.egp` pode estar
vencida, e ingerir input de um EGP que mudou é trabalho jogado fora. Este script
responde três perguntas que o app não responde:

1. **Que idade tem a versão que temos?** `project.xml` do `.egp` traz `<ModifiedOn>`
   (ticks .NET) — data real do último save no EG, não a data do arquivo em disco.
2. **Com quem falar?** o mesmo XML traz `<ModifiedBy>` e `<ModifiedByEGID>` (login
   corporativo) — é o autor do último save, não o coordenador da carteira. O
   responsável BV do app entra como quem convoca, não como quem responde.
3. **Quanto custa estar errado?** o nº de inputs pendentes que só existem por causa
   daquele EGP (`pend_exclusivo`) é o trabalho de ingestão em risco se a versão nova
   deixar de ler aquele dado. Input lido por 2+ EGPs quase nunca morre em todos ao
   mesmo tempo — esse segue sem esperar resposta.

Recorte e régua vêm do BACKEND DO APP via `gerar_pacote_migracao.carrega/calcula`
(frontier `indi_deps`, despriorizados fora), igual a [gerar_fila_ingestao.py].

    . egps_analysis/venv/bin/activate
    python docs/analises/gerar_fila_confirmacao_versao.py

Saídas em `docs/analises/`:
  · `BV_Migracao_SAS_Confirmacao_Versao_EGP_<data>.csv`  — uma linha por EGP de atuação
  · `BV_Migracao_SAS_Confirmacao_Versao_Autor_<data>.csv` — uma linha por autor (o pedido)
"""
import collections, csv, datetime, glob, importlib.util, os, re, unicodedata, zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))          # egps_analysis/
HOJE = datetime.date.today()
CORTE_MULTI = 2          # input lido por >= 2 EGPs não espera confirmação

spec = importlib.util.spec_from_file_location("G", os.path.join(AQUI, "gerar_pacote_migracao.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
d = G.carrega("bv"); c = G.calcula(d)
alvo, pend = c["alvo"], c["pend"]


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def ticks(v):
    """<ModifiedOn> é tick .NET: 100ns desde 0001-01-01."""
    try:
        return (datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=int(v) / 10)).date()
    except Exception:
        return None


CAMPOS = ("Label", "CreatedOn", "ModifiedOn", "ModifiedBy", "ModifiedByEGID")


def metadados(caminho):
    """Cabeçalho do project.xml (UTF-16): autor e data do último save no EG."""
    try:
        z = zipfile.ZipFile(caminho)
        bruto = z.read("project.xml")[:20000].decode("utf-16", "ignore")
    except Exception:
        return {}
    out = {}
    for tag in CAMPOS:
        m = re.search(rf"<{tag}>([^<]*)</{tag}>", bruto)
        if m:
            out[tag] = m.group(1).strip()
    out["mtime_zip"] = max((datetime.datetime(*i.date_time) for i in z.infolist()), default=None)
    return out


# --- varre o corpus uma vez
meta = {}
for f in glob.glob(os.path.join(RAIZ, "received_egps", "**", "*.egp"), recursive=True):
    m = metadados(f)
    if not m:
        continue
    m["arquivo"] = os.path.relpath(f, RAIZ)
    area, nome = os.path.basename(os.path.dirname(f)), os.path.basename(f)[:-4]
    meta[norm(area + "__" + nome)] = m
    meta.setdefault(norm(nome), m)

# --- EGPs que já receberam versão nova na rodada de set/26 (não perguntar de novo)
ja_nova = set()
troca = os.path.join(AQUI, "versoes_atualizadas_egp_2026-09", "BV_Migracao_SAS_Troca_EGP_2026-09-01.csv")
if os.path.exists(troca):
    with open(troca, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            for a in (r.get("egp_antigo") or "").split("|"):
                if a.strip():
                    ja_nova.add(norm(a.strip()))

# --- quantos EGPs de atuação leem cada input pendente
consumidores = collections.Counter()
for p, ps in pend.items():
    for r in ps:
        consumidores[r["artifact"]] += 1

linhas = []
for p, e in alvo.items():
    m = meta.get(norm(p)) or meta.get(norm(p.split("__")[-1])) or {}
    dt = ticks(m.get("ModifiedOn")) or (m["mtime_zip"].date() if m.get("mtime_zip") else None)
    ps = pend.get(p, [])
    excl = [r for r in ps if consumidores[r["artifact"]] < CORTE_MULTI]
    linhas.append(dict(
        egp=p, area=p.split("__")[0], nome=p.split("__")[-1],
        autor_ultimo_save=m.get("ModifiedBy", ""), login=m.get("ModifiedByEGID", ""),
        versao_que_temos=dt.isoformat() if dt else "",
        idade_meses=round((HOJE - dt).days / 30.44, 1) if dt else "",
        criado_em=(ticks(m.get("CreatedOn")).isoformat() if ticks(m.get("CreatedOn")) else ""),
        responsavel_bv=e["resp_bv"], mes_plano=e["mes"], etapa=e["etapa"], status=e["status"],
        pend_total=len(ps), pend_exclusivo=len(excl),
        ja_recebeu_versao_nova="sim" if norm(p) in ja_nova else "",
        arquivo=m.get("arquivo", "")))

linhas.sort(key=lambda x: (-x["pend_exclusivo"], -(x["idade_meses"] or 0)))
cols = ["egp", "area", "nome", "autor_ultimo_save", "login", "versao_que_temos", "idade_meses",
        "criado_em", "responsavel_bv", "mes_plano", "etapa", "status", "pend_total",
        "pend_exclusivo", "ja_recebeu_versao_nova", "arquivo"]
out_egp = os.path.join(AQUI, f"BV_Migracao_SAS_Confirmacao_Versao_EGP_{HOJE.isoformat()}.csv")
with open(out_egp, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, delimiter=";"); w.writeheader()
    for r in linhas:
        w.writerow({k: r[k] for k in cols})

# --- o pedido é por autor, não por EGP
aut = collections.defaultdict(lambda: dict(nome="", egps=[], pend=0, excl=0, meses=[], resp=set()))
for x in linhas:
    k = x["login"] or "(sem autor no project.xml)"
    g = aut[k]
    g["nome"] = x["autor_ultimo_save"] or k
    g["egps"].append(x); g["pend"] += x["pend_total"]; g["excl"] += x["pend_exclusivo"]
    if x["idade_meses"] != "":
        g["meses"].append(x["idade_meses"])
    g["resp"].add(x["responsavel_bv"].split()[0])
ordem = sorted(aut.items(), key=lambda kv: -kv[1]["excl"])
out_aut = os.path.join(AQUI, f"BV_Migracao_SAS_Confirmacao_Versao_Autor_{HOJE.isoformat()}.csv")
with open(out_aut, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["ordem", "login", "autor", "n_egps", "pend_total", "pend_exclusivo",
                "idade_media_meses", "responsaveis_bv", "egps"])
    for i, (k, g) in enumerate(ordem, 1):
        w.writerow([i, k, g["nome"], len(g["egps"]), g["pend"], g["excl"],
                    round(sum(g["meses"]) / len(g["meses"]), 1) if g["meses"] else "",
                    " | ".join(sorted(g["resp"])),
                    " | ".join(sorted(x["nome"] for x in g["egps"]))])

# --- console
com = [x for x in linhas if x["idade_meses"] != ""]
print(f"EGPs de atuação: {len(linhas)} | com data de versão: {len(com)} | "
      f"sem `.egp` casado: {len(linhas) - len(com)}")
fx = collections.Counter()
for x in com:
    i = x["idade_meses"]
    fx["<3m" if i < 3 else "3–6m" if i < 6 else "6–12m" if i < 12 else ">12m"] += 1
print("idade da versão que temos: " + " · ".join(f"{fx[k]} {k}" for k in ["<3m", "3–6m", "6–12m", ">12m"]))
tot_p = sum(x["pend_total"] for x in linhas); tot_e = sum(x["pend_exclusivo"] for x in linhas)
print(f"inputs pendentes ligados a esses EGPs: {tot_p} | exclusivos de 1 EGP (em risco): {tot_e}")
print(f"\n{'#':>3} {'excl':>5} {'pend':>5} {'EGPs':>5} {'idade':>6}  {'login':<22} coordenação")
for i, (k, g) in enumerate(ordem[:16], 1):
    md = round(sum(g["meses"]) / len(g["meses"]), 1) if g["meses"] else 0
    print(f"{i:>3} {g['excl']:>5} {g['pend']:>5} {len(g['egps']):>5} {md:>5}m  {k[:22]:<22} "
          f"{' | '.join(sorted(g['resp']))[:34]}")
print(f"\nCSV por EGP:   {out_egp}")
print(f"CSV por autor: {out_aut}")

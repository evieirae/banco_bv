# -*- coding: utf-8 -*-
"""Pastas priorizadas para pedido de acesso/download no servidor SAS.

Agrega a fila de ingestão (`BV_Migracao_SAS_Fila_Ingestao_<data>.csv`, gerada por
`gerar_fila_ingestao.py`) por **pasta física**, já que "cada libname pendente mapeia
para exatamente 1 diretório físico" — pedir acesso por pasta, não por tabela avulsa.

Critério de ranking: soma da `criticidade` (mesma régua da fila — Σ 1/pendências do EGP
por input) das tabelas pendentes daquela pasta. Não é contagem crua de EGPs: uma pasta
com muitas tabelas espalhadas por EGPs cheios de pendência pesa menos que uma pasta
pequena que fecha EGPs sozinha.

Só entram linhas com `categoria=tabela`, `pasta` preenchida e SEM `classe_a_resolver`
(exclui tier 0 — macro não expandida / cópia _BKP, ainda não resolvido o alvo real — e
tier 6 — sem caminho físico mapeado; essas não têm pasta acionável pra pedir acesso
ainda). Mesmo filtro que `gerar_fila_ingestao.py` usa pra montar o dict `pastas`.

Uso:
    . egps_analysis/venv/bin/activate
    python docs/analises/gerar_pastas_priorizadas_acesso.py
    # ou apontando pra uma fila específica:
    python docs/analises/gerar_pastas_priorizadas_acesso.py --fila BV_Migracao_SAS_Fila_Ingestao_2026-09-04.csv

Saída: BV_Migracao_SAS_Pastas_Priorizadas_Acesso_<data>.csv
"""
import argparse, collections, csv, datetime, glob, os

AQUI = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--fila", default=None, help="CSV da fila de ingestão (default: mais recente no diretório)")
args = ap.parse_args()

if args.fila:
    fila_path = os.path.join(AQUI, args.fila) if not os.path.isabs(args.fila) else args.fila
else:
    candidatos = sorted(glob.glob(os.path.join(AQUI, "BV_Migracao_SAS_Fila_Ingestao_*.csv")))
    if not candidatos:
        raise SystemExit("Nenhuma BV_Migracao_SAS_Fila_Ingestao_*.csv encontrada — rode gerar_fila_ingestao.py antes.")
    fila_path = candidatos[-1]

with open(fila_path, encoding="utf-8-sig") as f:
    linhas = list(csv.DictReader(f, delimiter=";"))

pastas = collections.defaultdict(lambda: dict(
    crit=0.0, n_tab=0, egps=set(), resps=set(), tiers=set(),
    fecha=0, quase=0, aberta=False,
))
for r in linhas:
    p = (r["pasta"] or "").strip()
    if not p or r["categoria"] != "tabela" or r["classe_a_resolver"]:
        continue
    g = pastas[p]
    g["crit"] += float(r["criticidade"])
    g["n_tab"] += 1
    g["egps"] |= {e.strip() for e in r["egps"].split("|") if e.strip()}
    g["resps"] |= {x.strip() for x in r["responsaveis"].split("|") if x.strip()}
    tier_n = r["tier"].split(" ")[0]
    g["tiers"].add(tier_n)
    if int(r["fecha_egp"] or 0):
        g["fecha"] += 1
    if int(r["egp_quase"] or 0):
        g["quase"] += 1
    if r["pasta_aberta"] == "sim":
        g["aberta"] = True

linhas_out = []
for p, g in pastas.items():
    linhas_out.append(dict(
        pasta=p,
        criticidade=round(g["crit"], 3),
        n_tabelas=g["n_tab"],
        n_egps=len(g["egps"]),
        criticidade_por_tabela=round(g["crit"] / g["n_tab"], 3),
        tier_mais_urgente=min(g["tiers"]),
        em_voo="sim" if g["aberta"] else "",
        egps_fecham_sozinho=g["fecha"],
        egps_quase_fecham=g["quase"],
        responsaveis=" | ".join(sorted(g["resps"])),
        egps=" | ".join(sorted(e.replace("Cobranças__", "") for e in g["egps"])),
    ))
linhas_out.sort(key=lambda r: -r["criticidade"])
for i, r in enumerate(linhas_out, 1):
    r["rank"] = i

cols = ["rank", "pasta", "criticidade", "criticidade_por_tabela", "n_tabelas", "n_egps",
        "tier_mais_urgente", "em_voo", "egps_fecham_sozinho", "egps_quase_fecham",
        "responsaveis", "egps"]
out = os.path.join(AQUI, f"BV_Migracao_SAS_Pastas_Priorizadas_Acesso_{datetime.date.today().isoformat()}.csv")
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
    w.writeheader()
    for r in linhas_out:
        w.writerow({k: r[k] for k in cols})

print(f"fila usada: {os.path.basename(fila_path)}")
print(f"{len(linhas_out)} pastas priorizadas -> {out}")
print(f"\n{'#':>3} {'crit':>6} {'c/tab':>6} {'tabs':>5} {'EGPs':>5} {'tier':>5} {'voo':>4}  pasta")
for r in linhas_out[:20]:
    print(f"{r['rank']:>3} {r['criticidade']:>6} {r['criticidade_por_tabela']:>6} "
          f"{r['n_tabelas']:>5} {r['n_egps']:>5} {r['tier_mais_urgente']:>5} {r['em_voo']:>4}  {r['pasta']}")

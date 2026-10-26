# -*- coding: utf-8 -*-
"""Fila de prioridade de INGESTÃO por input — escopo Indicium + dependências.

Ordena os inputs pendentes do plano `indi_deps` por **criticidade** = Σ (1 / pendências do EGP)
sobre os EGPs de atuação que leem aquele input: ser a última peça de um EGP vale 1,0; ser uma
de 28 vale 0,036. Volume de EGPs que leem o input NÃO é prioridade — um input lido por 8 EGPs
travados em 28 pendências cada não destrava ninguém.

Tiers (nesta ordem): 0 sanitizar (macro não expandida / _BKP / script — não é dado) · 1 concluir
o que já está em voo · 2 fecha um EGP sozinho · 3 EGP a <=2 inputs · 4 resto de pasta já aberta
(pasta com item em voo = atrito baixo) · 5 lote por pasta · 6 arquivo sem caminho físico.

Recorte e régua vêm do BACKEND DO APP (via gerar_pacote_migracao.carrega): frontier `indi_deps`,
`_aingerir` (Sanitizado e vínculo quebrado contam como resolvidos) e despriorizados fora. O script
imprime uma CONFERÊNCIA contra `main.inputs(scope='indi_deps')` — a fila deve bater com os cards
da aba Inputs, a menos dos inputs cujos únicos consumidores estão despriorizados/migrados.

    . egps_analysis/venv/bin/activate
    python docs/analises/gerar_fila_ingestao.py     # -> BV_Migracao_SAS_Fila_Ingestao_<data>.csv

Saída: um CSV com rank, tier, criticidade, fecha_egp, n_egps, mês mínimo, responsável BV, pasta
e a lista de EGPs por input. Companheiro de `gerar_pacote_migracao.py` (que faz as ondas por EGP).
"""
import collections, csv, datetime, importlib.util, os, re, sys
AQUI=os.path.dirname(os.path.abspath(__file__))
spec=importlib.util.spec_from_file_location("G", os.path.join(AQUI,"gerar_pacote_migracao.py"))
G=importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
d=G.carrega("bv"); c=G.calcula(d)
alvo, pend = c["alvo"], c["pend"]

# --- CONFERÊNCIA contra a aba Inputs do app (mesmo recorte, mesma régua dos cards)
import sys as _sys
_sys.path.insert(0, os.path.join(AQUI, "..", "..", "app", "backend"))
import main as _M
_rows=_M.inputs(scope="indi_deps", categoria=[], area=[])["rows"]
_cards=[x for x in _rows if x.get("vinculo_ativo") is not False and not x.get("ex_dependencia")]
def _ee(x):
    e=(x.get("etapa") or "").strip()
    return e or ("Modernizado" if (x.get("modernizada_auto") or "")=="Disponível" else "A Receber")
def _es(x):
    st=(x.get("status") or "").strip()
    return st or ("Concluído" if _ee(x)=="Modernizado" else "A Iniciar")
_app={x["artifact"] for x in _cards if _ee(x)!="Modernizado" and _es(x)!="Sanitizado"}
_meu={r["artifact"] for ps in pend.values() for r in ps}
print(f"[conferência] aba Inputs do app (indi_deps, régua dos cards): {len(_cards)} inputs no universo, "
      f"{len(_app)} pendentes")
print(f"[conferência] esta fila: {len(_meu)} pendentes | só no app: {len(_app-_meu)} "
      f"({', '.join(sorted(_app-_meu)[:3])}) | só na fila: {len(_meu-_app)}")
print("[conferência] a diferença são inputs cujos únicos consumidores estão despriorizados/migrados\n")

# --- inputs que precisam ser RESOLVIDOS antes de entrar na fila.
# NÃO é descarte: se o EGP lê, é dependência real. Macro não expandida significa que o
# inventário não sabe QUAL arquivo é (o `&ref`/`&DATA` é o período), não que o arquivo não
# exista; e uma cópia _BKP lida pelo EGP é uma leitura de verdade. Sanitizar aqui apagaria
# dependência real — só script não é dado.
MACRO=re.compile(r"&(amp;)?[A-Za-z_]")
SCRIPT=re.compile(r"\.(vbs|bat|exe|sh|py)$", re.I)
BKP=re.compile(r"_(BKP|BKUP|BACKUP)(_|\b|\.)", re.I)
def resolver(art):
    """('classe', 'ação') para o input que não pode ser enfileirado como está."""
    if SCRIPT.search(art):
        return "script (não é dado)", "descartar: é executável, não fonte"
    if MACRO.search(art):
        prefixo = re.split(r"&(amp;)?", art)[0].strip("_. ")
        if prefixo:
            return ("macro de período em nome conhecido",
                    f"resolver o parâmetro de '{prefixo}': qual período/safra — provável carga recorrente")
        return ("nome 100% macro", "ler o %let no código do EGP para descobrir o alvo real")
    if BKP.search(art):
        return ("cópia _BKP lida pelo EGP",
                "questionar a área: o modelo precisa da cópia ou só da tabela-fonte?")
    return "", ""
def descarte(art):
    return resolver(art)[0]

inp={}
for p, ps in pend.items():
    n=len(ps)                                    # pendências do EGP
    for r in ps:
        a=inp.setdefault(r["artifact"], dict(art=r["artifact"], cat=r["categoria"], etapa=r["etapa"],
            status=r["status"], path=r["path"], egps=set(), crit=0.0, fecha=0, quase=0, meses=[], resps=set()))
        a["egps"].add(p); a["crit"] += 1.0/n
        if n==1: a["fecha"] += 1
        if n<=2: a["quase"] += 1
        a["meses"].append(int(alvo[p]["mes"] or 9))
        a["resps"].add(alvo[p]["resp_bv"].split()[0])
for a in inp.values():
    a["mes"]=min(a["meses"]); a["desc"]=descarte(a["art"])

# --- pastas: uma pasta "aberta" (com item em voo) tem atrito ~0 p/ levar o resto
pastas=collections.defaultdict(lambda: dict(tab=[], crit=0.0, egps=set(), voo=0))
for a in inp.values():
    if a["cat"]=="tabela" and a["path"] and not a["desc"]:
        g=pastas[a["path"]]; g["tab"].append(a); g["crit"]+=a["crit"]; g["egps"]|=a["egps"]
        if G.em_voo(a): g["voo"]+=1
aberta={k for k,v in pastas.items() if v["voo"]}

def tier(a):
    if a["desc"]:                                   return 0, "0 · resolver antes de enfileirar (NAO e descarte)"
    if G.em_voo(a):                                 return 1, "1 · concluir o que esta em voo"
    if a["fecha"]:                                  return 2, "2 · fecha um EGP sozinho"
    if a["quase"]:                                  return 3, "3 · EGP a <=2 inputs"
    if a["cat"]=="tabela" and a["path"] in aberta:   return 4, "4 · resto de pasta ja aberta"
    if a["cat"]=="tabela" and a["path"]:            return 5, "5 · lote por pasta"
    return 6, "6 · arquivo / sem caminho"

linhas=[]
for a in sorted(inp.values(), key=lambda a:(tier(a)[0], -a["crit"], a["mes"], a["art"])):
    t,tn=tier(a)
    linhas.append(dict(tier=tn, input=a["art"], categoria=a["cat"], etapa=a["etapa"], status=a["status"],
        criticidade=round(a["crit"],3), fecha_egp=a["fecha"], egp_quase=a["quase"], n_egps=len(a["egps"]),
        mes_min=a["mes"], responsaveis=" | ".join(sorted(a["resps"])), pasta=a["path"],
        pasta_aberta="sim" if a["path"] in aberta else "", classe_a_resolver=a["desc"],
        acao=resolver(a["art"])[1],
        egps=" | ".join(sorted(x.replace("Cobranças__","") for x in a["egps"]))))
for i,r in enumerate(linhas,1): r["rank"]=i
cols=["rank","tier","input","criticidade","fecha_egp","egp_quase","n_egps","mes_min","responsaveis",
      "categoria","etapa","status","pasta","pasta_aberta","classe_a_resolver","acao","egps"]
out=os.path.join(AQUI, f"BV_Migracao_SAS_Fila_Ingestao_{datetime.date.today().isoformat()}.csv")
with open(out,"w",newline="",encoding="utf-8-sig") as f:
    w=csv.DictWriter(f,fieldnames=cols,delimiter=";"); w.writeheader()
    for r in linhas: w.writerow({k:r[k] for k in cols})

print(f"inputs pendentes no plano: {len(inp)}")
por=collections.Counter(r["tier"] for r in linhas)
for k in sorted(por): print(f"  {por[k]:>4}  {k}")
print(f"\nCSV: {out}")
print("\n=== TIER 0 · resolver antes de enfileirar (NÃO sanitizar)")
cl=collections.Counter(a["desc"] for a in inp.values() if a["desc"])
for m,n in cl.most_common():
    it=[a for a in inp.values() if a["desc"]==m]
    print(f"  {n:>3} itens | crit {round(sum(x['crit'] for x in it),2):>5} — {m}")
    print(f"        ação: {resolver(it[0]['art'])[1][:96]}")
    for x in sorted(it,key=lambda x:-x["crit"])[:3]:
        print(f"        · crit {round(x['crit'],3):<6} {x['art'][:46]}")
print("\n=== TIER 1..3 · topo da fila")
print(f"{'#':>3} {'crit':>5} {'fecha':>5} {'EGPs':>4} {'mês':>3}  {'input':<42} {'tier':<30} resp")
for r in linhas:
    if not r["tier"].startswith(("1","2","3")): continue
    if r["criticidade"]<0.2 and not r["fecha_egp"]: continue
    print(f"{r['rank']:>3} {r['criticidade']:>5} {r['fecha_egp']:>5} {r['n_egps']:>4} {r['mes_min']:>3}  "
          f"{r['input'][:42]:<42} {r['tier'][:30]:<30} {r['responsaveis'][:22]}")
print("\n=== PASTAS · impacto total e por tabela (top 16)")
print(f"{'crit':>6} {'tabs':>5} {'EGPs':>5} {'c/tab':>6} {'aberta':>6}  pasta")
for path,g in sorted(pastas.items(), key=lambda kv:-kv[1]["crit"])[:16]:
    ct=g["crit"]/max(1,len(g["tab"]))
    print(f"{round(g['crit'],2):>6} {len(g['tab']):>5} {len(g['egps']):>5} {round(ct,3):>6} {'sim' if g['voo'] else '':>6}  {path[:64]}")
print("\n=== PASTAS · melhor retorno por tabela (min 8 tabelas)")
elig=[(k,v) for k,v in pastas.items() if len(v["tab"])>=8]
for path,g in sorted(elig, key=lambda kv:-(kv[1]["crit"]/len(kv[1]["tab"])))[:10]:
    print(f"{round(g['crit']/len(g['tab']),3):>6} c/tab | {len(g['tab']):>3} tabs | {len(g['egps']):>2} EGPs | {'aberta' if g['voo'] else '      '} | {path[:60]}")

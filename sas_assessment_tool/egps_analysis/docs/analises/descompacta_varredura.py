# Varre text_egps/: para cada input atribuído ao %DESCOMPACTA no TABLE_READ_PROVENANCE,
# verifica se a base descompactada é LIDA depois (SET/FROM/DATA=/MERGE/UPDATE/JOIN) no
# corpo do programa. Sem leitura => input falso (só manutenção de disco).
import csv, io, os, re, sys, glob, collections

BASE = "/home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/descompacta_scan.csv"

PROV = re.compile(r"([^\[,][^\[]*?)\s\[([^\]]*)\]")
MECANICA = re.compile(r"^\s*(x\s+(cp|gunzip|gzip|mv|rm)\b|%DESCOMPACTA\s*\(|%compacta\w*\s*\(|%let\s|%mend|%macro\s)", re.I)

def leituras(corpo_linhas, membro):
    m = re.escape(membro)
    pats = [rf"\bset\b[^;]*\b{m}\b", rf"\bfrom\b[^;]*\b{m}\b", rf"\bdata\s*=\s*\w*\.?{m}\b",
            rf"\bmerge\b[^;]*\b{m}\b", rf"\bjoin\b[^;]*\b{m}\b", rf"\bupdate\b[^;]*\b{m}\b",
            rf"\bin\s*=\s*\w*\.?{m}\b", rf"\bbase\s*=\s*\w*\.?{m}\b"]
    rx = re.compile("|".join(pats), re.I)
    hits = []
    for i, ln in enumerate(corpo_linhas, 1):
        if MECANICA.match(ln):
            continue
        if rx.search(ln):
            hits.append(i)
    return hits

linhas_csv, veredito_ct = [], collections.Counter()
n_arq = n_com = 0
for path in sorted(glob.glob(os.path.join(BASE, "text_egps", "*.txt"))):
    try:
        txt = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    n_arq += 1
    cab, _, corpo = txt.partition("END_METADATA")
    prov_line = ""
    for ln in cab.splitlines():
        if ln.startswith("TABLE_READ_PROVENANCE"):
            prov_line = ln.split(":", 1)[1]
            break
    if "%DESCOMPACTA" not in prov_line:
        continue
    n_com += 1
    egp = os.path.basename(path)[:-4]
    corpo_linhas = corpo.splitlines()
    for tabela, provs in PROV.findall(prov_line):
        if "%DESCOMPACTA" not in provs:
            continue
        tabela = tabela.strip().strip(",").strip()
        membro = tabela.split(".")[-1]
        if not membro or "&" in membro:
            hits, veredito = [], "indeterminado (nome dinamico)"
        else:
            hits = leituras(corpo_linhas, membro)
            veredito = "lido depois" if hits else "NUNCA LIDO"
        veredito_ct[veredito] += 1
        linhas_csv.append({"egp": egp, "tabela": tabela, "membro": membro,
                           "veredito": veredito, "n_leituras": len(hits),
                           "linhas_leitura": ";".join(str(h) for h in hits[:5])})

with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["egp", "tabela", "membro", "veredito", "n_leituras", "linhas_leitura"], delimiter=";")
    w.writeheader(); w.writerows(linhas_csv)

print(f"arquivos varridos: {n_arq} | com input de %DESCOMPACTA: {n_com}")
print(f"inputs de descompacta: {len(linhas_csv)}")
for k, v in veredito_ct.most_common():
    print(f"  {k:30s} {v}")
print(f"\nEGPs distintos afetados: {len({l['egp'] for l in linhas_csv})}")
print(f"tabelas distintas: {len({l['tabela'] for l in linhas_csv})}")
print(f"CSV: {OUT}")

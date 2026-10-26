#!/usr/bin/env python3
"""Verifica e valida referências via macro (DYNAMIC REFS) entre EGPs.

O extrator manda toda referência de tabela com macro (LIB.BASE_&MES) para a
linha `DYNAMIC REFS (Ambiguous):` do txt — sem dizer se é leitura ou escrita.
Este script fecha essa lacuna em 3 etapas:

  1. Casa cada padrão dinâmico (LIB.NOME_{VAR}) com outputs concretos dos EGPs
     do corpus (candidatos a produtor), exigindo >=4 chars literais no membro.
  2. Volta ao código SAS do consumidor e classifica cada ocorrência da
     referência como leitura (FROM/JOIN/SET/MERGE/DATA=) ou escrita
     (CREATE TABLE/DATA lib.x/BASE=/OUT=), guardando o trecho de evidência.
  3. Tenta resolver o %LET da variável; se o valor for literal, confere se o
     nome resolvido bate com um output concreto do produtor candidato.

Saída: docs/analises/macro_refs_validacao.csv (; + BOM, p/ Excel) e resumo no
stdout. Vereditos:
  - dependencia_provavel   -> consumidor só LÊ o padrão (aresta escondida real)
  - producao_propria       -> consumidor só GRAVA (falso positivo de dependência;
                              na verdade é mais um produtor da família)
  - le_e_grava             -> lê e grava (auto-alimentado dinâmico)
  - indeterminado          -> ocorrências sem contexto claro; revisar no código

Uso: python validate_macro_refs.py  (da pasta egps_analysis/; lê text_egps/)
Opcional: --api http://localhost:8000 p/ marcar consumidores do recorte indi+deps.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

TXT_DIR = Path(__file__).parent / "text_egps"
OUT_CSV = Path(__file__).parent / "docs" / "analises" / "macro_refs_validacao.csv"

MIN_LITERAL = 4  # chars literais mínimos no membro p/ aceitar um casamento

# contexto de ESCRITA imediatamente antes da referência
WRITE_BEFORE = re.compile(
    r"(create\s+table\s+(if\s+not\s+exists\s+)?|"      # proc sql
    r"\bdata\s+(?:[a-z0-9_&.]+\s+)*|"                   # data lib.a lib.b;
    r"\bbase\s*=\s*|"                                    # proc append base=
    r"\bout\s*=\s*|\boutdata\s*=\s*)$",
    re.I,
)
# contexto de LEITURA imediatamente antes da referência
READ_BEFORE = re.compile(
    r"(\bfrom\s+|\bjoin\s+|\bset\s+(?:[a-z0-9_&.]+\s+)*|\bmerge\s+(?:[a-z0-9_&.()=]+\s+)*|"
    r"\bdata\s*=\s*)$",
    re.I,
)
LET_RE = r"%let\s+{var}\s*=\s*([^;]*);"


def parse_corpus(txt_dir: Path):
    """Extrai por projeto: dynamic refs, outputs concretos e corpo do código."""
    dyn, outs, body = {}, {}, {}
    for txt in sorted(txt_dir.glob("*.txt")):
        text = txt.read_text(encoding="utf-8", errors="replace")
        head = text[:20000]
        m = re.search(r"^PROJECT:\s*(.+)$", head, re.M)
        proj = m.group(1).strip() if m else txt.stem
        md = re.search(r"^DYNAMIC REFS \(Ambiguous\):\s*(.+)$", head, re.M)
        if md:
            payload = md.group(1).strip()
            if payload and not payload.startswith("---") and payload.lower() != "(none)":
                toks = sorted({t.strip().upper() for t in payload.split(", ") if "{" in t})
                if toks:
                    dyn[proj] = toks
        mo = re.search(r"^PERMANENT OUTPUTS.*?:\s*(.+)$", head, re.M)
        if mo:
            toks = sorted({t.strip().upper() for t in mo.group(1).split(", ")
                           if t.strip() and "&" not in t and t.strip().lower() != "(none)"})
            if toks:
                outs[proj] = toks
        cut = text.find("END_METADATA")
        body[proj] = text[cut:] if cut > 0 else text
    return dyn, outs, body


def pattern_regexes(pattern: str):
    """`LIB.NOME_{VAR}` -> (regex p/ outputs concretos, regex p/ código com &VAR)."""
    lib, member = pattern.split(".", 1)
    literal = re.sub(r"\{[^}]*\}", "", member)
    if len(literal) < MIN_LITERAL:
        return None, None, None
    parts = re.split(r"(\{[^}]*\})", member)
    concrete, code = [], [re.escape(lib) + r"\."]
    for p in parts:
        if p.startswith("{"):
            concrete.append(".+")
            code.append(r"&" + re.escape(p[1:-1]) + r"\.?")
        else:
            concrete.append(re.escape(p))
            code.append(re.escape(p))
    vars_ = re.findall(r"\{([^}]*)\}", member)
    return (re.compile("^" + "".join(concrete) + "$"),
            re.compile("".join(code), re.I), vars_)


def classify_occurrences(code: str, code_rx: re.Pattern):
    """Classifica cada ocorrência da referência no código como leitura/escrita."""
    reads, writes, unknown = [], [], []
    for m in code_rx.finditer(code):
        before = re.sub(r"\s+", " ", code[max(0, m.start() - 90):m.start()])
        line_start = code.rfind("\n", 0, m.start()) + 1
        line_end = code.find("\n", m.end())
        snippet = code[line_start:line_end if line_end > 0 else None].strip()[:160]
        if WRITE_BEFORE.search(before):
            writes.append(snippet)
        elif READ_BEFORE.search(before):
            reads.append(snippet)
        else:
            unknown.append(snippet)
    return reads, writes, unknown


def resolve_lets(code: str, vars_: list[str]):
    """%LET VAR = valor; -> literal, 'dinamico' (tem %/&) ou 'nao_encontrado'."""
    res = {}
    for v in vars_:
        vals = re.findall(LET_RE.format(var=re.escape(v)), code, re.I)
        if not vals:
            res[v] = "nao_encontrado"
        else:
            last = vals[-1].strip()
            res[v] = last if last and "%" not in last and "&" not in last else "dinamico"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000",
                    help="URL do backend local p/ marcar o recorte (opcional)")
    args = ap.parse_args()

    frontier = {}
    try:
        rows = json.load(urllib.request.urlopen(
            args.api + "/api/egp-readiness?scope=indi_deps", timeout=120))["rows"]
        frontier = {r["projeto"]: ("escopo" if r.get("escopo_indi") else "dependência")
                    for r in rows}
        print(f"recorte carregado do app: {len(frontier)} EGPs")
    except Exception as e:
        print(f"aviso: recorte indisponível ({e}); coluna no_recorte ficará vazia")

    dyn, outs, body = parse_corpus(TXT_DIR)
    producers = defaultdict(list)
    for proj, toks in outs.items():
        for o in toks:
            if "." in o:
                lib, member = o.split(".", 1)
                producers[lib].append((member, proj))

    rows = []
    for cons, patterns in sorted(dyn.items()):
        code = body.get(cons, "")
        for pat in patterns:
            if "." not in pat.split("{")[0]:
                continue
            lib, _ = pat.split(".", 1)
            concrete_rx, code_rx, vars_ = pattern_regexes(pat)
            if not concrete_rx:
                continue
            matched = defaultdict(list)  # produtor -> exemplos
            for member, prod in producers.get(lib, ()):
                if concrete_rx.match(member):
                    matched[prod].append(f"{lib}.{member}")
            if not matched:
                continue
            reads, writes, unknown = classify_occurrences(code, code_rx)
            lets = resolve_lets(code, vars_)
            resolved = None
            if all(v not in ("dinamico", "nao_encontrado") for v in lets.values()):
                name = pat
                for v, val in lets.items():
                    name = name.replace("{" + v + "}", val.upper())
                resolved = name
            if writes and reads:
                verdict = "le_e_grava"
            elif reads:
                verdict = "dependencia_provavel"
            elif writes:
                verdict = "producao_propria"
            else:
                verdict = "indeterminado"
            for prod, exemplos in sorted(matched.items()):
                bate = ""
                if resolved:
                    bate = "sim" if resolved in (f"{lib}.{m}" for m, p in
                                                 producers.get(lib, ()) if p == prod) else "nao"
                rows.append({
                    "consumidor": cons,
                    "no_recorte": frontier.get(cons, ""),
                    "padrao": pat,
                    "vars_macro": ", ".join(vars_),
                    "resolucao_let": "; ".join(f"{v}={lets[v]}" for v in vars_),
                    "nome_resolvido": resolved or "",
                    "produtor_candidato": prod,
                    "produtor_eh_o_proprio": "sim" if prod == cons else "",
                    "exemplos_output_produtor": " | ".join(exemplos[:3]),
                    "resolvido_bate_com_produtor": bate,
                    "n_leituras": len(reads),
                    "n_escritas": len(writes),
                    "n_indeterminadas": len(unknown),
                    "veredito": verdict,
                    "evidencia_leitura": (reads or [""])[0],
                    "evidencia_escrita": (writes or [""])[0],
                })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys()) if rows else []
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"\n{len(rows)} pares (consumidor x padrao x produtor) validados -> {OUT_CSV}")
    print("vereditos:", dict(Counter(r["veredito"] for r in rows)))
    rec = [r for r in rows if r["no_recorte"]]
    print(f"no recorte: {len(rec)} |",
          dict(Counter(r["veredito"] for r in rec)))
    dep = [r for r in rec if r["veredito"] == "dependencia_provavel"
           and not r["produtor_eh_o_proprio"]]
    print(f"dependencias escondidas PROVAVEIS no recorte: {len(dep)} "
          f"({len({r['consumidor'] for r in dep})} consumidores)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

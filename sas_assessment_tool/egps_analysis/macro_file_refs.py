"""Refs de ARQUIVO macro-aware a partir do header de um .txt de extração.

Contexto (PLANO_JUNCAO_ARQUIVOS_MACRO.md): handoffs EGP→EGP via arquivo
exportado/importado são invisíveis no match exato — inputs guardam a macro
HTML-escapada (&AMP;DIA.), outputs crua (&DIA_EXEC.), e produtor/consumidor
usam macros de nomes diferentes p/ o mesmo arquivo. Este módulo extrai as
refs com caminho completo do header (EXPORTED FILES / IMPORTED FILES /
EXTERNAL FILE PATHS — fase 1: 99% têm dir explícito), resolve macros
ESTÁTICAS via %LET do próprio EGP (iterativo até ponto fixo) e reduz as
voláteis a curinga '#' (esqueleto).

Usado pelo orchestrator_inventory (passada aditiva de arestas por arquivo —
corpus atual, sem re-extração) e pelo egps_extractor (seção FILE_REFS_MACRO
em extrações futuras).
"""

import html
import os
import re
from dataclasses import dataclass

# Macro exige terminador '.' OU nome com 2+ chars: '&C' solto (342x no corpus)
# é '&' literal em nomes tipo "M&C", não macro — fase 1, 2026-08-10.
MACRO_RE = re.compile(r"&([A-Za-z_][A-Za-z0-9_]+\.?|[A-Za-z_]\.)")
LET_RE = re.compile(r"%LET\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;\n]*);", re.I)

_HEADER_OUT = ("EXPORTED FILES (Artifacts):",)
_HEADER_IN = ("IMPORTED FILES (Requires Ingestion):", "EXTERNAL FILE PATHS (fluxo EG):")

# esqueleto precisa de massa própria p/ o match ter significado (guarda anti-REGRAS)
MIN_UTEIS = 8
EXT_RE = re.compile(r"\.[A-Za-z0-9]{2,4}$")


@dataclass(frozen=True)
class FileRef:
    lado: str            # "out" | "in"
    path_bruto: str      # como está no header (unescaped de &amp;)
    dir_resolvido: str   # diretório com %LET estáticos expandidos ('' se irresolvível)
    nome_skeleton: str   # basename maiúsculo com &MACRO. → '#'
    macros: tuple        # macros presentes no path (upper, sem & e .)
    confiavel: bool      # skeleton passa nas guardas (extensão + massa mínima)


def parse_lets(txt: str) -> dict:
    """%LETs do .txt inteiro (header PROJECT LETS + corpo das tasks), upper-keyed.
    Última atribuição vence — aproximação consciente: o valor exato de macro de
    DATA não importa (vira curinga); p/ macro de CAMINHO o último valor é o
    comportamento comum (setup no topo do projeto)."""
    return {m.group(1).upper(): m.group(2).strip() for m in LET_RE.finditer(txt)}


def resolve_static(texto: str, lets: dict, max_iter: int = 8) -> str:
    """Expande &MACRO. com valor em `lets`, iterativo até ponto fixo (macros de
    caminho aninhadas: &base_robbu → /riscosbv/...&dia._RODAS.csv). Macros sem
    %LET ficam intactas (viram curinga no esqueleto)."""
    for _ in range(max_iter):
        def _sub(m):
            nome = m.group(1).rstrip(".").upper()
            return lets[nome] if nome in lets else m.group(0)
        novo = MACRO_RE.sub(_sub, texto)
        if novo == texto:
            break
        texto = novo
    return texto


def _norm(s: str) -> str:
    return html.unescape(s or "").strip()


def _split_dir_nome(path: str):
    p = path.replace("\\", "/")
    if "/" in p:
        d, n = p.rsplit("/", 1)
        return d, n
    return "", p


_SHEET_RE = re.compile(r"\[SHEET=.*\]$", re.I)


def skeleton(nome: str) -> str:
    # variante [SHEET=...] aponta pro MESMO arquivo físico (o pipeline já colapsa
    # essas variantes) — sai do esqueleto p/ casar com o export, que nunca tem sheet
    nome = _SHEET_RE.sub("", nome.strip())
    return MACRO_RE.sub("#", nome.upper().replace("&AMP;", "&"))


def _confiavel(sk: str) -> bool:
    uteis = len(re.sub(r"[#.\s]", "", sk))
    return uteis >= MIN_UTEIS and bool(EXT_RE.search(sk))


def _refs_da_linha(txt: str, tags) -> list:
    out = []
    for tag in tags:
        m = re.search(re.escape(tag) + r"(.*)", txt)
        if not m or "(none)" in m.group(1):
            continue
        out += [_norm(x) for x in m.group(1).split(",") if _norm(x)]
    return sorted(set(out))


def file_refs(txt: str) -> list:
    """FileRefs (in+out) de um .txt de extração já lido em memória."""
    lets = parse_lets(txt)
    refs = []
    for lado, tags in (("out", _HEADER_OUT), ("in", _HEADER_IN)):
        for bruto in _refs_da_linha(txt, tags):
            resolvido = resolve_static(bruto, lets)
            d, nome = _split_dir_nome(resolvido)
            # dir só é utilizável se ficou sem macro pendente após a resolução
            dir_ok = d if (d and not MACRO_RE.search(d)) else ""
            sk = skeleton(nome)
            refs.append(FileRef(
                lado=lado,
                path_bruto=bruto,
                dir_resolvido=dir_ok.upper().rstrip("/"),
                nome_skeleton=sk,
                macros=tuple(sorted({m.rstrip(".").upper() for m in MACRO_RE.findall(bruto)})),
                confiavel=_confiavel(sk),
            ))
    return refs


def file_refs_de_arquivo(path_txt: str) -> list:
    with open(path_txt, encoding="utf-8", errors="replace") as fh:
        return file_refs(fh.read())


def formata_secao(refs: list) -> str:
    """Seção FILE_REFS_MACRO p/ o header do extractor (1 linha por ref, campos
    separados por '|'; parseável de volta com split)."""
    linhas = ["[[ FILE_REFS_MACRO ]]"]
    for r in refs:
        linhas.append("|".join([
            r.lado.upper(), r.path_bruto, r.dir_resolvido, r.nome_skeleton,
            ",".join(r.macros), "ok" if r.confiavel else "suspeito",
        ]))
    return "\n".join(linhas)


if __name__ == "__main__":
    # smoke-test nos casos golden do plano
    import sys
    base = os.path.join(os.path.dirname(__file__), "text_egps")
    alvos = sys.argv[1:] or [
        "Cobranças__Elegibilidade_Gradativo_20251103_reap_v12 - Expansao_custas.txt",
        "Cobranças__Validacao_boletos - V6.txt",
    ]
    for nome in alvos:
        p = nome if os.path.isabs(nome) else os.path.join(base, nome)
        print(f"== {os.path.basename(p)} ==")
        for r in file_refs_de_arquivo(p):
            if "#" in r.nome_skeleton or not r.confiavel:
                print(f"  {r.lado:3} | dir={r.dir_resolvido or '(irres.)'} | skel={r.nome_skeleton} | "
                      f"macros={','.join(r.macros)} | {'ok' if r.confiavel else 'SUSPEITO'}")

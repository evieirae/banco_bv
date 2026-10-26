# -*- coding: utf-8 -*-
"""Compara as leituras do app antigo (Databricks) com as do novo (Postgres) — ADR 0005.

Critério de pronto da Fase 1: para cada rota GET, o JSON do app novo é igual ao do antigo
partindo dos mesmos dados. Antes de comparar, normaliza só o que é FORMA e não conteúdo:
texto vazio = nulo (as telas tratam igual), instantes = UTC ao segundo, números = valor.
Ordem de lista NÃO é normalizada — ordem diferente é diferença real (NULLs primeiro no
Spark, por último no Postgres) e aparece marcada como "só ordem" para ajudar o diagnóstico.

Uso: python -m paridade.compara --antigo http://localhost:8000 --novo http://localhost:8001 \
         --saida paridade/relatorio.json [--rota /api/config ...]
"""
import argparse
import datetime
import fnmatch
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_INSTANTE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_NUMERO = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")

# Listas SEM ordem definida na origem — a ordem muda até entre dois processos do MESMO app,
# então ordem diferente aqui não é diferença: compara como multiconjunto. Cada entrada diz
# por quê; lista com ORDER BY nunca entra aqui.
ORDEM_LIVRE = {
    "/api/lineage/graph": (("$.blocked", "set do Python"), ("$.dep_of.*", "set do Python")),
    "/api/inputs-egps": (("$.rows", "SQL sem ORDER BY (export CSV)"),),
    "/api/outputs-egps": (("$.rows", "SQL sem ORDER BY (export CSV)"),),
}
# Diferenças POR DESENHO entre o app do Databricks e o da AWS (ADR 0005), com o motivo.
ACEITAS = {
    "/api/health": (("$.table", "nome qualificado do schema"), ("$.warehouse", "não há warehouse na AWS")),
    "/api/config": (("$.scope", "nome qualificado do schema"),
                    ("$.sincronizado_em", "só existe na AWS"),
                    ("$.somente_leitura", "AWS em modo leitura")),
    "/api/me": (("$.papel", "papel só existe no Postgres"),),
}
# Rotas que ficam de fora de propósito.
FORA = {"/api/prioridades": "sas_egp_prioridades não migra (spec): rota sem tela"}


def _base(rota):
    return urllib.parse.urlsplit(rota).path


def _casa(caminho, padroes):
    return next((m for p, m in padroes if fnmatch.fnmatchcase(caminho, p)), None)


def normaliza(v):
    if isinstance(v, dict):
        return {k: normaliza(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [normaliza(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        if _INSTANTE.match(s):
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if _NUMERO.match(s) and not (len(s) > 1 and s[0] == "0" and s[1] != "."):
            return float(s)          # "0012" fica texto: é identificador, não número
        return v
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def diferencas(a, b, caminho="$", limite=50, livres=()):
    """Lista de (caminho, antigo, novo) — no máximo `limite` itens. `livres`: padrões
    (fnmatch, com motivo) de listas comparadas como multiconjunto (ver ORDEM_LIVRE)."""
    saida = []

    def anda(x, y, c):
        if len(saida) >= limite:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                anda(x.get(k, "<ausente>"), y.get(k, "<ausente>"), f"{c}.{k}")
        elif isinstance(x, list) and isinstance(y, list) and _casa(c, livres):
            chave = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
            if sorted(map(chave, x)) != sorted(map(chave, y)):
                saida.append((f"{c}[multiconjunto]", len(x), len(y)))
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                saida.append((f"{c}[len]", len(x), len(y)))
            for i, (p, q) in enumerate(zip(x, y)):
                anda(p, q, f"{c}[{i}]")
        elif x != y:
            saida.append((c, x, y))

    anda(a, b, caminho)
    return saida


def so_ordem(a, b):
    """True quando as listas têm os mesmos itens em ordem diferente."""
    if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
        return False
    chave = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
    return sorted(map(chave, a)) == sorted(map(chave, b))


def rotas_get(app):
    """Rotas GET da API sem parâmetro de caminho (as com {id} entram na 1b, com amostras)."""
    rotas = []
    for r in app.routes:
        caminho = getattr(r, "path", "")
        if "GET" in getattr(r, "methods", set()) and caminho.startswith("/api/") and "{" not in caminho:
            rotas.append(caminho)
    return sorted(set(rotas))


def _busca(base, rota):
    with urllib.request.urlopen(base.rstrip("/") + rota, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _resposta(busca, base, rota):
    """("ok", json) ou ("http", status) — erro HTTP é comportamento a comparar, não falha."""
    try:
        return ("ok", busca(base, rota))
    except urllib.error.HTTPError as e:
        return ("http", e.code)


def compara(antigo, novo, rotas, busca=_busca):
    relatorio = {}
    for rota in rotas:
        base = _base(rota)
        if base in FORA:
            relatorio[rota] = {"igual": True, "fora": FORA[base]}
            continue
        try:
            ra, rb = _resposta(busca, antigo, rota), _resposta(busca, novo, rota)
            if ra[0] == rb[0] == "http":
                if ra[1] != rb[1]:
                    raise RuntimeError(f"HTTP {ra[1]} no antigo x HTTP {rb[1]} no novo")
                # mesmo erro nos dois (ex.: 422 de rota que exige parâmetro): mesmo comportamento
                relatorio[rota] = {"igual": True, "mesmo_erro": ra[1]}
                continue
            if "http" in (ra[0], rb[0]):
                raise RuntimeError(f"antigo {ra[1] if ra[0] == 'http' else 'ok'} x "
                                   f"novo {rb[1] if rb[0] == 'http' else 'ok'}")
            a, b = normaliza(ra[1]), normaliza(rb[1])
        except Exception as e:  # noqa: BLE001 — erro de rota é resultado, não para o resto
            relatorio[rota] = {"erro": f"{type(e).__name__}: {e}"}
            continue
        dif = diferencas(a, b, livres=ORDEM_LIVRE.get(base, ()))
        aceitas = [list(d) + [_casa(d[0], ACEITAS.get(base, ()))]
                   for d in dif if _casa(d[0], ACEITAS.get(base, ()))]
        dif = [d for d in dif if not _casa(d[0], ACEITAS.get(base, ()))]
        relatorio[rota] = {"igual": not dif, "so_ordem": bool(dif) and so_ordem(a, b),
                           "diferencas": [list(d) for d in dif], "aceitas": aceitas}
    return relatorio


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compara leituras do app antigo e do novo")
    ap.add_argument("--antigo", required=True)
    ap.add_argument("--novo", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--rota", action="append", help="rota GET (repita); padrão: todas")
    ap.add_argument("--amostras", action="store_true",
                    help="inclui as rotas com parâmetro (paridade.amostras; precisa de PG_DSN)")
    args = ap.parse_args(argv)
    if args.rota:
        rotas = args.rota
    else:
        sys.path.insert(0, "backend")
        from backend import main as app_main  # import tardio: só para listar as rotas
        rotas = rotas_get(app_main.app)
    if args.amostras:
        import os
        from paridade import amostras
        rotas = rotas + amostras.rotas(os.environ["PG_DSN"])
    rel = compara(args.antigo, args.novo, rotas)
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=2, default=str)
    iguais = sum(1 for v in rel.values() if v.get("igual"))
    print(f"[paridade] {iguais}/{len(rel)} rotas iguais — relatório em {args.saida}")
    sys.exit(0 if iguais == len(rel) else 1)


if __name__ == "__main__":
    main()

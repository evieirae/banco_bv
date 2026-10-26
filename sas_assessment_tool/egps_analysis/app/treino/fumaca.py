# -*- coding: utf-8 -*-
"""Teste de fumaça do app no ar — ensaio diário na training e subida de prod (ADR 0005).

Uso: python -m treino.fumaca http://<endereço> [--usuario fulano@indicium.ai]
Imprime uma linha por verificação e sai com 1 se alguma falhar.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def _pede(base, caminho, metodo="GET"):
    req = urllib.request.Request(base.rstrip("/") + caminho, method=metodo,
                                 data=None if metodo == "GET" else b"{}",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _json(st, corpo):
    try:
        return json.loads(corpo) if st == 200 else {}
    except ValueError:
        return {}


def verifica(base, usuario=None, pede=_pede):
    """Lista de (passou, descrição), na ordem em que um problema costuma aparecer."""
    res = []
    st, _ = pede(base, "/api/health")
    res.append((st == 200, f"/api/health -> {st}"))
    st, corpo = pede(base, "/api/me")
    me = _json(st, corpo)
    ok = bool(me.get("user")) and (usuario is None or me["user"] == usuario.lower())
    res.append((ok, f"/api/me -> {st} {me}"))
    st, corpo = pede(base, "/api/config")
    cfg = _json(st, corpo)
    ok = cfg.get("somente_leitura") is True and bool(cfg.get("sincronizado_em"))
    res.append((ok, f"/api/config -> {st} somente_leitura={cfg.get('somente_leitura')} "
                    f"sincronizado_em={cfg.get('sincronizado_em')}"))
    st, _ = pede(base, "/api/inputs", "PATCH")
    res.append((st == 403, f"PATCH /api/inputs -> {st} (esperado 403: só leitura)"))
    st, corpo = pede(base, "/")
    res.append((st == 200 and "<html" in corpo.lower(), f"/ -> {st} (front)"))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Teste de fumaça do app no ar")
    ap.add_argument("base")
    ap.add_argument("--usuario", help="e-mail esperado em /api/me")
    a = ap.parse_args(argv)
    falhou = False
    for passou, desc in verifica(a.base, a.usuario):
        print(f"[fumaca] {'OK   ' if passou else 'FALHA'} {desc}", flush=True)
        falhou = falhou or not passou
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()

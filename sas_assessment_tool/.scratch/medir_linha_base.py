# -*- coding: utf-8 -*-
"""Mede `total_egps` nos DOIS schemas, no mesmo processo e em LEITURA.

Guard: qualquer statement que não comece por select/with/show/describe levanta — nada
escreve em produção. Reimporta main.py com PUBLISH_SCHEMA trocado (as constantes T_* são
resolvidas no import).
"""
import importlib
import os
import sys

BACK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "egps_analysis", "app", "backend")
sys.path.insert(0, os.path.abspath(BACK))

SOMENTE_LEITURA = ("select", "with", "show", "describe", "explain")


class EscritaBloqueada(RuntimeError):
    pass


def medir(schema):
    os.environ["PUBLISH_SCHEMA"] = schema
    for mod in ("main", "vinculos", "linha_base", "familias"):
        sys.modules.pop(mod, None)
    m = importlib.import_module("main")

    bruto = m.run_sql
    vistos = {"n": 0}

    def guardado(stmt, want_rows=True):
        s = " ".join(str(stmt).split()).lstrip("( ").lower()
        if not s.startswith(SOMENTE_LEITURA):
            raise EscritaBloqueada(f"statement não-leitura barrado: {s[:120]}")
        vistos["n"] += 1
        return bruto(stmt, want_rows=want_rows)

    m.run_sql = guardado
    # os _ensure_* emitem DDL; aqui só se lê, então são neutralizados (e a neutralização
    # é ela mesma a prova de que nada de escrita precisou rodar).
    for nome in [n for n in dir(m) if n.startswith("_ensure_")]:
        if callable(getattr(m, nome)):
            setattr(m, nome, lambda *a, **k: None)

    land = m.landing()
    sc = m.scope_egps(scope="indi_deps", area=[])
    fun = m.funis()
    extras = m.egps_extras()
    rd = m._egp_readiness_uncached("indi_deps")
    front = m._frontier_egps("indi_deps", [])[0]
    print(f"\n=== {m.CATALOG}.{m.SCHEMA} ===  ({vistos['n']} statements, todos de leitura)")
    print(f"  recorte vivo (frontier indi_deps) : {len(front)}")
    print(f"  landing.total_egps               : {land['total_egps']}")
    print(f"    egps_escopo/deps/deps_ex       : {land['egps_escopo']} / {land['deps']} / {land['deps_ex']}")
    print(f"    landing.extras                 : {land['extras']}")
    print(f"  scope-egps.n_egps                : {sc['n_egps']}")
    print(f"    n_base/n_deps/n_ex/n_extra     : {sc['n_base']} / {sc['n_deps']} / {sc['n_ex']} / {sc['n_extra']}")
    print(f"  funis.migracao.total             : {fun['migracao']['total']}")
    print(f"  funis.migracao_deps.total        : {fun['migracao_deps']['total']}")
    print(f"  funis.migracao_deps.coorte/migr. : {fun['migracao_deps']['coorte']} / {fun['migracao_deps']['migrados']}")
    print(f"  funis.migracao_extras.total      : {fun['migracao_extras']['total']}")
    print(f"  egp-readiness.total              : {rd['total']}")
    print(f"    base/dep/ex/extra              : {rd['base_count']} / {rd['dep_count']} / {rd['ex_count']} / {rd['extra_count']}")
    print(f"    linhas listadas                : {len(rd['rows'])}")
    print(f"  /api/egps-extras n               : {extras['n']}")
    for r in extras["rows"][:8]:
        print(f"      - {r['projeto']}  [{r['motivo']}]")
    if extras["n"] > 8:
        print(f"      … e mais {extras['n'] - 8}")
    return land["total_egps"], sc["n_egps"], fun["migracao_deps"]["total"], extras["n"], rd["total"]


if __name__ == "__main__":
    res = {}
    for schema in ("monitoramento_sas", "monitoramento_sas_atualizados_dev"):
        res[schema] = medir(schema)
    print("\n=== veredito ===")
    for schema, (a, b, c, n, d) in res.items():
        ok = a == b == c == d == 193
        print(f"  {schema}: landing={a} scope-egps={b} funil+deps={c} readiness={d} "
              f"extras={n} -> {'OK' if ok else 'FALHOU'}")

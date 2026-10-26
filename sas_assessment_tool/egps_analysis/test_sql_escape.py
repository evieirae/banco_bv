#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão: escape de literal para Spark SQL.

O Spark NÃO trata `''` como aspa escapada dentro de um literal — ele lê `'O''Brien'`
como DOIS literais adjacentes e os concatena, devolvendo `OBrien`. O apóstrofo some
sem erro nenhum: a query roda, grava o texto errado e ninguém percebe.

Verificado no warehouse (bv, 2026-09-15):
    SELECT 'O''Brien'   ->  OBrien      (errado)
    SELECT 'O\\'Brien'   ->  O'Brien     (certo)

A contrabarra tem de ser escapada ANTES da aspa, senão a barra introduzida por `\\'`
seria duplicada pelo replace seguinte.

Este teste é OFFLINE: valida a forma do literal gerado, sem precisar de Databricks.
A validação contra o warehouse real foi feita à mão na correção; aqui garantimos que
ninguém volte para o `''`.

NÃO confundir com `sas_quote()` em egps_extractor.py: aquilo gera código SAS (%LET),
e em SAS `''` É o escape correto — por isso continua como está.

Uso: egps_analysis/venv/bin/python test_sql_escape.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'backend'))


def _desescapa(lit: str) -> str:
    """Interpreta o literal como o Spark interpreta: tira as aspas das pontas e
    resolve as sequências de escape com contrabarra."""
    assert lit.startswith("'") and lit.endswith("'"), lit
    corpo = lit[1:-1]
    out, i = [], 0
    while i < len(corpo):
        c = corpo[i]
        if c == '\\' and i + 1 < len(corpo):
            out.append(corpo[i + 1])
            i += 2
        elif c == "'":
            # aspa NÃO escapada dentro do corpo = fim de literal + início de outro,
            # que é exatamente a concatenação silenciosa que engole o apóstrofo
            raise AssertionError(f"aspa não escapada no literal: {lit!r}")
        else:
            out.append(c)
            i += 1
    return ''.join(out)


CASOS = [
    "O'Brien",
    "D'Ávila",
    "it's",
    "a''b",
    "'",
    "''",
    "a\\b",
    "N:\\",
    "\\\\bvnet\\global\\base.xlsx",
    "a\\'b",
    "Concluído",
    "Aprv. PR + Validação Governança",
    "obs com ; e -- comentário",
    "",
]


def roda():
    import publish_to_databricks as pub
    import publish_egps_atualizados as pea
    import egps_atualizados as ea
    import main as appmain
    import familias as fam

    helpers = [
        ("publish_to_databricks.sql_lit", pub.sql_lit),
        ("publish_egps_atualizados.sql_lit", pea.sql_lit),
        ("app/backend/egps_atualizados._sql_str", ea._sql_str),
        ("app/backend/main.sql_lit", appmain.sql_lit),
        # _lit já nascia certo, mas monta o CASE de familia_candidata_sql a partir de
        # nomes de tabela vindos do corpus — fica sob o guarda para não regredir.
        ("app/backend/familias._lit", fam._lit),
    ]

    falhas = 0
    for nome, fn in helpers:
        ruins = []
        for v in CASOS:
            lit = fn(v)
            if lit == "NULL":            # helpers que mapeiam ''/None p/ NULL
                continue
            try:
                got = _desescapa(lit)
            except AssertionError as e:
                ruins.append(f"{v!r}: {e}")
                continue
            if got != v:
                ruins.append(f"{v!r} -> {got!r} (literal {lit!r})")
        print(f"[{'PASS' if not ruins else 'FAIL'}] {nome}")
        for r in ruins:
            print(f"        {r}")
            falhas += 1

    # guarda explícito: ninguém volta para o '' em literal SQL
    import inspect
    for nome, fn in helpers:
        src = inspect.getsource(fn)
        ok = '''replace("'", "''")''' not in src
        print(f"[{'PASS' if ok else 'FAIL'}] {nome} não usa o escape '' (que o Spark concatena)")
        if not ok:
            falhas += 1

    print(f"\n{'TODOS PASSARAM' if falhas == 0 else f'{falhas} FALHA(S)'}")
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(roda())

# -*- coding: utf-8 -*-
"""O universo da Gestão retém ex-dependência pela LISTA CONGELADA, não pelo critério 189.

A Acompanhamento/Kanban lê `/api/gestao/rows`; a aba EGPs lê `/api/egp-readiness` e decide
por `contaNoTotalEgp`, que defere à foto (`na_linha_base`). O universo da Gestão ainda
retinha pelo critério "189" (`_ex_deps_contab`: só ex com etapa REAL), que a lista
ABSORVEU em 29/09/2026 — e em 07/10/2026 isso fazia a Acompanhamento exibir 31 EGPs
`Desatualizado` onde a aba EGPs exibia 33.

Os dois que faltavam eram ex-dependências com etapa FANTASMA (`Pré-conversão`) presentes na
foto. Um deles entrou na foto como `dependencia` e só virou ex depois — por isso a régua é
"está na lista", nunca "foi classificado ex na lista".

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m

FRONTIER = {"Cob__A", "Cob__B"}
BASE = {"Cob__A"}
# 3 ex-dependências vivas, todas com etapa fantasma (nenhuma passa no critério 189):
#   NA_FOTO_EX  entrou na foto já como ex          -> conta
#   NA_FOTO_DEP entrou como dependencia e virou ex -> conta (é o caso que motivou)
#   FORA_FOTO   não está na foto                   -> não conta
EX = {"Cob__NA_FOTO_EX", "Cob__NA_FOTO_DEP", "Cob__FORA_FOTO"}
# SAIU_DO_GRAFO: está na foto, mas não é frontier vivo NEM ex (o grafo deixou de alcançá-lo).
# A aba EGPs o lista (3º pedaço de `recorte`); a Gestão tem que listar também.
SAIU = "Cob__SAIU_DO_GRAFO"
LB = {"Cob__A": "base", "Cob__NA_FOTO_EX": "ex_dependencia", "Cob__NA_FOTO_DEP": "dependencia",
      SAIU: "dependencia"}


def _universo():
    """Os ids que `/api/gestao/rows?entity=egp` devolve."""
    def fake_run_sql(stmt, want_rows=True):
        s = " ".join(stmt.split()).lower()
        if "sas_lineage_nodes" in s:
            # o endpoint filtra por `projeto IN (<frontier montado>)`; devolver tudo e
            # deixar o filtro aparecer no statement é o que o teste quer medir
            return [{"projeto": p, "area": "Cobrança"}
                    for p in sorted(FRONTIER | EX | {SAIU}) if sql_contem(s, p)]
        return []

    def sql_contem(s, projeto):
        return projeto.lower() in s

    patches = [
        patch.object(m, "run_sql", side_effect=fake_run_sql),
        patch.object(m, "_frontier_egps", lambda *a, **k: (set(FRONTIER), set(BASE))),
        patch.object(m, "_ex_deps", lambda *a, **k: (set(EX), {}, {})),
        patch.object(m, "_ex_deps_contab", lambda *a, **k: set()),   # critério 189: nenhuma
        patch.object(m, "_linha_base", lambda: dict(LB)),
        patch.object(m, "_gestao_extras", lambda e: ({}, {}, {})),
        patch.object(m, "_vinculos_por_antecessor", lambda: {}),
        patch.object(m, "_ensure_gestao_tables", lambda *a, **k: True),
        patch.object(m, "_ensure_input_pipeline_cols", lambda *a, **k: True),
        patch.object(m, "_ensure_pipe_table", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        return {r["id"] for r in m._gestao_rows_uncached("egp")["rows"]}
    finally:
        for p in patches:
            p.stop()


def test_ex_da_foto_entra_mesmo_com_etapa_fantasma():
    """O critério 189 devolve vazio neste cenário; quem decide é a foto."""
    u = _universo()
    assert "Cob__NA_FOTO_EX" in u
    assert "Cob__NA_FOTO_DEP" in u, "classificada `dependencia` na foto, mas ESTÁ na foto"


def test_ex_fora_da_foto_nao_entra():
    """A retenção é da lista congelada; quem nunca esteve nela não ganha linha de gestão."""
    assert "Cob__FORA_FOTO" not in _universo()


def test_membro_da_foto_fora_do_grafo_entra():
    """Medido em prod (16/10/2026): a aba EGPs dizia 44 `Desatualizado` e a Acompanhamento
    43. O que faltava era `Fechamento_Contabil_RPDD_3040`, na foto como `dependencia`, fora
    do frontier vivo e fora de `ex`: a aba o lista (`linha_base - frontier - ex`), a Gestão
    só somava frontier + (ex ∩ foto)."""
    assert SAIU in _universo()


def test_frontier_vivo_continua_inteiro():
    u = _universo()
    assert FRONTIER <= u

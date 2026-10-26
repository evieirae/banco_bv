"""Testes unitários do override "ainda é dependência" (sas_egp_dep_mantida).

Não batem no warehouse: exercitam as duas partes PURAS da regra, que são as que decidem
se um EGP produtor fica no recorte ou some dele —

  1. `main._filter_vias_resolvidas_res`  (app)
  2. `publish_to_databricks.frontier_egps` (publish)

As duas são cópias da mesma regra em repositórios de código diferentes. O teste que
importa aqui é justamente o de PARIDADE: se só uma souber do override, o publish derruba
do escopo exatamente os EGPs que alguém marcou para manter — e ninguém vê, porque o app
continua mostrando certo até o próximo republish.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.main import _filter_vias_resolvidas_res  # noqa: E402
from publish_to_databricks import frontier_egps  # noqa: E402

# consumidor C lê a tabela T, produzida por P. T já está no lake.
EDGES = [{"projeto_alvo": "C", "depende_do": "P", "via_tabelas": "LIB.T"}]
RES = {"LIB.T"}


def test_via_resolvida_derruba_a_aresta_sem_override():
    assert _filter_vias_resolvidas_res(EDGES, RES) == []


def test_override_do_par_preserva_a_aresta():
    out = _filter_vias_resolvidas_res(EDGES, RES, {("C", "LIB.T")})
    assert len(out) == 1 and out[0]["depende_do"] == "P"
    assert out[0]["via_tabelas"] == "LIB.T"


def test_override_e_por_PAR_nao_por_tabela():
    """Outro consumidor da MESMA tabela continua com a via resolvida — é o ponto de
    guardar por par e não por artifact: marcar um consumidor não ressuscita a
    dependência para todo mundo."""
    edges = EDGES + [{"projeto_alvo": "C2", "depende_do": "P", "via_tabelas": "LIB.T"}]
    out = _filter_vias_resolvidas_res(edges, RES, {("C", "LIB.T")})
    assert [e["projeto_alvo"] for e in out] == ["C"]


def test_override_de_outro_par_nao_vale():
    assert _filter_vias_resolvidas_res(EDGES, RES, {("C2", "LIB.T")}) == []


def test_aresta_multi_via_mantem_so_a_via_marcada():
    """Aresta com 2 vias resolvidas e override em 1: sobrevive carregando só aquela."""
    edges = [{"projeto_alvo": "C", "depende_do": "P", "via_tabelas": "LIB.T | LIB.U"}]
    out = _filter_vias_resolvidas_res(edges, {"LIB.T", "LIB.U"}, {("C", "LIB.U")})
    assert len(out) == 1 and out[0]["via_tabelas"] == "LIB.U"


def test_sem_override_comportamento_identico_ao_anterior():
    """Default vazio não pode mudar nada de quem já existia (a chamada legada é posicional
    de 2 argumentos)."""
    edges = [{"projeto_alvo": "C", "depende_do": "P", "via_tabelas": "LIB.T | LIB.V"}]
    out = _filter_vias_resolvidas_res(edges, RES)
    assert len(out) == 1 and out[0]["via_tabelas"] == "LIB.V"


# ------------------------------------------------------------------ paridade com o publish

def test_publish_derruba_o_produtor_sem_override():
    front = frontier_egps(EDGES, base={"C"}, no_expand=set(), resolvidas=RES)
    assert front == {"C"}, "sem override, P não entra no frontier"


def test_publish_mantem_o_produtor_com_override():
    front = frontier_egps(EDGES, base={"C"}, no_expand=set(), resolvidas=RES,
                          mantidas={("C", "LIB.T")})
    assert front == {"C", "P"}, "com override, P volta ao frontier"


def test_paridade_app_x_publish():
    """A pergunta que as duas cópias têm de responder igual: 'P segue puxado por C?'"""
    for mant in (frozenset(), {("C", "LIB.T")}, {("C2", "LIB.T")}):
        app_mantem = any(e["depende_do"] == "P"
                         for e in _filter_vias_resolvidas_res(EDGES, RES, mant))
        pub_mantem = "P" in frontier_egps(EDGES, base={"C"}, no_expand=set(),
                                          resolvidas=RES, mantidas=mant)
        assert app_mantem == pub_mantem, f"divergiram com mantidas={mant}"

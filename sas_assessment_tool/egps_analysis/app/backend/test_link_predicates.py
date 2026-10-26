"""Testes unitários dos predicados SQL de status EFETIVO. Não bate no warehouse;
apenas verifica o STRING SQL gerado — a regra de sanitizado/modern/a_ingerir e o
overlay opcional de vínculo quebrado (lnk)."""
import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.main import _sanitizado, _modern, _aingerir, _ch_vinculo_ativo  # noqa: E402


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def test_sanitizado_default_lnk_matches_legacy_behavior():
    s = _sanitizado()
    assert "'Sanitizado'" in s
    assert "OR false" in _norm(s), f"lnk default deveria ser 'false': {s}"


def test_sanitizado_with_lnk_expression_gets_ored():
    s = _sanitizado("i.etapa", "e.modernizada_auto", "i.status", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert "'Sanitizado'" in n
    assert "OR coalesce(l.link_broken, false)" in n, f"lnk deve entrar como OR: {n}"


def test_modern_lnk_ored():
    s = _modern("i.etapa", "e.modernizada_auto", "i.status", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert "'Modernizado'" in n and "'Sanitizado'" in n
    assert "OR coalesce(l.link_broken, false)" in n


def test_aingerir_negates_modern_with_lnk():
    s = _aingerir("i.etapa", "e.modernizada_auto", "i.status", lnk="coalesce(l.link_broken, false)")
    n = _norm(s)
    assert n.startswith("(NOT ") or n.startswith("NOT ")
    assert "coalesce(l.link_broken, false)" in n


def test_ch_vinculo_ativo_universe_predicate():
    """Predicado ÚNICO do universo por vínculo (landing/funis/resumo/inputs): semi-join
    em sas_egp_inputs com LEFT JOIN no overlay de link, excluindo pares quebrados."""
    s = _norm(_ch_vinculo_ativo("e.escopo_indi = true"))
    assert s.startswith("(SELECT DISTINCT e.chave_canonica")
    assert "LEFT JOIN" in s and "l.link_broken" in s
    assert "e.escopo_indi = true AND NOT coalesce(l.link_broken, false)" in s
    # recorte por lista de projetos (deps/frontier) entra intacto no WHERE
    s2 = _norm(_ch_vinculo_ativo("e.projeto IN ('A', 'B')"))
    assert "e.projeto IN ('A', 'B') AND NOT coalesce(l.link_broken, false)" in s2


def test_lnk_true_forces_sanitized_short_circuit_semantics():
    """Ao passar lnk='true', a expressão OR-ed deveria colapsar em true no
    otimizador — verificamos que a string contém `OR true`."""
    s = _sanitizado("i.etapa", "e.modernizada_auto", "i.status", lnk="true")
    assert "OR true" in _norm(s)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")

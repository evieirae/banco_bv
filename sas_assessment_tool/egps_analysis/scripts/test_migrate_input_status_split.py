"""Testes unitários do mapeamento status_humano -> (etapa, status) do backfill único
(migrate_input_status_split.py). Não bate no warehouse; só garante que o CASE SQL contém
o mapeamento confirmado com o usuário — insurance contra o mapeamento driftar em silêncio."""
import re
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from migrate_input_status_split import ETAPA_CASE, STATUS_CASE  # noqa: E402

# (status_humano, etapa esperada, status esperado) — tabela confirmada com o usuário.
CASOS = [
    ("A receber", "A Receber", "A Iniciar"),
    ("A ingerir", "A Receber", "A Iniciar"),
    ("Não recebido", "A Receber", "A Iniciar"),
    ("Recebido", "Recebido", "Concluído"),
    ("Em análise", "Recebido", "Concluído"),
    ("Priorizado", "Recebido", "Concluído"),
    ("Em ingestão", "Ingestão UAT", "Em Andamento"),
    ("Modernizado", "Modernizado", "Concluído"),
    ("Disponível", "Modernizado", "Concluído"),
    ("Sanitizado", "Modernizado", "Sanitizado"),
    ("Sanitizada", "Modernizado", "Sanitizado"),
    ("Descartada", "Modernizado", "Sanitizado"),
    ("Descartado", "Modernizado", "Sanitizado"),
]


def _when_then(case_sql: str, valor: str) -> str | None:
    m = re.search(rf"WHEN '{re.escape(valor)}' THEN '([^']*)'", case_sql)
    return m.group(1) if m else None


def test_etapa_case_matches_confirmed_mapping():
    for status_humano, etapa_esperada, _ in CASOS:
        got = _when_then(ETAPA_CASE, status_humano)
        assert got == etapa_esperada, f"{status_humano!r}: etapa esperada {etapa_esperada!r}, CASE deu {got!r}"


def test_status_case_matches_confirmed_mapping():
    for status_humano, _, status_esperado in CASOS:
        got = _when_then(STATUS_CASE, status_humano)
        assert got == status_esperado, f"{status_humano!r}: status esperado {status_esperado!r}, CASE deu {got!r}"


def test_no_valor_legado_esquecido():
    """Todo valor coberto pelo CASE legado de _eff_status() (histórico) também precisa
    aparecer nos dois CASEs do backfill — senão a linha fica sem etapa/status."""
    legados = {"Disponível", "Sanitizada", "Descartada", "Descartado", "Em análise",
               "A ingerir", "Não recebido", "Priorizado"}
    cobertos = {c[0] for c in CASOS}
    faltando = legados - cobertos
    assert not faltando, f"valores legados sem caso de teste: {faltando}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")

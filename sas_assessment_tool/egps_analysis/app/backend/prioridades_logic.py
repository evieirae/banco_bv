"""Funções puras da aba Prioridades — sem dependências de FastAPI/Databricks
(testáveis com `python3 test_prioridades_logic.py`)."""

STATUS_PRIO = ["A fazer", "Em andamento", "Concluído", "Descartado"]


def valid_status(s):
    return s in STATUS_PRIO


def next_ordem(max_ordem):
    return (max_ordem or 0) + 1


def neighbor_swap(rows, item_id, direction):
    """rows: lista de {id, ordem}. Devolve (atual, vizinho) cujos `ordem` devem
    ser trocados, ou None se item_id não existe ou já está na ponta na direção pedida."""
    ordered = sorted(rows, key=lambda r: r["ordem"])
    idx = next((i for i, r in enumerate(ordered) if r["id"] == item_id), None)
    if idx is None:
        return None
    j = idx - 1 if direction == "up" else idx + 1
    if j < 0 or j >= len(ordered):
        return None
    return ordered[idx], ordered[j]

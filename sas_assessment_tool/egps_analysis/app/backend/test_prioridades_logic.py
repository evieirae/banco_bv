from prioridades_logic import valid_status, next_ordem, neighbor_swap, STATUS_PRIO


def check(name, cond):
    assert cond, name
    print("ok -", name)


check("status válidos", all(valid_status(s) for s in STATUS_PRIO))
check("status inválido", (not valid_status("xpto")) and (not valid_status("")))
check("next_ordem de vazio", next_ordem(0) == 1 and next_ordem(None) == 1)
check("next_ordem incrementa", next_ordem(5) == 6)

rows = [{"id": "a", "ordem": 1}, {"id": "b", "ordem": 2}, {"id": "c", "ordem": 3}]
up = neighbor_swap(rows, "b", "up")
check("subir troca com anterior", up is not None and {up[0]["id"], up[1]["id"]} == {"a", "b"})
down = neighbor_swap(rows, "b", "down")
check("descer troca com próximo", down is not None and {down[0]["id"], down[1]["id"]} == {"b", "c"})
check("primeiro não sobe", neighbor_swap(rows, "a", "up") is None)
check("último não desce", neighbor_swap(rows, "c", "down") is None)
check("id inexistente", neighbor_swap(rows, "z", "up") is None)
unordered = [{"id": "c", "ordem": 3}, {"id": "a", "ordem": 1}, {"id": "b", "ordem": 2}]
res = neighbor_swap(unordered, "a", "down")
check("ordena por ordem numérica", res is not None and res[1]["id"] == "b")

print("\nOK")

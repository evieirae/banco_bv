"""Lógica pura (sem DB) do empacotamento por capacidade da aba Priorização.
Testável offline; consumida por main.py:/api/priorizacao. Espelha o padrão de
prioridades_logic.py (funções puras + test_*.py)."""


def plan_months(order, egp_inputs, pin, cap):
    """Empacota EGPs em meses de ≤ cap inputs DISTINTOS a ingerir, com dedupe global
    (input conta no 1º mês em que aparece) e pins absolutos (teto vira guia).

    order      : list[str]      EGPs já ordenados por prioridade (viab, -fanout, esforço, nome).
    egp_inputs : dict[str, set] inputs pendentes distintos por EGP.
    pin        : dict[str, int] mês fixado (>=1) por EGP fixado (só os fixados).
    cap        : int            capacidade-guia por mês.

    Retorna list de meses contíguos (vazios removidos), cada um:
      {"inputs": set, "egps": [{"projeto", "n_inputs_novos", "excede", "pinned"}]}.
    Dentro do mês: pins primeiro (na ordem de `order`), depois os automáticos.
    """
    cap = max(1, int(cap))
    # pin válido = inteiro >= 1 (mês 0/None/negativo => tratado como não-fixado)
    pinned = [pj for pj in order if (pin.get(pj) or 0) >= 1]
    free = [pj for pj in order if not ((pin.get(pj) or 0) >= 1)]
    ingested = set()
    months = {}                       # m(int>=1) -> {"inputs": set, "egps": []}
    # o laço percorre m = 1..max(free_needed, max_pin), então TODO pin em [1..max_pin]
    # é visitado no topo do seu mês (não há pin silenciosamente descartado).
    max_pin = max([v for v in pin.values() if isinstance(v, int) and v >= 1], default=0)

    def _add(cm, pj, marginal, excede, pinned_flag):
        cm["inputs"] |= marginal
        cm["egps"].append({"projeto": pj, "n_inputs_novos": len(marginal),
                           "excede": excede, "pinned": pinned_flag})

    m = 1
    free_i = 0
    while free_i < len(free) or m <= max_pin:
        cm = months.setdefault(m, {"inputs": set(), "egps": []})
        # (a) pins deste mês, na ordem de prioridade
        for pj in pinned:
            if pin[pj] == m:
                marginal = egp_inputs.get(pj, set()) - ingested
                _add(cm, pj, marginal, len(marginal) > cap, True)
                ingested |= marginal
        # (b) automáticos até o teto (guia)
        while free_i < len(free):
            pj = free[free_i]
            marginal = egp_inputs.get(pj, set()) - ingested
            novos = len(marginal)
            if novos > cap:                      # EGP sozinho excede -> mês próprio
                if cm["egps"]:
                    break                        # não crava num mês já ocupado -> próximo
                _add(cm, pj, marginal, True, False)
                ingested |= marginal
                free_i += 1
                break                            # fecha o mês (over-cap)
            if cm["egps"] and len(cm["inputs"]) + novos > cap:
                break                            # não cabe -> próximo mês
            _add(cm, pj, marginal, False, False)
            ingested |= marginal
            free_i += 1
        m += 1

    # remove meses vazios; ordem crescente (renumeração fica com o caller: mes = i+1)
    return [months[k] for k in sorted(months) if months[k]["egps"]]


def resumo_counts(frontier, blocked):
    """total = nº de EGPs do recorte; bloqueados = interseção; habilitados = complemento."""
    frontier = set(frontier)
    total = len(frontier)
    bloq = len(frontier & set(blocked))
    return {"total": total, "bloqueados": bloq, "habilitados": total - bloq}

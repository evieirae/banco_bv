# -*- coding: utf-8 -*-
"""Guarda do ensaio diário: recusa aplicar plan que destrua ou substitua recurso.

O ensaio só cria (subida do zero) ou não muda nada (2ª rodada no mesmo dia, mesmo estado).
Destruir ali é sinal de estado ou sufixo errado — melhor parar do que aplicar às cegas.
Com --derruba (treino/desce_treino.sh) vale o contrário: o plan só pode destruir, e destruir
alguma coisa — plan vazio é sufixo errado, e o ensaio de pé ficaria esquecido.
Uso: terraform show -json <plan> | python -m treino.confere_plano [--derruba]
"""
import json
import sys


def destrutivos(plano):
    """Endereços dos recursos que o plan destruiria (inclui substituição: delete + create)."""
    return [r["address"] for r in plano.get("resource_changes", [])
            if "delete" in r["change"]["actions"]]


def fora_da_derrubada(plano):
    """Endereços cuja mudança não é só destruir (criar, mudar, substituir ou manter)."""
    return [r["address"] for r in plano.get("resource_changes", [])
            if r["change"]["actions"] != ["delete"]]


def main():
    plano = json.load(sys.stdin)
    if "--derruba" in sys.argv[1:]:
        ruins = fora_da_derrubada(plano)
        if ruins:
            sys.exit(f"ERRO: a derrubada faria mais que destruir em {ruins}. Nada foi aplicado.")
        n = len(destrutivos(plano))
        if not n:
            sys.exit("ERRO: o plan não derruba nada (sufixo ou estado errado?). Nada foi aplicado.")
        print(f"[treino] plan só derruba: {n} recursos", flush=True)
        return
    ruins = destrutivos(plano)
    if ruins:
        sys.exit(f"ERRO: o plan destruiria ou substituiria {ruins}. Nada foi aplicado.")
    print("[treino] plan só cria ou não muda nada", flush=True)


if __name__ == "__main__":
    main()

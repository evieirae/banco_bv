"""Gera o CSV de ação por EGP+input (Sanitizado / Desvincular / Revisar manualmente),
cruzando os dois estudos mais recentes:

- BV_Migracao_SAS_Inputs_Sanitizaveis_2026-08-13.csv (auto-produtores, tiers 1/1c)
- BV_Migracao_SAS_Escopo_Inputs_Nao_Usados_2026-08-18.csv (inputs nunca lidos pela lógica)

Regra central (pedido do usuário): "Sanitizado" é status global do input na aba Inputs —
se mais de um EGP lê o mesmo input e só um deles se autoabastece, marcar Sanitizado
afetaria a fila dos outros. Nesses casos a ação recomendada é "Desvincular" o par
EGP+input específico (mecanismo já existente, não altera o status para os demais).

Saída: BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv
"""
import csv
import os
import sys

# Relativo ao próprio arquivo (era um caminho absoluto de uma máquina só, o que
# quebrava o script em qualquer outro clone).
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{BASE}/BV_Migracao_SAS_Acao_Sanitizar_Desvincular_2026-08-21.csv"

rows_out = []


def add(egp, input_, chave_canonica, acao, comentario, estudo, classe, etapa, status,
        qtd_leitores, outros_leitores):
    rows_out.append({
        "egp": egp,
        "input": input_,
        "chave_canonica": chave_canonica,
        "acao": acao,
        "comentario": comentario,
        "estudo_origem": estudo,
        "classe": classe,
        "etapa_atual_app": etapa,
        "status_atual_app": status,
        "qtd_egps_leitores": qtd_leitores,
        "outros_egps_leitores_nao_afetados": outros_leitores,
    })


# ---------------------------------------------------------------------------
# Estudo 1: auto-produtores (safra, 2026-08-13) — tiers 1 e 1c, só pendentes
# ---------------------------------------------------------------------------
with open(f"{BASE}/BV_Migracao_SAS_Inputs_Sanitizaveis_2026-08-13.csv", encoding="utf-8-sig") as f:
    sanit_rows = list(csv.DictReader(f, delimiter=";"))

tier1_tier1c = [r for r in sanit_rows if r["Tier"].startswith("1")]
actionable = [r for r in tier1_tier1c if r["Status atual no app"] == "A Iniciar"]

for r in actionable:
    artefato = r["Artefato"]
    chave = r["Chave canônica"]
    qtd = int(r["Qtd EGPs leitores"])
    leitores = [x.strip() for x in r["EGPs leitores"].split("|")]
    produtor_raw = r["Produtor(es) identificado(s)"].strip()
    produtores = [] if produtor_raw in ("—", "") else [p.strip() for p in produtor_raw.split("|")]
    is_calendario = r["Tier"].startswith("1c")
    etapa, status = r["Etapa atual no app"], r["Status atual no app"]

    if is_calendario:
        # Recurso compartilhado (calendário): Sanitizado é seguro pra todo leitor,
        # o dado passa a vir de uma fonte comum (date spine), não de auto-produção
        # de um EGP específico — não há "outro EGP prejudicado".
        for egp in leitores:
            add(
                egp, artefato, chave, "Sanitizado",
                "Tabela de calendário (dias úteis/feriados/fim de semana); será recriada como "
                "date spine no dbt, igual para qualquer EGP que a leia — não depende de "
                "auto-produção deste EGP e não prejudica os demais leitores.",
                "Auto-produtores (safra) 2026-08-13", "calendario", etapa, status, qtd,
                " | ".join(x for x in leitores if x != egp),
            )
        continue

    if qtd == 1:
        add(
            leitores[0], artefato, chave, "Sanitizado",
            "O próprio EGP cria e lê esta tabela no mesmo run (auto-produção); é o único "
            "leitor do input, então marcar Sanitizado não afeta nenhum outro EGP.",
            "Auto-produtores (safra) 2026-08-13", "auto_mesmo_run", etapa, status, qtd, "",
        )
        continue

    if produtores:
        outros = [x for x in leitores if x not in produtores]
        for egp in produtores:
            add(
                egp, artefato, chave, "Desvincular",
                f"Este EGP cria e lê a tabela no mesmo run (auto-produção), mas outro(s) "
                f"{len(outros)} EGP(s) também leem o mesmo dado sem produzi-lo. Marcar o "
                f"input inteiro como Sanitizado afetaria a fila desses outros EGPs — "
                f"desvincular só este par ({egp} + {artefato}) resolve a auto-produção sem "
                f"tocar no status de quem ainda depende de ingestão real.",
                "Auto-produtores (safra) 2026-08-13", "auto_mesmo_run", etapa, status, qtd,
                " | ".join(outros),
            )
        continue

    # multi-leitor sem produtor identificado automaticamente -> não decidir por código
    add(
        " | ".join(leitores), artefato, chave, "Revisar manualmente",
        f"{qtd} EGPs leem esta tabela e o produtor não foi identificado automaticamente "
        f"(alias/path ambíguo). Confirmar manualmente qual EGP autoproduz antes de "
        f"sanitizar (afeta todos) ou desvincular (afeta só um par).",
        "Auto-produtores (safra) 2026-08-13", "auto_mesmo_run", etapa, status, qtd, "",
    )

# ---------------------------------------------------------------------------
# Estudo 2: inputs nunca lidos pela lógica (2026-08-18) — já por par EGP+input
# ---------------------------------------------------------------------------
with open(f"{BASE}/BV_Migracao_SAS_Escopo_Inputs_Nao_Usados_2026-08-18.csv", encoding="utf-8-sig") as f:
    nao_usados = list(csv.DictReader(f, delimiter=";"))

for r in nao_usados:
    if r["status"] == "Sanitizado":  # já resolvido
        continue
    add(
        r["egp"], r["input"], r["chave"], "Desvincular",
        f"Input declarado mas nunca lido pela lógica do programa ({r['motivo']}); é vínculo "
        f"falso, não dado sanitizado — desvincular apenas este par não altera nada para os "
        f"outros {r['n_consumidores']} EGP(s) que também leem a mesma tabela por vínculo próprio.",
        "Inputs não usados pela lógica 2026-08-18", "descompacta_nao_lido",
        r["etapa"], r["status"], r["n_consumidores"], "",
    )

# ---------------------------------------------------------------------------
# GUARD DE SOBRESCRITA: este CSV não é só a saída deste script — é o insumo de uma
# cadeia que termina em PRODUÇÃO:
#   build_acao_...(aqui)  ->  verifica_e_corrige_sanitizado_live.py --write  (corrige
#   à mão as linhas cuja marcação global "Sanitizado" foi estreitada para
#   "Desvincular" por par)  ->  aplica_acao_sanitizar_desvincular.py --apply --prod-confirm
# Regerar por cima descarta a passada de verificação sem avisar, e o apply seguinte
# empurraria para prod as ações largas que a revisão tinha deliberadamente reduzido.
if os.path.exists(OUT) and "--overwrite" not in sys.argv:
    print(f"ABORTADO: '{OUT}' já existe.\n"
          f"  Ele pode conter correções manuais de verifica_e_corrige_sanitizado_live.py\n"
          f"  que seriam perdidas — e o arquivo alimenta o apply em PRODUÇÃO.\n"
          f"  Revise/arquive o atual e rode de novo com --overwrite para regerar.",
          file=sys.stderr)
    sys.exit(2)

with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    fieldnames = [
        "egp", "input", "chave_canonica", "acao", "comentario", "estudo_origem", "classe",
        "etapa_atual_app", "status_atual_app", "qtd_egps_leitores",
        "outros_egps_leitores_nao_afetados",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
    w.writeheader()
    w.writerows(rows_out)

from collections import Counter
print("total linhas:", len(rows_out))
print("por ação:", Counter(r["acao"] for r in rows_out))
print("por estudo:", Counter(r["estudo_origem"] for r in rows_out))
print("escrito em:", OUT)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relatório READ-ONLY das ex-dependências RESOLVIDAS POR INGESTÃO — e o UPDATE proposto.

O caso: um EGP entrou no recorte só porque produzia uma tabela que alguém do escopo lia.
Em vez de migrar esse produtor, a tabela foi INGERIDA (é do que o consumidor precisava
para migrar). A partir daí a aresta morre, o produtor sai do frontier e vira
"ex-dependência". Houve ENTREGA — mas o esforço já gasto nele (pré-conversão) fica órfão:
etapa fantasma não conta nos totais de EGP.

A regra de detecção mora em UM lugar só: `app/backend/main.py::_ex_deps`, que devolve
`motivo == 'resolvida por ingestão'` quando TODAS as vias daquele produtor entraram no
lake e NENHUMA foi Sanitizada (descarte não é entrega). Este script importa essa função
em vez de reimplementá-la — a esteira já pagou o preço de manter duas cópias de uma regra
sutil (ver o cabeçalho de `app/backend/input_state.py`).

Detectar NÃO decide o desfecho — "a tabela foi ingerida" não diz o que houve com o
produtor. São dois, opostos:

  * **foi dispensado** — a ingestão cobre o que os consumidores precisavam; migrar o
    produtor perdeu o sentido. Saída: status `Despriorizado e Contabilizado` (o UPDATE que
    este script imprime).
  * **ainda é necessário** — a ingestão não cobre o que o consumidor lê (carga única sem
    refresh, recorte parcial...). Saída: botão **"ainda é dependência"** na aba EGPs, que
    reabre a aresta e devolve o EGP ao frontier. Nada de UPDATE aqui.

Saída deste script: os candidatos, separados por terem ou não esforço gasto, e o UPDATE
pronto para revisão. **Este script NUNCA escreve.**

Por que decisão humana e não regra automática: "a tabela entrou no lake" é fato derivado e
pode mudar. Já "este EGP não vai ser migrado" é DECISÃO — e mora em `sas_egp_pipeline`, que
o publish nunca recria (CREATE TABLE IF NOT EXISTS), com histórico em `sas_pipeline_audit`.
Por isso sobrevive ao republish, ao contrário dos patches de dado.

Uso (só SELECT):
  cd egps_analysis/app && DATABRICKS_CONFIG_PROFILE=bv \\
      ../venv/bin/python ../scripts/ex_deps_resolvidas_por_ingestao.py
  # dev: PUBLISH_SCHEMA=monitoramento_sas_dev ... (mesma env do app)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "app", "backend"))
os.environ.setdefault("DATABRICKS_WAREHOUSE_ID", "5922c26f81f1bbdd")

import main  # noqa: E402

STATUS_ALVO = "Despriorizado e Contabilizado"


def main_():
    pipe = main.run_sql(
        f"SELECT projeto, etapa_migracao, status_migracao FROM {main.T_PIPE}")
    et = {r["projeto"]: r["etapa_migracao"] for r in pipe}
    st = {r["projeto"]: r["status_migracao"] for r in pipe}

    frontier, base = main._frontier_egps("indi_deps", [])
    ex, motivo, _ = main._ex_deps(frontier, base)
    ing = sorted(p for p, m in motivo.items() if m == "resolvida por ingestão")

    print(f"esquema: {main.FQ}")
    print(f"ex-dependências: {len(ex)}  |  resolvidas por ingestão: {len(ing)}")
    print()

    # 3 baldes: já tratado / a tratar (tem esforço) / nada a fazer (nunca entrou na esteira)
    ja, tratar, sem_esforco = [], [], []
    for p in ing:
        if st.get(p) == STATUS_ALVO:
            ja.append(p)
        elif et.get(p):
            tratar.append(p)
        else:
            sem_esforco.append(p)

    print(f"[1] já marcados como '{STATUS_ALVO}': {len(ja)}")
    for p in ja:
        print(f"      {p}")
    print()
    print(f"[2] A DECIDIR — têm esforço gasto (etapa preenchida): {len(tratar)}")
    for p in tratar:
        print(f"      {p}")
        print(f"         etapa={et.get(p)!r}  status atual={st.get(p)!r}")
    if tratar:
        print()
        print("      A pergunta para cada um: a ingestão cobre o que o consumidor lia?")
        print("        NÃO cobre -> botão 'ainda é dependência' na aba EGPs (reabre a")
        print("                     aresta; o EGP volta a ser dependência viva).")
        print(f"        COBRE     -> status '{STATUS_ALVO}' (o UPDATE abaixo).")
    print()
    print(f"[3] sem esforço a contabilizar (nunca entraram na esteira): "
          f"{len(sem_esforco)}")
    for p in sem_esforco:
        print(f"      {p}")
    print("      -> nada a fazer: sem etapa, não há trabalho para reconhecer.")
    print()

    if not tratar:
        print("Nada a aplicar.")
        return 0

    print("=" * 78)
    print("UPDATE do desfecho 'COBRE' — só para os que foram DISPENSADOS pela ingestão.")
    print("Para os que ainda são necessários, use o botão, NÃO este UPDATE.")
    print("(revisar antes de rodar; este script não escreve)")
    print("=" * 78)
    lista = ", ".join("'" + p.replace("'", "''") + "'" for p in tratar)
    print(f"""
UPDATE {main.T_PIPE}
   SET status_migracao = '{STATUS_ALVO}',
       updated_by      = '<seu.email>',
       updated_at      = current_timestamp()
 WHERE projeto IN ({lista})
   AND status_migracao <> '{STATUS_ALVO}';
""")
    print("Depois de aplicar, re-rode este script: o balde [2] tem que ficar vazio")
    print("e os EGPs migram para o balde [1].")
    return 0


if __name__ == "__main__":
    sys.exit(main_())

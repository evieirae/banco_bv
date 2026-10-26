# -*- coding: utf-8 -*-
"""Roda a cópia do §3.3.11 RETROATIVAMENTE nos vínculos que a pularam.

Reusa `_copia_trabalho_para_sucessor` — a mesma função do PATCH — em vez de escrever SQL
à mão: foi escrever à mão que pulou a regra da primeira vez (ticket 17). Ela já decide o
que copiar (`campos_copiados_no_vinculo`), respeita a guarda de cadeia, faz MERGE e audita.

Dirigido pelos DADOS, não por lista: alvo é todo antecessor cuja etapa EXIBIDA está vazia
e cuja etapa GRAVADA não está — que é exatamente "o espelho apagou trabalho real".
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "app", "backend"))
os.environ.setdefault("FAMILIAS_SAFRA", "1")
os.environ.setdefault("PUBLISH_SCHEMA", "monitoramento_sas")
import main as m
for i, a in enumerate(sys.argv):
    if a == "--schema" and i + 1 < len(sys.argv):
        os.environ["PUBLISH_SCHEMA"] = sys.argv[i + 1]
APLICA = "--aplica" in sys.argv
import main as m

linhas = {r["projeto"]: r for r in m.run_sql(
    f"SELECT projeto, etapa_migracao AS etapa, mes_prioridade, jira_id, responsavel "
    f"FROM {m.T_PIPE}")}
vin, exib = m._vinculos_por_antecessor(), m._pipe_exibido()
alvos = [(a, v["sucessor"]) for a, v in sorted(vin.items())
         if exib.get(a, (None, None))[0] in (None, "")
         and (linhas.get(a) or {}).get("etapa")]
print(f"vínculos: {len(vin)} | antecessores com etapa real apagada pelo espelho: {len(alvos)}\n")
feitos, recusados = 0, []
for ante, suc in alvos:
    o = linhas[ante]
    origem = {"etapa": o.get("etapa"), "mes_prioridade": o.get("mes_prioridade"),
              "jira_id": o.get("jira_id"), "responsavel": o.get("responsavel")}
    if not APLICA:
        print(f"  [dry] {ante.replace('Cobranças__','')[:50]:50} -> "
              f"{suc.replace('Cobranças__','')[:44]:44} etapa={o.get('etapa')!r}")
        continue
    destino = m.vinculos.fim_do_espelho(suc, vin)   # o FIM da cadeia, não o salto
    campos = m._copia_trabalho_para_sucessor(destino, origem)
    if campos:
        feitos += 1
        print(f"  OK   {ante.replace('Cobranças__','')[:50]:50} -> "
              f"{destino.replace('Cobranças__','')[:40]:40} copiou {sorted(campos)}")
    else:
        recusados.append((ante, suc))
        print(f"  --   {ante.replace('Cobranças__','')[:50]:50} -> "
              f"{suc.replace('Cobranças__','')[:40]:40} NADA copiado (guarda de cadeia?)")
if APLICA:
    m._bump_gen()
    exib2 = m._pipe_exibido()
    resta = [a for a, _ in alvos if exib2.get(a, (None, None))[0] in (None, "")]
    print(f"\n  copiados: {feitos} | ainda sem etapa exibida: {len(resta)} -> "
          f"{[x.replace('Cobranças__','')[:40] for x in resta]}")

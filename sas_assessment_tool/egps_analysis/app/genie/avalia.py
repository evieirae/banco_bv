"""Mede a taxa de acerto do Genie space contra benchmarks.sql (só leitura em prod).

Para cada benchmark: roda o gabarito, pergunta ao Genie numa conversa NOVA (sem contexto
das anteriores), roda nada além do que o Genie já rodou, e compara:
  * escalar  -> passa se algum valor da resposta do Genie é igual ao gabarito
                (ou se ele listou exatamente N linhas quando o gabarito é N);
  * conjunto -> passa se alguma coluna da resposta tem EXATAMENTE o conjunto do gabarito.

Uso:  python avalia.py [rotulo]   (grava avaliacao_<rotulo>.json ao lado)
      GENIE_SPACE_ID=<id> GENIE_SCHEMA=monitoramento_sas_dev python avalia.py previa  (outro space/schema)
Precisa do profile `bv` do Databricks CLI.
"""
import json
import os
import pathlib
import re
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format

AQUI = pathlib.Path(__file__).resolve().parent
SPACE_ID = os.environ.get("GENIE_SPACE_ID", "01f1c0f81649139385ba0856ebefbfad")
SCHEMA = os.environ.get("GENIE_SCHEMA", "monitoramento_sas")
WAREHOUSE = "5922c26f81f1bbdd"

w = WorkspaceClient(profile="bv")


def benchmarks():
    # os gabaritos são escritos com o schema de PROD; troca para o alvo
    txt = (AQUI / "benchmarks.sql").read_text(encoding="utf-8").replace(
        "bv_dev_db.monitoramento_sas.", f"bv_dev_db.{SCHEMA}.")
    partes = re.split(r"^-- (B\d+) \| (escalar|conjunto) \| (.+)$", txt, flags=re.M)
    out = []
    for i in range(1, len(partes), 4):
        sql = partes[i + 3].strip().rstrip(";").strip()
        out.append({"id": partes[i], "tipo": partes[i + 1], "pergunta": partes[i + 2].strip(), "sql": sql})
    return out


def roda(sql):
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=WAREHOUSE, wait_timeout="50s",
                                                disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"gabarito falhou: {r.status.error.message if r.status.error else r.status.state}")
    # guarda contra truncamento silencioso
    assert (r.manifest.total_chunk_count or 1) == 1 and not r.manifest.truncated, "gabarito truncado"
    return r.result.data_array or []


def norm(v):
    return "" if v is None else str(v).strip().lower()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pergunta_genie(pergunta):
    m = w.genie.start_conversation_and_wait(SPACE_ID, pergunta)
    sql_g, linhas, texto = None, [], ""
    for a in m.attachments or []:
        if a.text and a.text.content:
            texto += a.text.content
        if a.query:
            sql_g = a.query.query
            r = w.genie.get_message_attachment_query_result(SPACE_ID, m.conversation_id, m.id, a.attachment_id)
            linhas = r.statement_response.result.data_array or []
    return str(m.status), sql_g, linhas, texto


def compara(tipo, gabarito, linhas):
    if tipo == "escalar":
        esperado = num(gabarito[0][0]) if gabarito else None
        if esperado is None:
            return False, "gabarito sem valor"
        if any(num(c) == esperado for row in linhas for c in row):
            return True, f"valor {esperado:g} na resposta"
        if len(linhas) == esperado:
            return True, f"listou {len(linhas)} linhas"
        return False, f"esperado {esperado:g}; resposta {[r[:4] for r in linhas[:3]]}"
    esperado = {norm(r[0]) for r in gabarito}
    if not esperado and not linhas:
        return True, "conjunto vazio nos dois"
    melhor = (0.0, -1)
    for j in range(len(linhas[0]) if linhas else 0):
        col = {norm(r[j]) for r in linhas}
        if col == esperado:
            return True, f"coluna {j} bate ({len(esperado)} itens)"
        uniao = col | esperado
        jac = len(col & esperado) / len(uniao) if uniao else 1.0
        melhor = max(melhor, (jac, j))
    return False, f"esperado {len(esperado)} itens; melhor coluna jaccard={melhor[0]:.2f} ({len(linhas)} linhas)"


def reavalia(rotulo):
    """Recorrige uma rodada antiga contra o benchmarks.sql ATUAL, rodando de novo o SQL que o
    Genie gerou naquela rodada (sem perguntar de novo). Serve para comparar antes/depois
    quando um gabarito foi corrigido no meio do caminho."""
    antiga = json.loads((AQUI / f"avaliacao_{rotulo}.json").read_text(encoding="utf-8"))
    gabs = {b["id"]: b for b in benchmarks()}
    n_ok = 0
    for r in antiga["resultados"]:
        b = gabs[r["id"]]
        linhas = roda(r["sql_genie"]) if r["sql_genie"] else []
        ok, motivo = compara(b["tipo"], roda(b["sql"]), linhas)
        n_ok += ok
        print(f"{r['id']} {'PASS' if ok else 'FAIL'} — {motivo}", flush=True)
    print(f"\n{rotulo} (recorrigida): {n_ok}/{len(antiga['resultados'])} corretas")


def main():
    if sys.argv[1:2] == ["--reavalia"]:
        for rot in sys.argv[2:]:
            reavalia(rot)
        return
    rotulo = sys.argv[1] if len(sys.argv) > 1 else "atual"
    resultados = []
    for b in benchmarks():
        gab = roda(b["sql"])
        try:
            status, sql_g, linhas, texto = pergunta_genie(b["pergunta"])
            ok, motivo = compara(b["tipo"], gab, linhas)
        except Exception as e:  # erro do Genie conta como falha, mas não derruba a rodada
            status, sql_g, texto, ok, motivo = "ERRO", None, "", False, repr(e)[:300]
        resultados.append({"id": b["id"], "pergunta": b["pergunta"], "ok": ok, "motivo": motivo,
                           "status": status, "sql_genie": sql_g, "texto_genie": texto[:500]})
        print(f"{b['id']} {'PASS' if ok else 'FAIL'} — {motivo}", flush=True)
        time.sleep(3)  # a API de conversa tem limite de taxa por workspace
    n_ok = sum(r["ok"] for r in resultados)
    print(f"\n{rotulo}: {n_ok}/{len(resultados)} corretas")
    (AQUI / f"avaliacao_{rotulo}.json").write_text(
        json.dumps({"rotulo": rotulo, "acertos": n_ok, "total": len(resultados), "resultados": resultados},
                   ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

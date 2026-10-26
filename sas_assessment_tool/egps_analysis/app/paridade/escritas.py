# -*- coding: utf-8 -*-
"""Roteiro fixo de escritas (ADR 0005, Fase 2): a MESMA sequência de edições, pela API, no app
antigo (Databricks) e no novo (Postgres), partindo da mesma base. Depois,
`paridade.tabelas --escritas --desde <instante UTC>` compara as 40 tabelas (o --desde mascara só os
instantes a partir do início do roteiro; o roteiro imprime o comando pronto) — é o critério de
aceite da escrita na ADR.

Os alvos saem da base Postgres de forma determinística (ORDER BY), ANTES do roteiro, quando
ela é igual ao Databricks (paridade.tabelas 40/40). As duas bases precisam ser descartáveis:
o roteiro grava de verdade (responsável de teste, escopo, vínculo, snapshot da priorização...).
Para os dois lados gravarem o mesmo autor, o app Postgres roda com DEV_USUARIO igual ao
usuário do Databricks. Esse usuário, nos DOIS lados (DEV_USUARIO no app Postgres; o usuário do
Databricks), precisa ser admin (bv_admins): o snapshot da priorização e o Com BV exigem.
O roteiro NÃO é idempotente: rodar de novo na mesma base falha em passos como familia-periodo
(a base é descartável).

Uso (a partir de egps_analysis/app):
  PG_DSN=postgresql://... python -m paridade.escritas --antigo http://127.0.0.1:8010 \\
      --novo http://127.0.0.1:8011
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg

MARCA = "Paridade 2A"   # tudo o que o roteiro escreve leva esta marca
# escritas que devolvem o id usado pelo passo seguinte ({id} na rota)
PRODUZ_ID = {("POST", "/api/escopo"), ("POST", "/api/gestao/bv")}


def alvos(dsn):
    """Chaves reais da base, escolhidas sempre do mesmo jeito."""
    with psycopg.connect(dsn) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")

        def um(sql, *params):
            linha = c.execute(sql, params).fetchone()
            if linha is None:
                raise SystemExit(f"[escritas] base sem alvo para: {sql[:90]}")
            return linha

        egp, = um("SELECT projeto FROM sas_lineage_nodes WHERE escopo_indi ORDER BY projeto LIMIT 1")
        vinculados = ("SELECT projeto FROM sas_egp_pipeline WHERE coalesce(egp_sucessor, '') <> '' "
                      "UNION SELECT egp_sucessor FROM sas_egp_pipeline WHERE coalesce(egp_sucessor, '') <> ''")
        # Migrado é terminal: o PATCH de vínculo recusa (409) antecessor nesse status
        livres = [r[0] for r in c.execute(
            f"SELECT projeto FROM sas_lineage_nodes WHERE projeto <> %s AND projeto NOT IN ({vinculados}) "
            f"AND projeto NOT IN (SELECT projeto FROM sas_egp_pipeline WHERE status_migracao = 'Migrado') "
            f"ORDER BY projeto LIMIT 2", (egp,))]
        if len(livres) < 2:
            raise SystemExit("[escritas] base sem 2 EGPs livres (sem vínculo e fora de Migrado) para o vínculo")
        fora, area = um("SELECT projeto, area FROM sas_lineage_nodes WHERE NOT escopo_indi AND projeto NOT IN "
                        "(SELECT projeto FROM sas_escopo WHERE projeto IS NOT NULL) ORDER BY projeto LIMIT 1")
        multi, produtor_out = um(
            "SELECT o.chave_canonica, min(e.projeto) FROM sas_outputs_monitor o JOIN sas_egp_outputs e "
            "USING (chave_canonica) WHERE o.qtd_produtores > 1 AND o.chave_canonica NOT IN "
            "(SELECT chave_canonica FROM sas_output_producer_choice) GROUP BY 1 ORDER BY 1 LIMIT 1")
        produtor, = um("SELECT depende_do FROM sas_lineage_edges WHERE coalesce(via_tabelas, '') <> '' "
                       "AND projeto_alvo <> depende_do ORDER BY depende_do LIMIT 1")
        # EGP novo: fora do escopo e diferente de todos os outros EGPs que o roteiro usa
        usados = [egp, *livres, fora, produtor]
        egp_novo = next((r[0] for r in c.execute(
            "SELECT projeto FROM sas_lineage_nodes WHERE NOT escopo_indi ORDER BY projeto DESC")
            if r[0] not in usados), None)
        if egp_novo is None:
            raise SystemExit("[escritas] base sem alvo para egp_novo (fora do escopo e distinto dos demais alvos)")
        atu_key, = um("SELECT egp_key FROM sas_egp_atualizados ORDER BY egp_key LIMIT 1")
        atu_tipo = c.execute("SELECT tipo_vinculo FROM sas_egp_atualizados_pipeline WHERE egp_key = %s",
                             (atu_key,)).fetchone()
        return {
            "input": um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'tabela' "
                        "AND NOT coalesce(orfao, false) ORDER BY qtd_projetos DESC, chave_canonica LIMIT 1")[0],
            "arquivo": um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'arquivo' "
                          "AND NOT coalesce(orfao, false) ORDER BY chave_canonica LIMIT 1")[0],
            "egp": egp,
            "par": um("SELECT projeto, chave_canonica FROM sas_egp_inputs WHERE projeto = %s "
                      "ORDER BY chave_canonica LIMIT 1", egp),
            "antigo": livres[0], "sucessor": livres[1],
            "produtor": produtor,
            "egp_novo": egp_novo,
            "fora": fora, "area": area,
            "output": um("SELECT chave_canonica FROM sas_outputs_monitor ORDER BY chave_canonica LIMIT 1")[0],
            "multi": multi, "produtor_out": produtor_out,
            "atu_key": atu_key,
            "atu_tipo": "substituicao" if (atu_tipo or [None])[0] != "substituicao" else "atualizacao",
        }


def roteiro(a):
    """(método, rota, corpo) — rota com {id} usa o id que a escrita anterior devolveu DAQUELE lado."""
    egp_dor1 = a["fora"].split("__", 1)[-1]
    return [
        ("POST", "/api/responsaveis-bv", {"nome": f"Teste {MARCA}", "subarea": "Cobrança"}),
        ("POST", "/api/analistas", {"email": "teste.paridade2a@indicium.ai", "nome": f"Teste {MARCA}"}),
        ("DELETE", "/api/analistas/teste.paridade2a@indicium.ai", None),
        ("PATCH", "/api/inputs", {"chave_canonica": a["input"], "responsavel": f"Teste {MARCA}",
                                  "observacao": MARCA}),
        ("PATCH", "/api/inputs/preworking", {"chave_canonica": a["arquivo"], "frequencia": "Diária",
                                             "recebido": "true", "data_recebimento": "2026-10-01"}),
        ("PATCH", "/api/familia-ingestao", {"categoria": "tabela", "familia": "PARIDADE_2A.FAM",
                                            "desde": "202601", "ingerida_em": "2026-10-01"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["egp"], "responsavel": f"Teste {MARCA}", "jira_id": "BV-2026"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["antigo"], "responsavel": f"Teste {MARCA}"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["antigo"], "egp_vinculo_tipo": "Substituído",
                                        "egp_sucessor": a["sucessor"]}),
        ("PATCH", "/api/egp-input-link", {"projeto": a["par"][0], "chave_canonica": a["par"][1],
                                          "link_broken": True}),
        ("PATCH", "/api/familia-periodo", {"projeto": a["egp"], "categoria": "tabela",
                                           "familia": "PARIDADE_2A.FAM", "tipo": "desde", "valor": "202601"}),
        ("PATCH", "/api/egp-dep-mantida", {"produtor": a["produtor"], "mantida": True, "motivo": MARCA}),
        ("PATCH", "/api/egps-novos", {"projeto": a["egp_novo"], "acao": "declarar"}),
        ("PATCH", "/api/egp-atualizado-pipeline", {"egp_key": a["atu_key"], "tipo_vinculo": a["atu_tipo"]}),
        ("PATCH", "/api/output-pipeline", {"chave_canonica": a["output"], "recebido": True,
                                           "recebido_data": "2026-10-01"}),
        ("POST", "/api/output-producer", {"chave_canonica": a["multi"], "projeto_escolhido": a["produtor_out"]}),
        ("POST", "/api/escopo", {"egp_dor1": egp_dor1, "area": a["area"], "projeto": a["fora"]}),
        ("DELETE", "/api/escopo/{id}", None),
        ("POST", "/api/escopo/{id}/ativar", None),
        ("POST", "/api/gestao/status", {"entity": "egp", "id": a["egp"], "autor": f"Teste {MARCA}",
                                        "texto": MARCA}),
        ("POST", "/api/gestao/bv", {"entity": "egp", "id": a["egp"], "comBv": True}),
        ("POST", "/api/gestao/bv", {"entity": "egp", "id": a["egp"], "comBv": False}),
        ("DELETE", "/api/gestao/bv?id={id}", None),
        ("POST", "/api/gestao/revisao", {"id": a["egp"], "delta": 1}),
        ("PATCH", "/api/gestao/datas", {"entity": "egp", "id": a["egp"], "campo": "inicio", "valor": "2026-10-01"}),
        ("POST", "/api/priorizacao/snapshot", {"pins": {}}),
    ]


def chama(base, metodo, rota, corpo):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(base.rstrip("/") + rota, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except (urllib.error.URLError, TimeoutError, ValueError) as e:   # sem resposta ou corpo não-JSON
        return 0, f"{type(e).__name__}: {e}"[:300]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aplica o roteiro fixo de escritas nos dois apps")
    ap.add_argument("--antigo", required=True)
    ap.add_argument("--novo", required=True)
    args = ap.parse_args(argv)
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        raise SystemExit("[escritas] defina PG_DSN com o DSN da base Postgres (descartável) que serve de referência")
    passos = roteiro(alvos(dsn))
    desde = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
    comparar = f"[escritas] para comparar depois: python -m paridade.tabelas --escritas --desde '{desde}'"
    print(comparar, flush=True)
    ultimo_id = {"antigo": None, "novo": None}
    falhas = 0
    for metodo, rota, corpo in passos:
        status = {}
        for lado, base in (("antigo", args.antigo), ("novo", args.novo)):
            if (metodo, rota) in PRODUZ_ID:
                ultimo_id[lado] = None   # nunca reaproveita o id de uma escrita anterior
            if "{id}" in rota and not ultimo_id[lado]:
                status[lado] = 0
                print(f"[escritas]   {lado}: sem id da escrita anterior", flush=True)
                continue
            st, r = chama(base, metodo, rota.replace("{id}", urllib.parse.quote(ultimo_id[lado] or "")), corpo)
            status[lado] = st
            if st == 200 and isinstance(r, dict) and r.get("id"):
                ultimo_id[lado] = r["id"]
            elif st != 200:
                ultimo_id[lado] = None
                print(f"[escritas]   {lado}: HTTP {st} {r}", flush=True)
        ok = status["antigo"] == status["novo"] == 200
        falhas += not ok
        print(f"[escritas] {'OK   ' if ok else 'FALHA'} {metodo} {rota} {status}", flush=True)
    print(f"[escritas] {len(passos) - falhas}/{len(passos)} escritas aceitas nos dois lados")
    print(comparar, flush=True)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()

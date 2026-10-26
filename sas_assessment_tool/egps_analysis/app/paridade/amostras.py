# -*- coding: utf-8 -*-
"""Rotas GET com parâmetro, com valores de amostra tirados do próprio espelho (ADR 0005).

As rotas sem parâmetro (paridade.compara.rotas_get) não exercitam as que pedem `chave`,
`projeto` etc. nem os filtros que mudam o SQL (área, recorte). Aqui sai uma lista fixa de
rotas, com amostras ESCOLHIDAS DE FORMA DETERMINÍSTICA (ORDER BY), para a comparação
rodar igual duas vezes seguidas.
"""
import urllib.parse

import psycopg

_q = urllib.parse.quote


def rotas(dsn):
    with psycopg.connect(dsn) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")

        def um(sql, n=1):
            return [r[0] for r in c.execute(sql + f" LIMIT {n}")]

        area = um("SELECT area FROM sas_lineage_nodes WHERE escopo_indi GROUP BY area ORDER BY count(*) DESC, area")
        egps = (um("SELECT projeto FROM sas_lineage_nodes WHERE escopo_indi ORDER BY n_inputs DESC, projeto", 2)
                + um("SELECT projeto FROM sas_egp_pipeline WHERE egp_sucessor IS NOT NULL ORDER BY projeto")
                + um("SELECT projeto FROM sas_lineage_nodes WHERE NOT escopo_indi ORDER BY n_inputs DESC, projeto"))
        inputs = (um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'tabela' AND NOT orfao "
                     "ORDER BY qtd_projetos DESC, chave_canonica", 2)
                  + um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'arquivo' AND NOT orfao "
                       "ORDER BY qtd_projetos DESC, chave_canonica")
                  + um("SELECT chave_canonica FROM sas_inputs_monitor WHERE NOT orfao AND artifact ~ '_20[0-9]{4}' "
                       "ORDER BY qtd_projetos DESC, chave_canonica"))      # safra: caminho da família
        outputs = (um("SELECT chave_canonica FROM sas_outputs_monitor WHERE qtd_produtores > 1 "
                      "ORDER BY qtd_produtores DESC, chave_canonica")
                   + um("SELECT chave_canonica FROM sas_output_producer_choice ORDER BY chave_canonica"))
        nos = um("SELECT projeto_alvo FROM sas_lineage_edges GROUP BY projeto_alvo ORDER BY count(*) DESC, projeto_alvo")
        gestao = [("egp", x) for x in um("SELECT entity_id FROM sas_gestao_status WHERE entity = 'egp' "
                                          "GROUP BY entity_id ORDER BY count(*) DESC, entity_id")]
        gestao += [("input", x) for x in um("SELECT entity_id FROM sas_gestao_status WHERE entity = 'input' "
                                             "GROUP BY entity_id ORDER BY count(*) DESC, entity_id")]
        versoes = um("SELECT versao_id FROM sas_egp_atualizados ORDER BY versao_id", 2)
    saida = []
    saida += [f"/api/egp?projeto={_q(p)}" for p in egps]
    saida += [f"/api/input?chave={_q(k)}" for k in inputs]
    saida += [f"/api/audit?chave={_q(k)}" for k in inputs[:2]]
    saida += [f"/api/output?chave={_q(k)}" for k in outputs]
    saida += [f"/api/lineage/neighbors?node={_q(n)}&dir={d}" for n in nos for d in ("up", "down")]
    saida += [f"/api/gestao/status?entity={e}&id={_q(i)}" for e, i in gestao]
    saida += [f"/api/egp-atualizado?versao_id={_q(v)}" for v in versoes]
    for a in area:                              # filtros que mudam o SQL
        saida += [f"/api/metrics?scope=indi&area={_q(a)}",
                  f"/api/inputs?scope=indi&area={_q(a)}&categoria=tabela",
                  f"/api/inputs-egps?scope=indi&area={_q(a)}",
                  f"/api/scope-egps?scope=indi_deps&area={_q(a)}"]
    for s in ("indi_deps", "base"):
        saida += [f"/api/inputs?scope={s}", f"/api/outputs?scope={s}", f"/api/egp-readiness?scope={s}",
                  f"/api/scope-egps?scope={s}", f"/api/egp-input-units?scope={s}"]
    saida += ["/api/gestao/rows?entity=input", "/api/responsaveis-bv?incluir_inativos=true",
              "/api/analistas?incluir_inativos=true"]
    return saida

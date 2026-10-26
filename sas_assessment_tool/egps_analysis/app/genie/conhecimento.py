"""Knowledge store do Genie space: colunas, joins, expressões SQL e parâmetros dos exemplos.

Tudo aqui é LOCAL ao space (não mexe em Unity Catalog). monta_space.py lê este arquivo.
Nas expressões, as tabelas são referenciadas pelo NOME CURTO (sas_consulta_egp.coluna) — é
o alias que o Genie usa; valida_conhecimento.py roda cada uma contra o schema-alvo antes
de subir.

Fonte do estado = tabelas de CONSULTA (ADR 0004): o app grava nelas o que as telas
mostram. As tabelas cruas de linhagem/pipeline/monitor ficam FORA do space de propósito
(decisão Q14): com elas à mão o Genie "recalcularia" recorte e divergiria do app.
"""

X = {"x": True}

# Colunas comuns aos retratos atual e diário de EGP — descrevem a régua de cada tela.
_EGP = {
    "projeto": {"d": "Identificador do EGP (<Área>__<nome>). Chave do EGP em todas as tabelas.",
                "s": ["EGP", "projeto", "nome do EGP"], "em": True},
    "area": {"d": "Área de negócio do EGP.", "em": True},
    "responsavel": {"d": "E-mail (@indicium.ai) do analista responsável.",
                    "s": ["analista", "dono", "quem está com", "responsável"], "em": True},
    "responsavel_bv": {"d": "Pessoa do BV responsável pelo EGP (ponto focal do cliente).",
                       "s": ["responsável BV", "ponto focal"], "em": True},
    "classe_linha_base": {"d": "Classe do EGP na Linha de base congelada em 29/09/2026 (193 EGPs): base (168, o Escopo daquele dia), dependencia (11), ex_dependencia (14). NULL = fora da Linha de base (extras e EGPs não nomeados).",
                          "s": ["classe", "linha de base", "denominador"], "em": True},
    "na_linha_base": {"d": "true se o EGP está na Linha de base (conta no 'X de 193')."},
    "no_recorte": {"d": "true se o EGP está no Recorte vivo (Escopo + Dependências) agora."},
    "tipo": {"d": "Tipo do EGP na aba EGPs (escopo, dependencia, ...).", "em": True},
    "dep_nivel": {"d": "Nível da dependência: 1 = alimenta direto um EGP do Escopo; 2 = alimenta uma dependência de nível 1; etc."},
    "depende_de": {"d": "EGPs dos quais este depende (separados por vírgula)."},
    "e_dependencia_de": {"d": "EGPs que dependem deste (separados por vírgula).", "s": ["quem depende dele"]},
    "ex_dependencia": {"d": "true se já foi Dependência e deixou de ser."},
    "ex_motivo": {"d": "Por que deixou de ser dependência."},
    "extra": {"d": "true se é Extra: entrou depois do congelamento e foi nomeado; conta à parte ('+N extra'), nunca no total."},
    "extra_motivo": {"d": "Por que é Extra: sucessor (de um vínculo), casca, novo (declarado pela gestão), dependencia (dependência que apareceu depois do congelamento da Linha de base).", "em": True},
    "casca": {"d": "true se é Casca: antecessor sem inventário próprio, unificado em outro EGP."},
    "vinculo_tipo": {"d": "Tipo do vínculo deste EGP com o sucessor: Atualizado, Unificado (o trabalho corre no sucessor) ou Substituído.",
                     "em": True},
    "sucessor": {"d": "EGP que substitui/atualiza este."},
    "antecessores": {"d": "EGPs que este substitui/atualiza."},
    "etapa_gravada": {"d": "Etapa gravada no pipeline (pode diferir da exibida em antecessores)."},
    "status_gravado": {"d": "Status gravado no pipeline."},
    "etapa_exibida": {"d": "Etapa que as telas mostram. Use esta.", "s": ["etapa", "fase"], "em": True},
    "status_exibido": {"d": "Status que as telas mostram. 'Desatualizado' = antecessor cujo trabalho corre no sucessor. Use este.",
                       "s": ["status", "situação"], "em": True},
    "status_contagem": {"d": "Status usado nos totais de migrados (o antecessor herda o do fim da cadeia).", "em": True},
    "bloqueado_dep": {"d": "true se está bloqueado por uma dependência sem fonte.", "s": ["bloqueado por dependência"]},
    "deps_despriorizadas": {"d": "Dependências deste EGP que foram despriorizadas."},
    "n_inputs": {"d": "Inputs que o EGP lê."},
    "n_faltam": {"d": "Inputs do EGP ainda não ingeridos.", "s": ["inputs faltando", "pendências de input"]},
    "n_sem_fonte": {"d": "Inputs do EGP sem fonte conhecida."},
    "conta_total_egps": {"d": "Conta no total 'X de 193' do Resumo (= está na Linha de base)."},
    "conta_funil_migracao": {"d": "Conta no funil de migração do Escopo (classe base, 168)."},
    "conta_funil_migracao_deps": {"d": "Conta no funil de migração +deps (Linha de base inteira, 193)."},
    "conta_funil_migracao_extras": {"d": "Conta no funil de migração dos Extras."},
    "conta_migrado": {"d": "Entra no 'X/Y migrados' do funil em que estiver (etapa no coorte e status de contagem Migrado ou Despriorizado e Contabilizado)."},
    "aparece_gestao": {"d": "Aparece na lista/Kanban da aba Gestão (e no Acompanhamento): Recorte + ex-dependências contabilizadas, incluindo Extras."},
    "mes_priorizacao": {"d": "Mês do EGP no plano congelado de Priorização (1 = M1...). NULL = fora do plano.",
                        "s": ["mês", "mês do plano"]},
    "calculado_em": {"d": "Quando o app calculou este retrato (UTC)."},
}
_INPUT = {
    "chave": {"d": "Chave da unidade de input: 'familia::...' para família de safras, senão a chave da tabela/arquivo."},
    "nome": {"d": "Nome do input como aparece no app.", "s": ["tabela", "arquivo", "input"]},
    "categoria": {"d": "tabela ou arquivo.", "em": True},
    "origem": {"d": "Origem do input (BigQuery, Transacional, Arquivo, SAS/Local...).", "em": True},
    "familia": {"d": "true se a unidade é uma família de safras (conta como 1)."},
    "n_safras": {"d": "Quantas safras a família tem (1 se não é família)."},
    "safras": {"d": "Chaves das safras da família, separadas por ', '."},
    "responsavel": {"d": "E-mail (@indicium.ai) do analista responsável pela ingestão.",
                    "s": ["analista", "dono", "responsável"], "em": True},
    "etapa_efetiva": {"d": "Etapa do input no funil de ingestão, como as telas mostram.", "s": ["etapa"], "em": True},
    "status_efetivo": {"d": "Status do input como as telas mostram (já com o Sanitizado derivado).", "s": ["status"], "em": True},
    "sanitizado_derivado": {"d": "true se o app sanitizou por regra (só lido por EGPs despriorizados/antecessores), não por edição."},
    "resolvido": {"d": "Modernizado, Sanitizado ou Autoprodutor.", "s": ["ingerido", "pronto"]},
    "a_ingerir": {"d": "Conta como pendente ('a ingerir'/'não modernizado') no Resumo.", "s": ["pendente", "falta ingerir"]},
    "vinculo_ativo": {"d": "false = vínculo quebrado em todos os EGPs do Recorte (nenhum EGP precisa mais dele)."},
    "so_de_ex_dependencia": {"d": "true se só ex-dependências leem este input (não conta em total nenhum)."},
    "de_extra": {"d": "true se algum Extra lê este input."},
    "so_de_extra": {"d": "true se só Extras leem este input."},
    "balde": {"d": "Partição da Visão geral: escopo, dependencia, extra (contam no total); so_ex_dependencia, sem_vinculo_ativo (não contam).",
              "s": ["grupo", "partição"], "em": True},
    "conta_total_inputs": {"d": "Conta no Total de Inputs do Resumo."},
    "conta_funil_ingestao": {"d": "Conta no total do funil de ingestão do Escopo (sem Sanitizado)."},
    "conta_funil_ingestao_deps": {"d": "Conta no total do funil de ingestão +deps (sem Sanitizado e sem os só-de-extra)."},
    "conta_funil_ingestao_extras": {"d": "Conta no total do funil de ingestão dos Extras (sem Sanitizado)."},
    "aparece_gestao": {"d": "Aparece na Gestão de inputs (sem Sanitizado e sem input que nenhum EGP do Recorte usa mais — vínculo quebrado em todos)."},
    "egps_no_recorte": {"d": "EGPs do Recorte que leem este input, com vínculo ativo (separados por vírgula).",
                        "s": ["quem lê", "consumidores"]},
    "calculado_em": {"d": "Quando o app calculou este retrato (UTC)."},
}
_DIA = {"dia": {"d": "Dia do retrato (o último cálculo daquele dia). Compare dias para ver o que mudou.",
                "s": ["data do retrato", "ontem", "hoje"]}}

# tabela -> {coluna: config}. Chaves: d (descrição), s (sinônimos), em (entity matching +
# format assistance), x (esconder do Genie).
COLUNAS = {
    "sas_consulta_egp": _EGP,
    "sas_consulta_egp_dia": {**_DIA, **_EGP},
    "sas_consulta_input": _INPUT,
    "sas_consulta_input_dia": {**_DIA, **_INPUT},
    "sas_analistas": {
        "email": {"d": "E-mail @indicium.ai do analista; casa com os campos responsavel."},
        "nome": {"d": "Nome de exibição do analista. Use em toda resposta no lugar do e-mail.",
                 "s": ["analista", "pessoa", "nome"], "em": True},
        "ativo": {"d": "false = saiu do projeto (pode seguir como responsável de itens antigos)."},
        "papel": {"d": "Papel no time (DE, AE, Project Analyst, Tech Lead...).", "s": ["cargo", "função"], "em": True},
        "organograma": X, "created_by": X, "created_at": X, "updated_by": X, "updated_at": X,
    },
    "sas_gestao_status": {
        "entity": {"d": "Tipo do item comentado: egp, input ou egp_atualizado.", "em": True},
        "entity_id": {"d": "Item comentado: projeto (entity='egp') ou chave do input/família/safra (entity='input')."},
        "texto": {"d": "Texto do comentário — é onde está o MOTIVO de bloqueios, esperas e dependências.",
                  "s": ["comentário", "observação", "status escrito", "nota", "motivo"]},
        "autor": {"d": "Em nome de quem o comentário foi escrito (e-mail .tech ou .ai — compare pela parte antes do @).",
                  "s": ["quem comentou", "autor"]},
        "criado_por": {"d": "Usuário logado que gravou o comentário (pode diferir do autor)."},
        "ts": {"d": "Data/hora do comentário (STRING — use to_timestamp(ts))."},
        "id": X,
    },
    "sas_pipeline_audit": {
        "projeto": {"d": "EGP que mudou."},
        "funil": {"d": "'migracao' = mudanças do EGP (etapa, status, responsavel...); 'gestao' = datas e switch Com BV.",
                  "em": True},
        "campo": {"d": "Campo alterado: etapa, status, responsavel, jira_id, mes_prioridade...", "em": True},
        "valor_antigo": {"d": "Valor antes da mudança."},
        "valor_novo": {"d": "Valor depois da mudança.", "em": True},
        "ator": {"d": "Quem REGISTROU a mudança (e-mail .tech ou .ai). Não é o analista responsável.",
                 "s": ["quem mudou", "quem editou"]},
        "ts": {"d": "Data/hora da mudança (STRING — use to_timestamp(ts))."},
        "id": X,
    },
    "sas_inputs_audit": {
        "chave_canonica": {"d": "SAFRA (ou input) que mudou — case com sas_consulta_input.chave ou com uma das safras."},
        "campo": {"d": "Campo alterado: etapa, status, responsavel, observacao, preworking.* (status_humano = esquema antigo, antes de 14/08/2026).",
                  "em": True},
        "valor_antigo": {"d": "Valor antes da mudança."},
        "valor_novo": {"d": "Valor depois da mudança."},
        "updated_by": {"d": "Quem registrou a mudança (e-mail .tech ou .ai).", "s": ["quem mudou"]},
        "updated_at": {"d": "Data/hora da mudança (timestamp)."},
    },
    "sas_gestao_datas": {
        "entity": {"d": "egp ou input.", "em": True},
        "entity_id": {"d": "projeto ou chave do input."},
        "inicio": {"d": "Data de início da migração (YYYY-MM-DD).", "s": ["início"]},
        "fim_conversao": {"d": "Data de fim da conversão do código (YYYY-MM-DD)."},
        "fim": {"d": "Data de fim da migração (YYYY-MM-DD).", "s": ["término", "conclusão"]},
        "updated_by": X, "updated_at": X,
    },
    "sas_gestao_bv": {
        "entity": {"d": "egp ou input.", "em": True},
        "entity_id": {"d": "projeto ou chave do input."},
        "com_bv": {"d": "true = item parado aguardando o BV. É um LOG: o estado atual é o evento mais recente por item.",
                   "s": ["com o BV", "aguardando o BV", "aguardando cliente"]},
        "data": {"d": "Desde quando (YYYY-MM-DD) o item está nesse estado."},
        "autor": {"d": "Quem ligou/desligou o switch."},
        "ts": {"d": "Data/hora do registro (STRING — use to_timestamp(ts))."},
        "id": X,
    },
}

# ---------------------------------------------------------------- joins
# (esquerda, direita, condição, relação). Relação: MANY_TO_ONE / ONE_TO_ONE / ONE_TO_MANY.
JOINS = [
    ("sas_consulta_egp", "sas_analistas",
     "lower(`sas_consulta_egp`.`responsavel`) = lower(`sas_analistas`.`email`)", "MANY_TO_ONE"),
    ("sas_consulta_input", "sas_analistas",
     "lower(`sas_consulta_input`.`responsavel`) = lower(`sas_analistas`.`email`)", "MANY_TO_ONE"),
    ("sas_gestao_status", "sas_consulta_egp",
     "`sas_gestao_status`.`entity_id` = `sas_consulta_egp`.`projeto` AND `sas_gestao_status`.`entity` = 'egp'",
     "MANY_TO_ONE"),
    ("sas_gestao_status", "sas_consulta_input",
     "`sas_gestao_status`.`entity` = 'input' AND (`sas_gestao_status`.`entity_id` = `sas_consulta_input`.`chave` "
     "OR array_contains(split(`sas_consulta_input`.`safras`, ', '), `sas_gestao_status`.`entity_id`))",
     "MANY_TO_ONE"),
    ("sas_pipeline_audit", "sas_consulta_egp",
     "`sas_pipeline_audit`.`projeto` = `sas_consulta_egp`.`projeto`", "MANY_TO_ONE"),
    ("sas_inputs_audit", "sas_consulta_input",
     "(`sas_inputs_audit`.`chave_canonica` = `sas_consulta_input`.`chave` "
     "OR array_contains(split(`sas_consulta_input`.`safras`, ', '), `sas_inputs_audit`.`chave_canonica`))",
     "MANY_TO_ONE"),
    ("sas_gestao_bv", "sas_consulta_egp",
     "`sas_gestao_bv`.`entity_id` = `sas_consulta_egp`.`projeto` AND `sas_gestao_bv`.`entity` = 'egp'",
     "MANY_TO_ONE"),
    ("sas_gestao_datas", "sas_consulta_egp",
     "`sas_gestao_datas`.`entity_id` = `sas_consulta_egp`.`projeto` AND `sas_gestao_datas`.`entity` = 'egp'",
     "MANY_TO_ONE"),
]

# ---------------------------------------------------------------- expressões SQL
# (nome exibido, sql, sinônimos, instrução). FILTROS = booleano; CAMPOS = valor por linha;
# MEDIDAS = agregação. O alias (só campos/medidas) é derivado do nome.
CHAVE_COMENTARIO = ("concat(substr(sas_gestao_status.ts, 1, 16), '|', sas_gestao_status.autor, '|', "
                    "sas_gestao_status.texto)")
FILTROS = [
    ("EGP em andamento", "sas_consulta_egp.status_exibido IN ('Em Andamento', 'Block', 'Em espera')",
     ["em andamento", "ativo agora", "em execução"], "Trabalho em curso agora: inclui Block e Em espera."),
    ("EGP ativo no funil", "sas_consulta_egp.status_exibido IN ('Em Andamento', 'Block', 'Em espera', 'A Iniciar') "
     "AND coalesce(sas_consulta_egp.etapa_exibida, '') NOT IN ('Migrado', '')",
     ["ativo", "no backlog", "não concluído"],
     "EGP no funil e não concluído. EGP SEM etapa ainda não entrou no funil — o 'A Iniciar' dele é o "
     "padrão do app para quem não tem registro — e não é ativo."),
    ("EGP em Block", "sas_consulta_egp.status_exibido = 'Block'", ["bloqueado", "travado", "impedido"],
     "Bloqueio externo. Traga junto o último comentário (motivo)."),
    ("EGP migrado de verdade", "sas_consulta_egp.etapa_exibida = 'Migrado' AND sas_consulta_egp.status_exibido = 'Migrado'",
     ["migrado", "concluído", "entregue", "finalizado"],
     "Concluído = etapa E status Migrado. Etapa Migrado sozinha inclui despriorizados."),
    ("EGP despriorizado", "sas_consulta_egp.status_exibido = 'Despriorizado e Contabilizado'",
     ["despriorizado", "fora do backlog", "removido"], "Saiu do backlog; não é trabalho em andamento."),
    ("EGP na linha de base", "sas_consulta_egp.na_linha_base", ["conta no total", "dos 193"],
     "Denominador do 'X de 193'."),
    ("EGP extra", "sas_consulta_egp.extra", ["extra", "fora do total", "sucessor"],
     "Conta à parte ('+N extra'), nunca no total."),
    ("EGP dependência", "sas_consulta_egp.classe_linha_base = 'dependencia'", ["dependência"], None),
    ("input conta no total", "sas_consulta_input.conta_total_inputs", ["conta no Resumo"],
     "Total de Inputs do Resumo (escopo + dependência + extra)."),
    ("input pendente", "sas_consulta_input.a_ingerir", ["não ingerido", "a ingerir", "falta ingerir"],
     "Pendente como o Resumo conta."),
    ("comentário de EGP", "sas_gestao_status.entity = 'egp'", ["comentários dos EGPs"], None),
    ("comentário de input", "sas_gestao_status.entity = 'input'", ["comentários dos inputs"], None),
    ("mudança de etapa do EGP", "sas_pipeline_audit.funil = 'migracao' AND sas_pipeline_audit.campo = 'etapa'",
     ["avanço de etapa", "mudou de etapa"], None),
    ("mudança de status do EGP", "sas_pipeline_audit.funil = 'migracao' AND sas_pipeline_audit.campo = 'status'",
     ["mudou de status"], None),
]
CAMPOS = [
    ("data do comentário", "to_timestamp(sas_gestao_status.ts)", ["quando comentou"], None),
    ("data da mudança do EGP", "to_timestamp(sas_pipeline_audit.ts)", ["quando mudou"], None),
    ("quem registrou a mudança do EGP", "split(lower(sas_pipeline_audit.ator), '@')[0]", ["quem mudou"],
     "Normaliza .tech/.ai; junte com split(lower(sas_analistas.email), '@')[0] para o nome."),
    ("autor do comentário", "split(lower(sas_gestao_status.autor), '@')[0]", ["quem comentou"],
     "Normaliza .tech/.ai; junte com split(lower(sas_analistas.email), '@')[0] para o nome."),
    ("chave do comentário", CHAVE_COMENTARIO, ["comentário único"],
     "Identifica o comentário sem a repetição do lote (mesmo texto gravado em vários itens)."),
    ("retrato de (Brasília)", "date_format(sas_consulta_egp.calculado_em - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm')",
     ["data do retrato"],
     "Horário de Brasília do cálculo, já como TEXTO — use este e não converta de novo."),
]
MEDIDAS = [
    ("comentários distintos", f"count(DISTINCT {CHAVE_COMENTARIO})", ["quantos comentários", "número de comentários"],
     "Conta comentários sem inflar pelo lote. Para ITENS comentados, conte linhas."),
    ("total de EGPs (X de 193)", "count_if(sas_consulta_egp.conta_total_egps)", ["total de EGPs"], None),
    ("migrados no funil +deps", "count_if(sas_consulta_egp.conta_migrado AND sas_consulta_egp.conta_funil_migracao_deps)",
     ["X/Y migrados", "quantos migrados"], "Mesmo número do 'X/Y migrados' do funil +deps."),
    ("total de inputs (Resumo)", "count_if(sas_consulta_input.conta_total_inputs)", ["total de inputs"], None),
    ("inputs a ingerir", "count_if(sas_consulta_input.a_ingerir)", ["não modernizados", "pendentes"], None),
]

# ---------------------------------------------------------------- exemplos com parâmetro
# id do bloco em exemplos.sql -> [(nome, tipo, descrição, valor padrão)]
PARAMETROS = {
    "P1": [("analista", "STRING", "parte do nome ou do e-mail do analista", "julian")],
    "P2": [("projeto", "STRING", "parte do nome do EGP", "PERF_REVISIONAIS")],
    "P3": [("projeto", "STRING", "parte do nome do EGP", "MIS_IQ")],
    "P4": [("projeto", "STRING", "parte do nome do EGP", "ROI")],
    "P5": [("input", "STRING", "parte do nome ou da chave do input", "CARTEIRA_CL")],
}

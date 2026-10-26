-- Exemplos do Genie space. Cada bloco: `-- <ID> <pergunta>`; blocos P* usam parâmetros
-- (`:nome`) declarados em conhecimento.py. Schema sempre o de PROD aqui; monta_space.py
-- troca para o alvo (ex.: dev na pré-visualização).

-- Q1 Quantos EGPs cada analista tem por etapa e status hoje?
SELECT a.nome AS analista, e.etapa_exibida AS etapa, e.status_exibido AS status, count(*) AS egps,
       date_format(max(e.calculado_em) - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE nullif(e.responsavel, '') IS NOT NULL AND e.status_exibido <> 'Desatualizado'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
-- Q2 Quantos inputs cada analista tem por etapa e status hoje?
SELECT a.nome AS analista, i.etapa_efetiva AS etapa, i.status_efetivo AS status, count(*) AS inputs,
       date_format(max(i.calculado_em) - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_input i
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(i.responsavel) = lower(a.email)
WHERE nullif(i.responsavel, '') IS NOT NULL AND i.conta_total_inputs
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
-- R1 Por que o funil de migração +deps tem um total diferente do funil do escopo?
SELECT coalesce(classe_linha_base, 'fora da linha de base') AS classe,
       count_if(conta_funil_migracao) AS no_funil_escopo,
       count_if(conta_funil_migracao_deps) AS no_funil_deps,
       count_if(conta_funil_migracao_extras) AS no_funil_extras,
       date_format(max(calculado_em) - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
GROUP BY 1 ORDER BY 1;
-- R2 Por que o Total de Inputs do Resumo é maior que o total do funil de ingestão +deps?
SELECT balde, status_efetivo, count(*) AS inputs
FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE conta_total_inputs AND NOT conta_funil_ingestao_deps
GROUP BY 1, 2 ORDER BY 3 DESC;
-- R3 Por que a Gestão mostra mais EGPs concluídos que o "X/Y migrados" do funil +deps?
SELECT projeto, classe_linha_base, extra, extra_motivo, etapa_exibida, status_exibido, status_contagem
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE aparece_gestao
  AND (lower(etapa_exibida) = 'migrado' OR lower(etapa_exibida) LIKE '%despriorizado%')
  AND NOT (conta_funil_migracao_deps AND conta_migrado)
ORDER BY projeto;
-- R4 Por que a Gestão de inputs tem menos itens que o Total de Inputs do Resumo?
SELECT CASE WHEN conta_total_inputs AND NOT aparece_gestao THEN 'no Resumo e fora da Gestão'
            WHEN aparece_gestao AND NOT conta_total_inputs THEN 'na Gestão e fora do Resumo' END AS lado,
       balde, status_efetivo, count(*) AS inputs
FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE conta_total_inputs <> aparece_gestao
GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;
-- R5 Por que o Kanban da Gestão tem mais EGPs que o total "X de 193" do Resumo?
SELECT projeto, extra_motivo, ex_dependencia, no_recorte, status_exibido
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE aparece_gestao AND NOT conta_total_egps
ORDER BY extra_motivo, projeto;
-- R6 O que mudou nos totais de EGPs e inputs entre os dois últimos retratos diários?
WITH d AS (SELECT DISTINCT dia FROM bv_dev_db.monitoramento_sas.sas_consulta_egp_dia ORDER BY dia DESC LIMIT 2),
eg AS (
  SELECT dia, count_if(conta_total_egps) AS total_egps, count_if(conta_migrado AND conta_funil_migracao_deps) AS migrados_deps,
         count_if(extra) AS extras, count_if(no_recorte) AS no_recorte
  FROM bv_dev_db.monitoramento_sas.sas_consulta_egp_dia WHERE dia IN (SELECT dia FROM d) GROUP BY dia
), inp AS (
  SELECT dia, count_if(conta_total_inputs) AS total_inputs, count_if(a_ingerir) AS a_ingerir
  FROM bv_dev_db.monitoramento_sas.sas_consulta_input_dia WHERE dia IN (SELECT dia FROM d) GROUP BY dia
)
SELECT eg.dia, eg.total_egps, eg.migrados_deps, eg.extras, eg.no_recorte, inp.total_inputs, inp.a_ingerir
FROM eg JOIN inp ON inp.dia = eg.dia ORDER BY eg.dia;
-- C1 O que foi comentado nos últimos 7 dias?
SELECT CAST(to_timestamp(min(s.ts)) AS DATE) AS dia, coalesce(a.nome, split(s.autor, '@')[0]) AS autor,
       s.entity AS tipo, count(*) AS itens, min(s.entity_id) AS exemplo_item, s.texto
FROM bv_dev_db.monitoramento_sas.sas_gestao_status s
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON split(lower(s.autor), '@')[0] = split(lower(a.email), '@')[0]
WHERE to_timestamp(s.ts) >= date_sub(current_date(), 7)
GROUP BY substr(s.ts, 1, 16), 2, s.entity, s.texto
ORDER BY 1 DESC, 2;
-- C2 Quais comentários falam de espera ou dependência (aguardando, depende, pendente)?
WITH ult AS (
  SELECT entity, entity_id, texto, autor, to_timestamp(ts) AS quando,
         row_number() OVER (PARTITION BY entity, entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_status
)
SELECT ult.entity AS tipo, ult.entity_id AS item, CAST(ult.quando AS DATE) AS data_comentario,
       coalesce(a.nome, split(ult.autor, '@')[0]) AS autor, ult.texto
FROM ult
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON split(lower(ult.autor), '@')[0] = split(lower(a.email), '@')[0]
WHERE ult.rn = 1
  AND (lower(ult.texto) LIKE '%aguard%' OR lower(ult.texto) LIKE '%depend%' OR lower(ult.texto) LIKE '%pendente%')
ORDER BY ult.quando DESC;
-- C3 Quais EGPs em andamento ou bloqueados estão sem comentário há mais de 14 dias?
WITH ult AS (
  SELECT entity_id, max(to_timestamp(ts)) AS ultimo
  FROM bv_dev_db.monitoramento_sas.sas_gestao_status WHERE entity = 'egp' GROUP BY 1
)
SELECT a.nome AS analista, e.projeto, e.etapa_exibida, e.status_exibido,
       CAST(ult.ultimo AS DATE) AS ultimo_comentario,
       datediff(current_date(), CAST(ult.ultimo AS DATE)) AS dias_sem_comentario
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
LEFT JOIN ult ON ult.entity_id = e.projeto
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE e.status_exibido IN ('Em Andamento', 'Block', 'Em espera')
  AND (ult.ultimo IS NULL OR ult.ultimo < date_sub(current_date(), 14))
ORDER BY dias_sem_comentario DESC NULLS FIRST;
-- C4 Quantos comentários cada pessoa escreveu por semana no último mês?
SELECT date_trunc('WEEK', to_timestamp(s.ts)) AS semana, coalesce(a.nome, split(s.autor, '@')[0]) AS autor,
       count(DISTINCT CASE WHEN s.entity = 'egp' THEN concat(substr(s.ts, 1, 16), s.texto) END) AS comentarios_egp,
       count(DISTINCT CASE WHEN s.entity = 'input' THEN concat(substr(s.ts, 1, 16), s.texto) END) AS comentarios_input,
       count(*) AS itens_comentados
FROM bv_dev_db.monitoramento_sas.sas_gestao_status s
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON split(lower(s.autor), '@')[0] = split(lower(a.email), '@')[0]
WHERE to_timestamp(s.ts) >= date_sub(current_date(), 28)
GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC;
-- B1 Quais EGPs estão em Block, desde quando e por quê?
WITH desde AS (
  SELECT projeto, max(to_timestamp(ts)) AS entrou_em_block
  FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit
  WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Block' GROUP BY 1
), ult AS (
  SELECT entity_id, texto, to_timestamp(ts) AS quando,
         row_number() OVER (PARTITION BY entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_status WHERE entity = 'egp'
)
SELECT a.nome AS analista, e.projeto, e.etapa_exibida AS etapa,
       CAST(desde.entrou_em_block AS DATE) AS em_block_desde,
       datediff(current_date(), CAST(desde.entrou_em_block AS DATE)) AS dias_em_block,
       CAST(ult.quando AS DATE) AS data_comentario, ult.texto AS ultimo_comentario
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
LEFT JOIN desde ON desde.projeto = e.projeto
LEFT JOIN ult ON ult.entity_id = e.projeto AND ult.rn = 1
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE e.status_exibido = 'Block'
ORDER BY dias_em_block DESC NULLS LAST;
-- B3 O que está parado aguardando o BV agora, e há quantos dias?
WITH ultimo AS (
  SELECT entity, entity_id, com_bv, data,
         row_number() OVER (PARTITION BY entity, entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_bv
)
SELECT u.entity AS tipo, u.entity_id AS item, u.data AS com_bv_desde,
       datediff(current_date(), to_date(u.data)) AS dias_com_bv,
       coalesce(ae.nome, ai.nome) AS analista
FROM ultimo u
LEFT JOIN bv_dev_db.monitoramento_sas.sas_consulta_egp e ON u.entity = 'egp' AND e.projeto = u.entity_id
LEFT JOIN bv_dev_db.monitoramento_sas.sas_consulta_input i
  ON u.entity = 'input' AND (i.chave = u.entity_id OR array_contains(split(i.safras, ', '), u.entity_id))
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas ae ON lower(e.responsavel) = lower(ae.email)
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas ai ON lower(i.responsavel) = lower(ai.email)
WHERE u.rn = 1 AND u.com_bv
  -- switch esquecido ligado em item já resolvido não é espera
  AND NOT coalesce(e.status_exibido IN ('Migrado', 'Despriorizado e Contabilizado'), false)
  AND NOT coalesce(i.resolvido, false)
ORDER BY dias_com_bv DESC;
-- B4 Quais EGPs ativos estão parados na mesma etapa há mais tempo?
WITH ult_etapa AS (
  SELECT projeto, max(to_timestamp(ts)) AS entrou_na_etapa
  FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit
  WHERE funil = 'migracao' AND campo = 'etapa' GROUP BY 1
)
SELECT a.nome AS analista, e.projeto, e.etapa_exibida AS etapa, e.status_exibido AS status,
       CAST(u.entrou_na_etapa AS DATE) AS na_etapa_desde,
       datediff(current_date(), CAST(u.entrou_na_etapa AS DATE)) AS dias_na_etapa
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
LEFT JOIN ult_etapa u ON u.projeto = e.projeto
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE e.status_exibido IN ('Em Andamento', 'Block', 'Em espera', 'A Iniciar')
  AND coalesce(e.etapa_exibida, '') NOT IN ('Migrado', '')
ORDER BY dias_na_etapa DESC NULLS LAST;
-- B5 Em qual etapa do funil de migração os EGPs estão se acumulando?
SELECT etapa_exibida AS etapa, count(*) AS egps_ativos,
       count_if(status_exibido = 'Block') AS em_block, count_if(status_exibido = 'Em espera') AS em_espera,
       date_format(max(calculado_em) - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE conta_funil_migracao_deps
  AND status_exibido IN ('Em Andamento', 'Block', 'Em espera', 'A Iniciar')
  AND coalesce(etapa_exibida, '') NOT IN ('Migrado', '')
GROUP BY 1 ORDER BY 2 DESC;
-- B6 Quais EGPs em andamento ainda dependem de inputs não ingeridos?
SELECT a.nome AS analista, e.projeto, e.etapa_exibida AS etapa, e.status_exibido AS status,
       e.n_faltam AS inputs_faltando, e.n_sem_fonte AS inputs_sem_fonte, e.bloqueado_dep
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE e.status_exibido IN ('Em Andamento', 'Block', 'Em espera') AND e.n_faltam > 0
ORDER BY e.n_faltam DESC;
-- Q5 Quais EGPs mudaram de etapa nos últimos 7 dias?
SELECT CAST(to_timestamp(au.ts) AS DATE) AS dia, au.projeto, au.valor_antigo AS de, au.valor_novo AS para,
       coalesce(a.nome, split(e.responsavel, '@')[0]) AS analista_responsavel
FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit au
LEFT JOIN bv_dev_db.monitoramento_sas.sas_consulta_egp e ON e.projeto = au.projeto
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
WHERE au.funil = 'migracao' AND au.campo = 'etapa' AND to_timestamp(au.ts) >= date_sub(current_date(), 7)
ORDER BY 1 DESC, 2;
-- P1 Quais EGPs do analista :analista estão em andamento, e qual o último comentário de cada?
WITH ult AS (
  SELECT entity_id, texto, to_timestamp(ts) AS quando,
         row_number() OVER (PARTITION BY entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_status WHERE entity = 'egp'
)
SELECT a.nome AS analista, e.projeto, e.etapa_exibida AS etapa, e.status_exibido AS status,
       CAST(ult.quando AS DATE) AS data_comentario, ult.texto AS ultimo_comentario
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON lower(e.responsavel) = lower(a.email)
LEFT JOIN ult ON ult.entity_id = e.projeto AND ult.rn = 1
WHERE (a.nome ILIKE concat('%', :analista, '%') OR a.email ILIKE concat('%', :analista, '%'))
  AND e.status_exibido IN ('Em Andamento', 'Block', 'Em espera')
ORDER BY e.status_exibido, e.projeto;
-- P2 Qual o histórico de comentários do EGP :projeto?
SELECT CAST(to_timestamp(s.ts) AS DATE) AS dia, s.entity_id AS projeto,
       coalesce(a.nome, split(s.autor, '@')[0]) AS autor, s.texto
FROM bv_dev_db.monitoramento_sas.sas_gestao_status s
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON split(lower(s.autor), '@')[0] = split(lower(a.email), '@')[0]
WHERE s.entity = 'egp' AND s.entity_id ILIKE concat('%', :projeto, '%')
ORDER BY to_timestamp(s.ts) DESC;
-- P3 O que mudou no EGP :projeto (etapa, status e responsável), em ordem?
SELECT to_timestamp(au.ts) AS quando, au.projeto, au.campo, au.valor_antigo AS de, au.valor_novo AS para,
       coalesce(a.nome, split(au.ator, '@')[0]) AS registrado_por
FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit au
LEFT JOIN bv_dev_db.monitoramento_sas.sas_analistas a ON split(lower(au.ator), '@')[0] = split(lower(a.email), '@')[0]
WHERE au.funil = 'migracao' AND au.campo IN ('etapa', 'status', 'responsavel')
  AND au.projeto ILIKE concat('%', :projeto, '%')
ORDER BY to_timestamp(au.ts) DESC;
-- P4 Em quais telas o EGP :projeto aparece, e por quê?
SELECT projeto, classe_linha_base, no_recorte, tipo, depende_de, e_dependencia_de, extra, extra_motivo,
       ex_dependencia, ex_motivo, etapa_exibida, status_exibido, status_contagem,
       conta_total_egps, conta_funil_migracao, conta_funil_migracao_deps, conta_funil_migracao_extras,
       conta_migrado, aparece_gestao, mes_priorizacao,
       date_format(calculado_em - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE projeto ILIKE concat('%', :projeto, '%');
-- P5 Em quais telas o input :input aparece, e por quê?
SELECT chave, nome, familia, n_safras, balde, etapa_efetiva, status_efetivo, sanitizado_derivado,
       resolvido, vinculo_ativo, conta_total_inputs, conta_funil_ingestao, conta_funil_ingestao_deps,
       conta_funil_ingestao_extras, aparece_gestao, egps_no_recorte,
       date_format(calculado_em - INTERVAL 3 HOURS, 'dd/MM/yyyy HH:mm') AS retrato_brasilia
FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE nome ILIKE concat('%', :input, '%') OR chave ILIKE concat('%', :input, '%')

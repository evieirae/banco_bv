-- Benchmarks do Genie space: pergunta + SQL de referência (gabarito).
-- Formato de cada bloco: `-- <ID> | <tipo> | <pergunta>`; tipo = escalar (1 valor) ou conjunto
-- (a 1ª coluna é o conjunto esperado). Usados em dois lugares:
--   * monta_space.py sobe como `benchmarks` do space (aba Benchmarks da tela do Genie);
--   * avalia.py pergunta ao Genie, roda o gabarito e compara — mede a taxa de acerto.
-- Estado de EGP/input: gabarito nas tabelas de CONSULTA (é a régua do app — ADR 0004).
-- Comentários e auditoria: gabarito nas tabelas cruas. Schema de PROD aqui; os scripts trocam.
-- Não repita aqui perguntas que já são exemplo: o benchmark mede se o Genie GENERALIZA.

-- B01 | escalar | Quantos EGPs estão em Block?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_egp WHERE status_exibido = 'Block';

-- B02 | conjunto | Quais EGPs do Julian Vital estão em Block?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE status_exibido = 'Block' AND lower(responsavel) = 'julian.vital@indicium.ai';

-- B03 | escalar | Quantos EGPs já foram migrados de verdade?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE etapa_exibida = 'Migrado' AND status_exibido = 'Migrado';

-- B04 | escalar | Quantos EGPs o Sergio Pedroso tem em andamento hoje (incluindo Block e Em espera)?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE lower(responsavel) = 'sergio.pedroso@indicium.ai'
  AND status_exibido IN ('Em Andamento', 'Block', 'Em espera');

-- B05 | conjunto | Quais EGPs estão parados aguardando o BV agora?
WITH ultimo AS (
  SELECT entity_id, com_bv,
         row_number() OVER (PARTITION BY entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_bv WHERE entity = 'egp'
)
SELECT u.entity_id FROM ultimo u
JOIN bv_dev_db.monitoramento_sas.sas_consulta_egp e ON e.projeto = u.entity_id
WHERE u.rn = 1 AND u.com_bv AND e.status_exibido NOT IN ('Migrado', 'Despriorizado e Contabilizado');

-- B06 | escalar | Quantos comentários diferentes foram escritos em inputs em setembro de 2026, sem contar repetição de lote?
SELECT count(DISTINCT concat(substr(ts, 1, 16), autor, texto))
FROM bv_dev_db.monitoramento_sas.sas_gestao_status
WHERE entity = 'input' AND to_timestamp(ts) >= '2026-09-01' AND to_timestamp(ts) < '2026-10-01';

-- B07 | escalar | Quantas pessoas diferentes escreveram comentários em EGPs em setembro de 2026?
SELECT count(DISTINCT split(lower(autor), '@')[0])
FROM bv_dev_db.monitoramento_sas.sas_gestao_status
WHERE entity = 'egp' AND to_timestamp(ts) >= '2026-09-01' AND to_timestamp(ts) < '2026-10-01';

-- B08 | conjunto | Quais EGPs estão hoje na etapa Validação em DES?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE etapa_exibida = 'Validação em DES';

-- B09 | escalar | Há quantos dias o EGP Cobranças__MIS_IQ_v2_NEW está em Block?
SELECT datediff(current_date(), CAST(max(to_timestamp(ts)) AS DATE))
FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit
WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Block' AND projeto = 'Cobranças__MIS_IQ_v2_NEW';

-- B10 | escalar | Quantos EGPs chegaram na etapa Migrado em setembro de 2026?
SELECT count(DISTINCT projeto) FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit
WHERE funil = 'migracao' AND campo = 'etapa' AND valor_novo = 'Migrado'
  AND to_timestamp(ts) >= '2026-09-01' AND to_timestamp(ts) < '2026-10-01';

-- B11 | escalar | Quantos inputs o Marlon Lourenço ainda tem pendentes de ingestão?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE lower(responsavel) = 'marlon.lourenco@indicium.ai' AND a_ingerir;

-- B12 | conjunto | Quais EGPs em andamento ainda dependem de algum input não ingerido?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE status_exibido IN ('Em Andamento', 'Block', 'Em espera') AND n_faltam > 0;

-- B13 | conjunto | Quais EGPs ativos estão sem responsável?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE nullif(responsavel, '') IS NULL
  AND status_exibido IN ('Em Andamento', 'Block', 'Em espera', 'A Iniciar')
  AND coalesce(etapa_exibida, '') NOT IN ('Migrado', '');

-- B14 | escalar | Quantas mudanças de status de EGP a Morgana Hübner registrou em setembro de 2026?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_pipeline_audit
WHERE funil = 'migracao' AND campo = 'status' AND split(lower(ator), '@')[0] = 'morgana.hubner'
  AND to_timestamp(ts) >= '2026-09-01' AND to_timestamp(ts) < '2026-10-01';

-- B15 | conjunto | Quais EGPs estão em Block e o último comentário deles fala em dependência?
WITH ult AS (
  SELECT entity_id, texto,
         row_number() OVER (PARTITION BY entity_id ORDER BY to_timestamp(ts) DESC) AS rn
  FROM bv_dev_db.monitoramento_sas.sas_gestao_status WHERE entity = 'egp'
)
SELECT e.projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp e
JOIN ult ON ult.entity_id = e.projeto AND ult.rn = 1
WHERE e.status_exibido = 'Block' AND lower(ult.texto) LIKE '%depend%';

-- B16 | escalar | Quantos EGPs o funil de migração +deps tem a mais que o funil do escopo?
SELECT count_if(conta_funil_migracao_deps) - count_if(conta_funil_migracao)
FROM bv_dev_db.monitoramento_sas.sas_consulta_egp;

-- B17 | conjunto | Quais EGPs aparecem na aba Gestão mas não contam no total de EGPs do Resumo?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE aparece_gestao AND NOT conta_total_egps;

-- B18 | escalar | Quantos inputs contam no Total de Inputs do Resumo mas não aparecem na Gestão?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE conta_total_inputs AND NOT aparece_gestao;

-- B19 | escalar | Quantos inputs que nenhum EGP precisa mais (vínculo quebrado em todos) ainda aparecem na Gestão?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE aparece_gestao AND balde = 'sem_vinculo_ativo';

-- B20 | conjunto | Quais EGPs extras já contam como migrados no funil de extras?
SELECT projeto FROM bv_dev_db.monitoramento_sas.sas_consulta_egp
WHERE conta_funil_migracao_extras AND conta_migrado;

-- B21 | escalar | Quantos inputs lidos só pelos extras ainda faltam ingerir?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE balde = 'extra' AND a_ingerir;

-- B22 | escalar | Quantos EGPs são casca?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_egp WHERE casca;

-- B23 | escalar | Quantos inputs Sanitizados contam no Total de Inputs mas ficam fora do funil de ingestão +deps?
SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_consulta_input
WHERE conta_total_inputs AND NOT conta_funil_ingestao_deps AND status_efetivo = 'Sanitizado'

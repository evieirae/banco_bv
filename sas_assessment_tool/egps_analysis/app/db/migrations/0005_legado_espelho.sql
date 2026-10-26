-- Espelho fiel das tabelas Delta que o app lê (ADR 0005, Fase 1 — decisão de 14/10/2026).
--
-- Na Fase 1 o app na AWS só LÊ, e o Databricks é a fonte da verdade. Cada tabela que o app lê
-- vira uma cópia fiel em `legado` (mesmas colunas e tipos, sem restrição nenhuma: o Delta não
-- tem PK nem FK, e a cópia não pode recusar o que o Databricks aceitou). A view compat.<tabela>
-- só lê de lá, então a resposta da API sai igual à do Databricks por construção.
-- `timestamp` é SEM fuso e em UTC: CAST(x AS STRING) sai como no Spark e o driver devolve
-- AAAA-MM-DDTHH:MM:SS.mmmZ, como o JSON do Databricks.
-- O de-para com correções para o schema novo é da Fase 2, por grupo; aí a view de cada grupo
-- passa a ler do schema novo e `legado` encolhe até sumir.
-- Lista de colunas: sync/espelho_tabelas.py (o teste test_espelho confere as duas).

CREATE SCHEMA legado;

CREATE TABLE legado.sas_inputs_monitor (
  chave_canonica text,
  artifact text,
  categoria text,
  source_types text,
  qtd_projetos integer,
  areas text,
  escopo_indi boolean,
  modernizada_auto text,
  status_humano text,
  responsavel text,
  observacao text,
  updated_at timestamp,
  updated_by text,
  orfao boolean,
  refreshed_at timestamp,
  origem text,
  paths_fisicos text,
  n_paths_fisicos integer,
  etapa text,
  status text
);

CREATE TABLE legado.sas_egp_inputs (
  projeto text,
  area text,
  onda text,
  escopo_indi boolean,
  ciclo_id integer,
  chave_canonica text,
  artifact text,
  categoria text,
  source_types text,
  modernizada_auto text
);

CREATE TABLE legado.sas_lineage_nodes (
  projeto text,
  area text,
  onda text,
  n_inputs integer,
  n_outputs integer,
  escopo_indi boolean,
  ciclo_id integer,
  loc integer,
  code_tasks_count integer,
  n_outputs_avaliados integer,
  n_outputs_consumidos_por_outro_egp integer,
  pct_outputs_consumidos_por_outro_egp double precision,
  n_egps_consumidores integer,
  n_exports_arquivos integer,
  flag_output_100pct_egp boolean,
  flag_algum_output_egp boolean,
  flag_sem_export_arquivo boolean,
  flag_output_unico boolean,
  flag_hub_multiplos_consumidores boolean
);

CREATE TABLE legado.sas_lineage_edges (
  projeto_alvo text,
  depende_do text,
  via_tabelas text,
  qtd_via integer,
  max_produtores integer
);

CREATE TABLE legado.sas_egp_outputs (
  projeto text,
  area text,
  onda text,
  escopo_indi boolean,
  chave_canonica text,
  artifact text,
  categoria text,
  apenas_contribui boolean
);

CREATE TABLE legado.sas_outputs_monitor (
  chave_canonica text,
  artifact text,
  categoria text,
  areas text,
  qtd_produtores integer,
  qtd_criadores integer,
  qtd_consumidores integer,
  terminal boolean,
  modernizada_auto text,
  escopo_indi boolean,
  paths_fisicos text
);

CREATE TABLE legado.sas_resumo_inputs (
  chave_canonica text,
  area_principal text,
  origem_bucket text,
  escopo_indi boolean,
  modernizada_auto text
);

CREATE TABLE legado.sas_funil_area (
  area text,
  qtd_dor1 integer,
  egps_enviados integer,
  egps_analisados integer
);

CREATE TABLE legado.sas_escopo (
  id text,
  egp_dor1 text,
  area text,
  status_extracao text,
  projeto text,
  origem text,
  created_by text,
  created_at text,
  ativo boolean
);

CREATE TABLE legado.sas_egp_pipeline (
  projeto text,
  etapa_migracao text,
  status_migracao text,
  etapa_progresso text,
  status_progresso text,
  updated_by text,
  updated_at text,
  responsavel text,
  mes_prioridade integer,
  jira_id text,
  responsavel_bv text,
  preworking_preenchido text,
  preworking_data text,
  egp_atualizado_key text,
  egp_vinculo_tipo text,
  egp_sucessor text
);

CREATE TABLE legado.sas_egp_input_link (
  projeto text,
  chave_canonica text,
  link_broken boolean,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_egp_dep_mantida (
  projeto text,
  chave_canonica text,
  motivo text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_output_producer_choice (
  chave_canonica text,
  projeto_escolhido text,
  chosen_by text,
  chosen_at text
);

CREATE TABLE legado.sas_outputs_pipeline (
  chave_canonica text,
  recebido text,
  recebido_data text,
  updated_by text,
  updated_at text,
  carga_fria text,
  cf_etapa text,
  cf_status text,
  cf_responsavel text,
  cf_inicio text,
  cf_fim text,
  cf_caminho text,
  cf_tabela text
);

CREATE TABLE legado.sas_inputs_preworking (
  chave_canonica text,
  origem_arquivo text,
  frequencia text,
  horario text,
  tipo_carga text,
  pos_processamento text,
  dados_sensiveis text,
  updated_by text,
  updated_at text,
  recebido text,
  data_recebimento text,
  modernizado_bv text,
  data_modernizado_bv text,
  iniciado_em text,
  concluido_em text
);

CREATE TABLE legado.sas_egp_input_periodo (
  projeto text,
  categoria text,
  familia text,
  tipo text,
  valor text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_familia_ingestao (
  categoria text,
  familia text,
  desde text,
  ingerida_em text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_app_config (
  chave text,
  valor text,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_priorizacao_snapshot (
  id text,
  payload text,
  capacidade integer,
  saved_by text,
  saved_at text
);

CREATE TABLE legado.sas_gestao_status (
  id text,
  entity text,
  entity_id text,
  autor text,
  criado_por text,
  ts text,
  texto text
);

CREATE TABLE legado.sas_gestao_datas (
  entity text,
  entity_id text,
  inicio text,
  fim_conversao text,
  fim text,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_gestao_bv (
  id text,
  entity text,
  entity_id text,
  com_bv boolean,
  data text,
  autor text,
  ts text
);

CREATE TABLE legado.sas_gestao_revisao (
  entity text,
  entity_id text,
  contador integer,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_inputs_audit (
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_pipeline_audit (
  id text,
  projeto text,
  funil text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts text
);

CREATE TABLE legado.sas_escopo_audit (
  id text,
  acao text,
  egp_dor1 text,
  projeto text,
  ator text,
  ts text
);

CREATE TABLE legado.sas_egp_input_link_audit (
  id text,
  projeto text,
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_atualizados (
  versao_id text,
  egp_key text,
  nome text,
  area text,
  arquivo text,
  arquivo_hash text,
  origem text,
  egp_original text,
  n_antecessores integer,
  confianca_par text,
  overlap_tasks double precision,
  autor_ultimo_save text,
  login_autor text,
  data_ultimo_save text,
  data_criacao text,
  data_recebimento text,
  valor double precision,
  esforco double precision,
  razao double precision,
  quadrante text,
  n_vetos integer,
  vetos text,
  alertas text,
  table_in_antigo integer,
  table_in_novo integer,
  a_ingerir_antigo integer,
  a_ingerir_novo integer,
  disponivel_antigo integer,
  disponivel_novo integer,
  file_in_antigo integer,
  file_in_novo integer,
  script_in_antigo integer,
  script_in_novo integer,
  outputs_antigo integer,
  outputs_novo integer,
  outputs_removidos_com_consumidor integer,
  outputs_removidos_privados integer,
  inputs_macro_nao_resolvido integer,
  inputs_rede_novos integer,
  deps_novas integer,
  loc_antigo integer,
  loc_novo integer,
  linhas_add integer,
  linhas_rem integer,
  tasks_novas integer,
  alcance_total integer,
  alcance_por_grafo integer,
  alcance_por_output integer,
  status_troca text,
  publicado_por text,
  publicado_em timestamp
);

CREATE TABLE legado.sas_egp_atualizados_inputs (
  versao_id text,
  chave_canonica text,
  artefato text,
  categoria text,
  source text,
  situacao_no_recebimento text,
  novo boolean,
  publicado_em timestamp
);

CREATE TABLE legado.sas_egp_atualizados_outputs (
  versao_id text,
  chave_canonica text,
  artefato text,
  situacao text,
  novo boolean,
  removido boolean,
  n_consumidores_externos integer,
  publicado_em timestamp,
  padrao boolean,
  categoria text
);

CREATE TABLE legado.sas_egp_atualizados_pipeline (
  egp_key text,
  etapa text,
  status text,
  responsavel text,
  updated_by text,
  updated_at timestamp,
  responsavel_bv text,
  tipo_vinculo text
);

CREATE TABLE legado.sas_analistas (
  email text,
  nome text,
  ativo boolean,
  created_by text,
  created_at text,
  updated_by text,
  updated_at text,
  organograma boolean,
  papel text
);

CREATE TABLE legado.sas_responsaveis_bv (
  nome_key text,
  nome text,
  subarea text,
  ativo boolean,
  created_by text,
  created_at text,
  updated_by text,
  updated_at text
);

-- As duas views do 1a liam o schema novo; passam a ler o espelho, como as demais
-- (o escopo_indi gravado pelo Databricks, e não o derivado, é o que o app antigo mostra).
DROP VIEW compat.sas_inputs_monitor;
DROP VIEW compat.sas_egp_inputs;

CREATE VIEW compat.sas_inputs_monitor AS SELECT chave_canonica, artifact, categoria, source_types, qtd_projetos, areas, escopo_indi, modernizada_auto, status_humano, responsavel, observacao, updated_at, updated_by, orfao, refreshed_at, origem, paths_fisicos, n_paths_fisicos, etapa, status FROM legado.sas_inputs_monitor;

CREATE VIEW compat.sas_egp_inputs AS SELECT projeto, area, onda, escopo_indi, ciclo_id, chave_canonica, artifact, categoria, source_types, modernizada_auto FROM legado.sas_egp_inputs;

CREATE VIEW compat.sas_lineage_nodes AS SELECT projeto, area, onda, n_inputs, n_outputs, escopo_indi, ciclo_id, loc, code_tasks_count, n_outputs_avaliados, n_outputs_consumidos_por_outro_egp, pct_outputs_consumidos_por_outro_egp, n_egps_consumidores, n_exports_arquivos, flag_output_100pct_egp, flag_algum_output_egp, flag_sem_export_arquivo, flag_output_unico, flag_hub_multiplos_consumidores FROM legado.sas_lineage_nodes;

CREATE VIEW compat.sas_lineage_edges AS SELECT projeto_alvo, depende_do, via_tabelas, qtd_via, max_produtores FROM legado.sas_lineage_edges;

CREATE VIEW compat.sas_egp_outputs AS SELECT projeto, area, onda, escopo_indi, chave_canonica, artifact, categoria, apenas_contribui FROM legado.sas_egp_outputs;

CREATE VIEW compat.sas_outputs_monitor AS SELECT chave_canonica, artifact, categoria, areas, qtd_produtores, qtd_criadores, qtd_consumidores, terminal, modernizada_auto, escopo_indi, paths_fisicos FROM legado.sas_outputs_monitor;

CREATE VIEW compat.sas_resumo_inputs AS SELECT chave_canonica, area_principal, origem_bucket, escopo_indi, modernizada_auto FROM legado.sas_resumo_inputs;

CREATE VIEW compat.sas_funil_area AS SELECT area, qtd_dor1, egps_enviados, egps_analisados FROM legado.sas_funil_area;

CREATE VIEW compat.sas_escopo AS SELECT id, egp_dor1, area, status_extracao, projeto, origem, created_by, created_at, ativo FROM legado.sas_escopo;

CREATE VIEW compat.sas_egp_pipeline AS SELECT projeto, etapa_migracao, status_migracao, etapa_progresso, status_progresso, updated_by, updated_at, responsavel, mes_prioridade, jira_id, responsavel_bv, preworking_preenchido, preworking_data, egp_atualizado_key, egp_vinculo_tipo, egp_sucessor FROM legado.sas_egp_pipeline;

CREATE VIEW compat.sas_egp_input_link AS SELECT projeto, chave_canonica, link_broken, updated_by, updated_at FROM legado.sas_egp_input_link;

CREATE VIEW compat.sas_egp_dep_mantida AS SELECT projeto, chave_canonica, motivo, updated_by, updated_at FROM legado.sas_egp_dep_mantida;

CREATE VIEW compat.sas_output_producer_choice AS SELECT chave_canonica, projeto_escolhido, chosen_by, chosen_at FROM legado.sas_output_producer_choice;

CREATE VIEW compat.sas_outputs_pipeline AS SELECT chave_canonica, recebido, recebido_data, updated_by, updated_at, carga_fria, cf_etapa, cf_status, cf_responsavel, cf_inicio, cf_fim, cf_caminho, cf_tabela FROM legado.sas_outputs_pipeline;

CREATE VIEW compat.sas_inputs_preworking AS SELECT chave_canonica, origem_arquivo, frequencia, horario, tipo_carga, pos_processamento, dados_sensiveis, updated_by, updated_at, recebido, data_recebimento, modernizado_bv, data_modernizado_bv, iniciado_em, concluido_em FROM legado.sas_inputs_preworking;

CREATE VIEW compat.sas_egp_input_periodo AS SELECT projeto, categoria, familia, tipo, valor, updated_by, updated_at FROM legado.sas_egp_input_periodo;

CREATE VIEW compat.sas_familia_ingestao AS SELECT categoria, familia, desde, ingerida_em, updated_by, updated_at FROM legado.sas_familia_ingestao;

CREATE VIEW compat.sas_app_config AS SELECT chave, valor, updated_by, updated_at FROM legado.sas_app_config;

CREATE VIEW compat.sas_priorizacao_snapshot AS SELECT id, payload, capacidade, saved_by, saved_at FROM legado.sas_priorizacao_snapshot;

CREATE VIEW compat.sas_gestao_status AS SELECT id, entity, entity_id, autor, criado_por, ts, texto FROM legado.sas_gestao_status;

CREATE VIEW compat.sas_gestao_datas AS SELECT entity, entity_id, inicio, fim_conversao, fim, updated_by, updated_at FROM legado.sas_gestao_datas;

CREATE VIEW compat.sas_gestao_bv AS SELECT id, entity, entity_id, com_bv, data, autor, ts FROM legado.sas_gestao_bv;

CREATE VIEW compat.sas_gestao_revisao AS SELECT entity, entity_id, contador, updated_by, updated_at FROM legado.sas_gestao_revisao;

CREATE VIEW compat.sas_inputs_audit AS SELECT chave_canonica, campo, valor_antigo, valor_novo, updated_by, updated_at FROM legado.sas_inputs_audit;

CREATE VIEW compat.sas_pipeline_audit AS SELECT id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit;

CREATE VIEW compat.sas_escopo_audit AS SELECT id, acao, egp_dor1, projeto, ator, ts FROM legado.sas_escopo_audit;

CREATE VIEW compat.sas_egp_input_link_audit AS SELECT id, projeto, chave_canonica, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_input_link_audit;

CREATE VIEW compat.sas_egp_atualizados AS SELECT versao_id, egp_key, nome, area, arquivo, arquivo_hash, origem, egp_original, n_antecessores, confianca_par, overlap_tasks, autor_ultimo_save, login_autor, data_ultimo_save, data_criacao, data_recebimento, valor, esforco, razao, quadrante, n_vetos, vetos, alertas, table_in_antigo, table_in_novo, a_ingerir_antigo, a_ingerir_novo, disponivel_antigo, disponivel_novo, file_in_antigo, file_in_novo, script_in_antigo, script_in_novo, outputs_antigo, outputs_novo, outputs_removidos_com_consumidor, outputs_removidos_privados, inputs_macro_nao_resolvido, inputs_rede_novos, deps_novas, loc_antigo, loc_novo, linhas_add, linhas_rem, tasks_novas, alcance_total, alcance_por_grafo, alcance_por_output, status_troca, publicado_por, publicado_em FROM legado.sas_egp_atualizados;

CREATE VIEW compat.sas_egp_atualizados_inputs AS SELECT versao_id, chave_canonica, artefato, categoria, source, situacao_no_recebimento, novo, publicado_em FROM legado.sas_egp_atualizados_inputs;

CREATE VIEW compat.sas_egp_atualizados_outputs AS SELECT versao_id, chave_canonica, artefato, situacao, novo, removido, n_consumidores_externos, publicado_em, padrao, categoria FROM legado.sas_egp_atualizados_outputs;

CREATE VIEW compat.sas_egp_atualizados_pipeline AS SELECT egp_key, etapa, status, responsavel, updated_by, updated_at, responsavel_bv, tipo_vinculo FROM legado.sas_egp_atualizados_pipeline;

CREATE VIEW compat.sas_analistas AS SELECT email, nome, ativo, created_by, created_at, updated_by, updated_at, organograma, papel FROM legado.sas_analistas;

CREATE VIEW compat.sas_responsaveis_bv AS SELECT nome_key, nome, subarea, ativo, created_by, created_at, updated_by, updated_at FROM legado.sas_responsaveis_bv;


-- Funções do Spark que o app usa em rotas GET e ainda faltavam (levantamento de 14/10).
-- instr(str, sub): posição a partir de 1; 0 se não acha; NULL se algum lado é NULL.
CREATE FUNCTION compat.instr(text, text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT strpos($1, $2) $$;

-- regexp_extract(str, regex, grupo): '' quando não casa (o Spark não devolve NULL).
CREATE FUNCTION compat.regexp_extract(text, text, integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN $1 IS NULL THEN NULL ELSE coalesce((regexp_match($1, $2))[$3], '') END
$$;

-- Leitura para os dois papéis; regravação só para a sincronização. As views novas de compat
-- já nascem legíveis pelos privilégios padrão da 0004.
GRANT USAGE ON SCHEMA legado TO app_leitura, sincronizador;
GRANT SELECT ON ALL TABLES IN SCHEMA legado TO app_leitura, sincronizador;
GRANT INSERT, DELETE ON ALL TABLES IN SCHEMA legado TO sincronizador;
ALTER DEFAULT PRIVILEGES IN SCHEMA legado GRANT SELECT ON TABLES TO app_leitura, sincronizador;

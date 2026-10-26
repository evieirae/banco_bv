CREATE SCHEMA IF NOT EXISTS bv_dev_db.monitoramento_sas;

CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_inputs_monitor (
  chave_canonica STRING, artifact STRING, categoria STRING, origem STRING, source_types STRING,
  qtd_projetos INT, areas STRING, escopo_indi BOOLEAN, modernizada_auto STRING,
  paths_fisicos STRING, n_paths_fisicos INT,
  status_humano STRING, etapa STRING, status STRING, responsavel STRING, observacao STRING,
  updated_at TIMESTAMP, updated_by STRING,
  orfao BOOLEAN, refreshed_at TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_pipeline_metrics (
  captured_at TIMESTAMP, escopo STRING, metric STRING, valor BIGINT
) USING DELTA;

CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_inputs_audit (
  chave_canonica STRING, campo STRING, valor_antigo STRING, valor_novo STRING,
  updated_by STRING, updated_at TIMESTAMP
) USING DELTA;

-- staging+merge de bv_dev_db.monitoramento_sas.sas_inputs_monitor: 10188 linhas (preview de 1 batch)
INSERT INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor_stg (chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas, escopo_indi, modernizada_auto, paths_fisicos, n_paths_fisicos) VALUES
('script::00-INCLUDEMACROSDDR.SAS', '00-IncludeMacrosDDR.sas', 'script', 'Script', '', 1, 'SAS_UC4', false, 'A ingerir', '/&Modo_Exec./riscosmercado/rmsas/bin/sas/joblist/00-IncludeMacrosDDR.sas', 1),
('script::02-GERADDRDOCTO2011.SAS', '02-GeraDDRDocto2011.sas', 'script', 'Script', '', 1, 'SAS_UC4', false, 'A ingerir', '/&Modo_Exec./riscosmercado/rmsas/bin/sas/joblist/02-GeraDDRDocto2011.sas', 1),
('script::02-GERADDR_XML_DOCTO2011.SAS', '02-GeraDDR_XML_Docto2011.sas', 'script', 'Script', '', 1, 'SAS_UC4', false, 'A ingerir', '/&Modo_Exec./riscosmercado/rmsas/bin/sas/joblist/02-GeraDDR_XML_Docto2011.sas', 1),
('script::03-EXECUTAMOTORCVA.SAS', '03-ExecutaMotorCVA.sas', 'script', 'Script', '', 1, 'SAS_UC4', false, 'A ingerir', '/&Modo_Exec./riscosmercado/rmsas/bin/sas/joblist/03-ExecutaMotorCVA.sas', 1),
('script::00-INCLUDEFATORVERTICE.SAS', '00-IncludeFatorVertice.sas', 'script', 'Script', '', 1, 'SAS_UC4', false, 'A ingerir', '/&Modo_Exec./riscosmercado/rmsas/bin/sas/joblist/00-IncludeFatorVertice.sas', 1);

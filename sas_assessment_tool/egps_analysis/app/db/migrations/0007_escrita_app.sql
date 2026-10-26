-- Escrita do app no Postgres (Fase 2, decisão de 15/10/2026): o espelho `legado` vira a FONTE.
-- O app grava pelas MESMAS views compat que lê: são views simples de uma tabela só, e o
-- Postgres aceita INSERT/UPDATE/DELETE/MERGE nelas, gravando no legado. Assim o SQL de escrita
-- muda só de dialeto, não de tabela.
--
-- app_escrita = app_leitura + escrita nas 33 views que o backend grava — entre elas os nós da
-- linhagem e as tabelas de input/output do corpus (o recálculo do escopo marca escopo_indi) e o
-- funil/auditoria dos EGPs atualizados (tipo_vinculo). As 7 que só o publish grava — as arestas
-- da linhagem, a versão recebida e o I/O dos EGPs atualizados (sas_egp_atualizados, _inputs,
-- _outputs), o alias canônico, as métricas e o resumo por projeto — ficam para o papel do
-- publish (plano 2b). Na Fase 1 o app segue com app_leitura e nada disto é usado.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_escrita') THEN
    CREATE ROLE app_escrita NOLOGIN;
  END IF;
END $$;

GRANT app_leitura TO app_escrita;

GRANT INSERT, UPDATE, DELETE ON
  compat.sas_analistas,
  compat.sas_app_config,
  compat.sas_egp_atualizados_audit,
  compat.sas_egp_atualizados_pipeline,
  compat.sas_egp_dep_mantida,
  compat.sas_egp_dep_mantida_audit,
  compat.sas_egp_input_link,
  compat.sas_egp_input_link_audit,
  compat.sas_egp_input_periodo,
  compat.sas_egp_input_periodo_audit,
  compat.sas_egp_inputs,
  compat.sas_egp_outputs,
  compat.sas_egp_pipeline,
  compat.sas_escopo,
  compat.sas_escopo_audit,
  compat.sas_familia_ingestao,
  compat.sas_familia_ingestao_audit,
  compat.sas_funil_area,
  compat.sas_gestao_bv,
  compat.sas_gestao_datas,
  compat.sas_gestao_revisao,
  compat.sas_gestao_status,
  compat.sas_inputs_audit,
  compat.sas_inputs_monitor,
  compat.sas_inputs_preworking,
  compat.sas_lineage_nodes,
  compat.sas_output_producer_choice,
  compat.sas_outputs_monitor,
  compat.sas_outputs_pipeline,
  compat.sas_pipeline_audit,
  compat.sas_priorizacao_snapshot,
  compat.sas_responsaveis_bv,
  compat.sas_resumo_inputs
TO app_escrita;

-- O app entra com o usuário MESTRE e baixa a sessão para PG_PAPEL (app_escrita na Fase 2).
GRANT app_escrita TO CURRENT_USER;

-- uuid() do Spark (ids de auditoria gerados no INSERT): texto, como o Spark devolve.
CREATE FUNCTION compat.uuid() RETURNS text
LANGUAGE sql VOLATILE AS $$ SELECT gen_random_uuid()::text $$;

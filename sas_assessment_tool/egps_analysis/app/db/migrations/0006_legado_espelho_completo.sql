-- Espelho completo (Fase 2, 15/10/2026): as 7 tabelas que as escritas e o publish leem ou
-- gravam e que a 0005 deixou de fora. Na virada o espelho vira a FONTE (app e publish passam a
-- escrever nele): sem estas, quatro históricos (vínculo mantido, período, ingestão de família,
-- EGPs atualizados) e as tabelas do publish (resumo por projeto, métricas, alias canônico)
-- começariam vazios na AWS. Mesmo molde da 0005: colunas e tipos do Delta, sem PK/FK/NOT NULL,
-- e a view compat só lê do legado.

CREATE TABLE legado.sas_egp_atualizados_audit (
  id text,
  egp_key text,
  campo text,
  valor_antigo text,
  valor_novo text,
  autor text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_dep_mantida_audit (
  id text,
  projeto text,
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_input_periodo_audit (
  id text,
  projeto text,
  categoria text,
  familia text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_familia_ingestao_audit (
  id text,
  categoria text,
  familia text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_input_alias_canonico (
  chave_canonica text,
  chave_canonica_alvo text,
  membro text,
  lib text,
  lib_canonica text,
  path_fisico text,
  n_egps integer,
  eh_canonico boolean,
  origem_decisao text,
  motivo text,
  ativo boolean,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_pipeline_metrics (
  captured_at timestamp,
  escopo text,
  metric text,
  valor bigint
);

CREATE TABLE legado.sas_resumo_proj (
  chave_canonica text,
  projeto text
);

CREATE VIEW compat.sas_egp_atualizados_audit AS SELECT id, egp_key, campo, valor_antigo, valor_novo, autor, ts FROM legado.sas_egp_atualizados_audit;

CREATE VIEW compat.sas_egp_dep_mantida_audit AS SELECT id, projeto, chave_canonica, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_dep_mantida_audit;

CREATE VIEW compat.sas_egp_input_periodo_audit AS SELECT id, projeto, categoria, familia, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_input_periodo_audit;

CREATE VIEW compat.sas_familia_ingestao_audit AS SELECT id, categoria, familia, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_familia_ingestao_audit;

CREATE VIEW compat.sas_input_alias_canonico AS SELECT chave_canonica, chave_canonica_alvo, membro, lib, lib_canonica, path_fisico, n_egps, eh_canonico, origem_decisao, motivo, ativo, updated_by, updated_at FROM legado.sas_input_alias_canonico;

CREATE VIEW compat.sas_pipeline_metrics AS SELECT captured_at, escopo, metric, valor FROM legado.sas_pipeline_metrics;

CREATE VIEW compat.sas_resumo_proj AS SELECT chave_canonica, projeto FROM legado.sas_resumo_proj;

-- O privilégio padrão do legado (0005) só dá SELECT; o INSERT/DELETE da sincronização foi dado
-- às tabelas que existiam na 0005. Tabela nova precisa dele explícito: sem isto a sincronização
-- não grava as novas. O SELECT fica explícito também. As views compat já nascem legíveis pela 0004.
GRANT SELECT ON legado.sas_egp_atualizados_audit, legado.sas_egp_dep_mantida_audit, legado.sas_egp_input_periodo_audit, legado.sas_familia_ingestao_audit, legado.sas_input_alias_canonico, legado.sas_pipeline_metrics, legado.sas_resumo_proj TO app_leitura, sincronizador;
GRANT INSERT, DELETE ON legado.sas_egp_atualizados_audit, legado.sas_egp_dep_mantida_audit, legado.sas_egp_input_periodo_audit, legado.sas_familia_ingestao_audit, legado.sas_input_alias_canonico, legado.sas_pipeline_metrics, legado.sas_resumo_proj TO sincronizador;

-- compat.sas_inputs_monitor devolve updated_at/updated_by NULOS quando ninguém editou o
-- input (a sincronização grava atualizado_por = 'publish' — ver sync/mapeamento.py), como
-- o Databricks devolvia. Sem isso a comparação de leituras acusaria 11 mil diferenças falsas.
CREATE OR REPLACE VIEW compat.sas_inputs_monitor AS
SELECT i.chave                                  AS chave_canonica,
       i.artefato                               AS artifact,
       i.categoria,
       i.origem,
       array_to_string(i.source_types, ' | ')   AS source_types,
       i.qtd_projetos,
       array_to_string(i.areas, ' | ')          AS areas,
       ve.escopo_indi,
       CASE WHEN i.disponivel_auto THEN 'Disponível' ELSE 'A ingerir' END AS modernizada_auto,
       array_to_string(i.paths_fisicos, ' | ')  AS paths_fisicos,
       i.n_paths_fisicos,
       s.etapa, s.status, s.responsavel, s.observacao,
       CASE WHEN s.atualizado_por = 'publish' THEN NULL ELSE s.atualizado_em END AS updated_at,
       nullif(s.atualizado_por, 'publish')      AS updated_by,
       i.orfao,
       i.publicado_em                           AS refreshed_at
FROM corpus.input i
LEFT JOIN trabalho.estado_input s   ON s.chave = i.chave
LEFT JOIN derivado.v_input_escopo ve ON ve.chave = i.chave;

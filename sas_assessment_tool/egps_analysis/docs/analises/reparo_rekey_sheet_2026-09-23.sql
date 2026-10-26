-- ============================================================================
-- Reparo do re-key de [SHEET=] — publish de 23/09/2026
-- ============================================================================
-- CONTEXTO
--   O publish geral de 23/09/2026 16:32 UTC (Eduardo) rodou com o extractor de
--   setembro, que escreve a aba do Excel COM aspas: [SHEET='Planilha1']. O que
--   estava no project_sas era o de junho, que escrevia SEM aspas.
--
--   Como o MERGE do publish casa por chave_canonica, isso re-keyou 834 planilhas:
--   entraram 834 linhas novas (em branco) e as 834 antigas viraram orfao=true,
--   levando junto o estado humano. 117 delas tinham estado real (90 Modernizado/
--   Sanitizado, 25 Modernizado/Concluído, 1 Recebido, 1 Ingestão UAT), 58 tinham
--   responsável e 10 observação. Isso é o que inchou a fila de ingestão.
--
--   Verificado antes de escrever este script:
--     - mapeamento velha->nova é 1:1 (834/834, zero ambiguidade nos dois sentidos)
--     - 2 chaves novas JÁ foram corrigidas à mão depois do publish -> pular
--       (por isso o bloco 2 restaura 116, e não as 117)
--     - sas_egp_input_link: 12 linhas na chave velha, 0 colisões
--     - sas_inputs_preworking: 10 linhas na chave velha, 1 colisão -> pular
--     - sas_inputs_audit: 359 eventos (118 chaves) na chave velha
--
-- DECISÕES EMBUTIDAS (mudar aqui se discordar)
--   1. O formato canônico passa a ser COM aspas (é o que o extractor de setembro
--      produz). Se a decisão for voltar a tirar as aspas, este script não serve:
--      o conserto vira fix no extractor + republish.
--   2. status_humano NÃO é copiado. main.py:98-103 diz que a coluna é congelada
--      como histórico e nunca reescrita. Ela fica na linha velha, como o resto
--      do histórico dela.
--   3. updated_by/updated_at são copiados da linha velha (preserva quem decidiu).
--      O rastro do reparo fica no histórico Delta e na tabela de backup abaixo.
--   4. sas_inputs_audit É re-apontada. Não é reescrita de histórico: o evento
--      (campo/valor_antigo/valor_novo/updated_at/updated_by) fica intacto, só a
--      chave é corrigida. Sem isso o indicador mensal de Sanitizado perde as 90
--      planilhas, porque main.py:1050-1071 filtra a auditoria pelo universo vivo.
--
-- COMO RODAR
--   Bloco a bloco, conferindo o resultado de cada um. Os blocos 1 e 6 são só
--   leitura. Os blocos 2-5 escrevem. Tudo é idempotente: re-rodar não duplica
--   nem sobrescreve o que já foi corrigido à mão.
--
--   Alvo: bv_dev_db.monitoramento_sas  (PROD)
--
-- EXECUTADO EM PROD — 23/09/2026, por lucas.muller@indicium.ai
--   bloco 0  tabela _reparo_sheet_20260923_map criada (834 pares)
--   bloco 1  834/834/834 · ambiguidade 0/0 · vai_restaurar 116 · ja_editadas 2
--   bloco 2  sas_inputs_monitor      116 atualizadas
--   bloco 3  sas_egp_input_link       12 re-apontadas
--   bloco 4  sas_inputs_preworking     9 re-apontadas (1 colisao pulada: AGENTE.XLS)
--   bloco 5  sas_inputs_audit        359 re-apontadas
--   bloco 6  118 vivas com estado (91/25/1/1) · sobras: link 0, preworking 1, audit 0
--            eventos Sanitizado devolvidos ao universo vivo: 67 jul + 18 ago + 9 set
-- ============================================================================


-- ----------------------------------------------------------------------------
-- BLOCO 0 — mapa + backup (uma tabela só, serve de fonte e de rede de segurança)
-- ----------------------------------------------------------------------------
-- Materializa o par velha->nova junto com o estado a restaurar. Depois disso o
-- script não depende mais de derivar a chave por replace(), e dá para auditar /
-- desfazer olhando só esta tabela.

CREATE OR REPLACE TABLE bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map AS
SELECT
    v.chave_canonica  AS chave_velha,
    n.chave_canonica  AS chave_nova,
    v.etapa           AS etapa_velha,
    v.status          AS status_velha,
    v.responsavel     AS responsavel_velha,
    v.observacao      AS observacao_velha,
    v.status_humano   AS status_humano_velha,   -- só para registro; NÃO é copiado
    v.updated_by      AS updated_by_velha,
    v.updated_at      AS updated_at_velha,
    n.etapa           AS etapa_nova_antes,
    n.status          AS status_nova_antes,
    n.responsavel     AS responsavel_nova_antes,
    n.observacao      AS observacao_nova_antes,
    -- a linha nova foi mexida por alguém depois do publish? então é dela a razão.
    (coalesce(n.etapa, 'A Receber') <> 'A Receber'
     OR coalesce(n.status, 'A Iniciar') <> 'A Iniciar'
     OR n.responsavel IS NOT NULL
     OR n.observacao IS NOT NULL)                AS nova_ja_editada,
    -- a linha velha tem algo que valha restaurar?
    (coalesce(v.etapa, 'A Receber') <> 'A Receber'
     OR coalesce(v.status, 'A Iniciar') <> 'A Iniciar'
     OR v.responsavel IS NOT NULL
     OR v.observacao IS NOT NULL)                AS velha_tem_estado
FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor n
JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor v
  ON replace(n.chave_canonica, "'", "") = v.chave_canonica
 AND n.chave_canonica <> v.chave_canonica
WHERE n.orfao = false
  AND v.orfao = true;


-- ----------------------------------------------------------------------------
-- BLOCO 1 — pré-checks (LEITURA). Não siga se algum destes não bater.
-- ----------------------------------------------------------------------------
-- Esperado: 834 / 834 / 834
SELECT count(*) AS pares,
       count(DISTINCT chave_velha) AS velhas,
       count(DISTINCT chave_nova)  AS novas
FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map;

-- Esperado: 0 e 0. Qualquer valor > 0 significa que o replace() colapsou chaves
-- distintas e o reparo escreveria estado no arquivo errado. PARE se der > 0.
SELECT
  (SELECT count(*) FROM (SELECT chave_nova  FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map
                         GROUP BY chave_nova  HAVING count(*) > 1)) AS nova_ambigua,
  (SELECT count(*) FROM (SELECT chave_velha FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map
                         GROUP BY chave_velha HAVING count(*) > 1)) AS velha_ambigua;

-- Esperado (medido em 23/09 21:0x): vai_restaurar = 116, ja_editadas = 2
-- (DE_PARA_ASSESSORIA 1.XLSX e AGENTE.XLS). São 117 velhas com estado, menos o
-- AGENTE.XLS, cuja velha tem estado mas cuja nova já foi refeita à mão.
-- Se "ja_editadas" subiu, alguém mexeu depois — reveja a lista abaixo.
SELECT
  sum(CASE WHEN velha_tem_estado AND NOT nova_ja_editada THEN 1 ELSE 0 END) AS vai_restaurar,
  sum(CASE WHEN nova_ja_editada THEN 1 ELSE 0 END)                          AS ja_editadas
FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map;

-- As que o script vai pular, para conferência visual.
SELECT chave_nova, etapa_nova_antes, status_nova_antes, responsavel_nova_antes,
       etapa_velha, status_velha, responsavel_velha
FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map
WHERE nova_ja_editada;


-- ----------------------------------------------------------------------------
-- BLOCO 2 — restaura etapa/status/responsavel/observacao (ESCRITA)
-- ----------------------------------------------------------------------------
-- Guardas: só onde a velha tem algo E a nova continua intocada desde o publish.

MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
USING (
    SELECT chave_nova, etapa_velha, status_velha, responsavel_velha,
           observacao_velha, updated_by_velha, updated_at_velha
    FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map
    WHERE velha_tem_estado
      AND NOT nova_ja_editada
) AS m
ON t.chave_canonica = m.chave_nova
WHEN MATCHED THEN UPDATE SET
    t.etapa       = m.etapa_velha,
    t.status      = m.status_velha,
    t.responsavel = m.responsavel_velha,
    t.observacao  = m.observacao_velha,
    t.updated_by  = m.updated_by_velha,
    t.updated_at  = m.updated_at_velha;


-- ----------------------------------------------------------------------------
-- BLOCO 3 — re-aponta os vínculos EGP->input (ESCRITA)
-- ----------------------------------------------------------------------------
-- 12 linhas, 0 colisões verificadas. O NOT EXISTS mantém o bloco idempotente e
-- protege caso alguém crie o vínculo na chave nova antes de você rodar.

MERGE INTO bv_dev_db.monitoramento_sas.sas_egp_input_link AS t
USING (
    SELECT l.projeto, l.chave_canonica AS chave_velha, m.chave_nova
    FROM bv_dev_db.monitoramento_sas.sas_egp_input_link l
    JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
      ON l.chave_canonica = m.chave_velha
    WHERE NOT EXISTS (
        SELECT 1 FROM bv_dev_db.monitoramento_sas.sas_egp_input_link j
        WHERE j.projeto = l.projeto AND j.chave_canonica = m.chave_nova
    )
) AS s
ON t.projeto = s.projeto AND t.chave_canonica = s.chave_velha
WHEN MATCHED THEN UPDATE SET t.chave_canonica = s.chave_nova;


-- ----------------------------------------------------------------------------
-- BLOCO 4 — re-aponta o pré-working (ESCRITA)
-- ----------------------------------------------------------------------------
-- 10 linhas, 1 colisão conhecida: AGENTE.XLS[SHEET=PLANILHA1], que a Morgana
-- repreencheu na chave nova em 23/09 19:21. O NOT EXISTS pula essa; a linha
-- velha (16/09) fica como órfã. Se você quiser a versão antiga em vez da nova,
-- é edição manual — o script não escolhe entre duas respostas humanas.

MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_preworking AS t
USING (
    SELECT pw.chave_canonica AS chave_velha, m.chave_nova
    FROM bv_dev_db.monitoramento_sas.sas_inputs_preworking pw
    JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
      ON pw.chave_canonica = m.chave_velha
    WHERE NOT EXISTS (
        SELECT 1 FROM bv_dev_db.monitoramento_sas.sas_inputs_preworking j
        WHERE j.chave_canonica = m.chave_nova
    )
) AS s
ON t.chave_canonica = s.chave_velha
WHEN MATCHED THEN UPDATE SET t.chave_canonica = s.chave_nova;


-- ----------------------------------------------------------------------------
-- BLOCO 5 — re-aponta a auditoria (ESCRITA) — ver decisão 4 no cabeçalho
-- ----------------------------------------------------------------------------
-- 359 eventos, 118 chaves. Sem isto o indicador mensal de Sanitizado/Modernizado
-- perde as 90 planilhas: main.py filtra sas_inputs_audit pelo universo vivo, e a
-- chave velha está fora dele. O conteúdo do evento não muda, só a chave.
-- Se preferir deixar a auditoria congelada, NÃO rode este bloco — mas então o
-- número de setembro sai menor do que o trabalho que foi feito de fato.

MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_audit AS t
USING (
    SELECT chave_velha, chave_nova
    FROM bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map
) AS m
ON t.chave_canonica = m.chave_velha
WHEN MATCHED THEN UPDATE SET t.chave_canonica = m.chave_nova;


-- ----------------------------------------------------------------------------
-- BLOCO 6 — verificação (LEITURA)
-- ----------------------------------------------------------------------------
-- Esperado: 118 linhas vivas com estado = 116 restauradas pelo script + AGENTE.XLS
-- (refeita pela Francielly) + DE_PARA_ASSESSORIA 1.XLSX (estado novo, que você pôs
-- hoje na chave nova — a velha dela estava em branco).
SELECT count(*) AS vivas_com_estado
FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor i
JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
  ON i.chave_canonica = m.chave_nova
WHERE coalesce(i.etapa, 'A Receber') <> 'A Receber'
   OR coalesce(i.status, 'A Iniciar') <> 'A Iniciar'
   OR i.responsavel IS NOT NULL;

-- Esperado: o que havia antes do publish, mais o DE_PARA_ASSESSORIA —
--   Modernizado/Sanitizado 91 · Modernizado/Concluído 25 · Recebido 1 · Ingestão UAT 1
-- (90 sanitizadas restauradas + 1 nova sua; o AGENTE.XLS é o Ingestão UAT)
SELECT i.etapa, i.status, count(*) AS n
FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor i
JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
  ON i.chave_canonica = m.chave_nova
WHERE coalesce(i.etapa, 'A Receber') <> 'A Receber'
   OR coalesce(i.status, 'A Iniciar') <> 'A Iniciar'
GROUP BY i.etapa, i.status
ORDER BY n DESC;

-- Esperado: 0 sobras em todas as linhas (exceto preworking_velho = 1, a colisão).
SELECT
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_egp_input_link l
     JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
       ON l.chave_canonica = m.chave_velha)                       AS link_velho,
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_inputs_preworking p
     JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
       ON p.chave_canonica = m.chave_velha)                       AS preworking_velho,
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_inputs_audit a
     JOIN bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map m
       ON a.chave_canonica = m.chave_velha)                       AS audit_velho;


-- ----------------------------------------------------------------------------
-- DESFAZER
-- ----------------------------------------------------------------------------
-- O mapa guarda o estado das duas pontas antes do reparo, então dá para reverter
-- sem time travel:
--
--   MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
--   USING bv_dev_db.monitoramento_sas._reparo_sheet_20260923_map AS m
--     ON t.chave_canonica = m.chave_nova
--   WHEN MATCHED THEN UPDATE SET
--       t.etapa = m.etapa_nova_antes, t.status = m.status_nova_antes,
--       t.responsavel = m.responsavel_nova_antes, t.observacao = m.observacao_nova_antes;
--
-- Para os blocos 3-5, inverta o sentido do MERGE (nova -> velha).
-- O estado imediatamente anterior ao reparo também está no histórico Delta.
--
-- Depois que o reparo estiver conferido e estável, a tabela _reparo_sheet_20260923_map
-- pode ser dropada — mas só depois, porque ela é o desfazer.
-- ============================================================================


-- ============================================================================
-- O QUE ESTE SCRIPT NÃO FAZ
-- ============================================================================
-- 1. Não apaga as 834 linhas órfãs. Elas seguem com status_humano e o histórico
--    delas; sumiram das contagens porque orfao = true. Limpeza é decisão à parte.
-- 2. Não impede que o próximo publish re-keye de novo. Enquanto os dois formatos
--    existirem nos dois lados, isto se repete. O fim disso é o extractor do
--    project_sas ficar alinhado com o nosso — que já ficou, com o pacote de hoje.
--    Por isso: rodar este reparo DEPOIS do próximo publish, não antes.
-- 3. Não toca nos 5 inputs casco:: (feature do lado do BV, não do nosso pacote).

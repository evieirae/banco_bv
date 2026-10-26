-- ============================================================================
-- Consolidação de homônimos por libname — 23/09/2026
-- ============================================================================
-- O QUE É
--   249 membros de tabela SAS/Local aparecem sob mais de um libname. Separados
--   por certeza do caminho físico (docs/analises/inputs_homonimos_libname_2026-09-23.csv):
--     A  85 grupos, mesmo path em todas as linhas -> uma tabela só, aliases diferentes
--     B  92 grupos, paths distintos -> tabelas diferentes que só dividem o nome. NÃO MEXER.
--     C  72 grupos, path ausente em alguma linha -> indeterminado, falta dado.
--
--   Este script age SÓ no balde A, e dentro dele só nos 63 grupos onde ninguém
--   foi resolvido ainda (135 linhas: 63 canônicas + 72 redundantes).
--
-- POR QUE OS OUTROS 22 GRUPOS DO BALDE A FICAM DE FORA
--   15 estão "mistos" (algum irmão já Modernizado) e 7 já estão todos resolvidos.
--   Os mistos JÁ FORAM consolidados à mão, e na direção certa: o alias redundante
--   é que está Sanitizado, e o que segue pendente é o que tem o trabalho. Em
--   PERF_AMIGAVEL, CARTAO (5 EGPs) e CART_HST (1) estão Sanitizados enquanto MOVTO
--   (17 EGPs) está em Aplicação de Grant com o Marlon. Propagar "resolvido" do irmão
--   para o pendente teria cancelado a maior ingestão do grupo. Mesmo formato em
--   BASE_REGULARIZADO. Por isso a regra aqui NÃO é propagar estado.
--
-- A REGRA
--   Em cada grupo, o CANÔNICO é a linha com (1) etapa mais avançada, (2) mais EGPs
--   consumidores, (3) dentro do escopo Indicium, (4) nome do libname como desempate.
--   Os demais viram 'Modernizado / Sanitizado' com observação apontando o canônico.
--
--   Sanitizado aqui não é "descartado do projeto": é "esta linha não gera ingestão
--   própria, a tabela física entra pelo canônico". É a mesma convenção que o time já
--   aplicou à mão nos 15 grupos mistos — o script segue o precedente, não inventa um.
--
-- SEGURANÇA (medido antes de escrever)
--   As 72 linhas candidatas estão TODAS em 'A Receber / A Iniciar', com observação
--   vazia e sem responsável. Nenhuma foi tocada por analista. Só 5 das 72 estão no
--   escopo Indicium — o ganho de fila é pequeno; o valor é parar de contar a mesma
--   tabela física duas vezes.
--
--   Alvo: bv_dev_db.monitoramento_sas  (PROD)
--
-- EXECUTADO EM PROD — 23/09/2026, por lucas.muller@indicium.ai
--   bloco 0  _consolid_libname_20260923_map criada (63 grupos, 135 linhas)
--   bloco 1  63/135/63/72 · com_obs 0 · estado_nao_default 0 · no_escopo 5
--   bloco 2  72 linhas -> Modernizado / Sanitizado
--   bloco 3  72 consolidadas, 0 ainda na fila; as 63 canonicas intactas
--            (62 em A Receber + 1 em Recebido)
--   fila viva: A Receber 7.805 -> 7.730 (-75: 72 daqui + 3 de edicao no app)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- BLOCO 0 — mapa canônico/redundante (fonte dos MERGEs e desfazer)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE TABLE bv_dev_db.monitoramento_sas._consolid_libname_20260923_map AS
WITH base AS (
    SELECT chave_canonica,
           split_part(upper(artifact), '.', 1)                  AS lib,
           split_part(upper(artifact), '.', 2)                  AS membro,
           nullif(trim(coalesce(paths_fisicos, '')), '')        AS path,
           n_paths_fisicos, etapa, status, responsavel, observacao,
           escopo_indi, qtd_projetos,
           CASE etapa WHEN 'Modernizado'       THEN 6
                      WHEN 'Ingestão PRD'      THEN 5
                      WHEN 'Ingestão UAT'      THEN 4
                      WHEN 'Aplicação de Grant' THEN 3
                      WHEN 'Pré-Working'       THEN 2
                      WHEN 'Recebido'          THEN 1
                      ELSE 0 END                                AS peso_etapa
    FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor
    WHERE orfao = false
      AND categoria = 'tabela'
      AND origem IN ('SAS/Local (externo)', 'SAS/Local (dependência)')
      AND length(artifact) - length(replace(artifact, '.', '')) = 1
),
balde_a AS (   -- mesmo membro, path conhecido em todas, um path só
    SELECT membro FROM base
    GROUP BY membro
    HAVING count(DISTINCT lib) > 1
       AND count(path) = count(*)
       AND count(DISTINCT path) = 1
       AND max(n_paths_fisicos) <= 1
),
grupo AS (
    SELECT b.*, count(*) OVER (PARTITION BY b.membro) AS n_no_grupo,
           sum(CASE WHEN b.etapa = 'Modernizado' THEN 1 ELSE 0 END)
               OVER (PARTITION BY b.membro)           AS n_resolvidas
    FROM base b JOIN balde_a a USING (membro)
)
SELECT membro, lib, chave_canonica, path, etapa AS etapa_antes, status AS status_antes,
       observacao AS observacao_antes, escopo_indi, qtd_projetos, n_no_grupo,
       row_number() OVER (PARTITION BY membro
           ORDER BY peso_etapa DESC, qtd_projetos DESC,
                    CASE WHEN escopo_indi THEN 0 ELSE 1 END, lib) AS rk,
       first_value(lib) OVER (PARTITION BY membro
           ORDER BY peso_etapa DESC, qtd_projetos DESC,
                    CASE WHEN escopo_indi THEN 0 ELSE 1 END, lib) AS lib_canonica
FROM grupo
WHERE n_resolvidas = 0;   -- só grupos em que ninguém foi resolvido ainda


-- ----------------------------------------------------------------------------
-- BLOCO 1 — pré-checks (LEITURA). Não siga se algum destes não bater.
-- ----------------------------------------------------------------------------
-- Esperado: 63 grupos · 135 linhas · 63 canônicas · 72 redundantes
SELECT count(DISTINCT membro) AS grupos, count(*) AS linhas,
       sum(CASE WHEN rk = 1 THEN 1 ELSE 0 END) AS canonicas,
       sum(CASE WHEN rk > 1 THEN 1 ELSE 0 END) AS redundantes
FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map;

-- Esperado: 72 / 0 / 0 / 5. Se "com_obs" ou "com_resp" der > 0, alguém editou
-- desde o levantamento — PARE e reveja, porque o bloco 2 sobrescreve observação.
SELECT count(*) AS redundantes,
       sum(CASE WHEN trim(coalesce(observacao_antes, '')) <> '' THEN 1 ELSE 0 END) AS com_obs,
       sum(CASE WHEN etapa_antes <> 'A Receber' OR status_antes <> 'A Iniciar'
                THEN 1 ELSE 0 END)                                                 AS estado_nao_default,
       sum(CASE WHEN escopo_indi THEN 1 ELSE 0 END)                                AS no_escopo
FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map
WHERE rk > 1;

-- Conferência visual: um canônico por grupo, e o canônico nunca é redundante.
SELECT membro, lib_canonica,
       concat_ws(', ', sort_array(collect_list(CASE WHEN rk > 1 THEN lib END))) AS redundantes,
       max(qtd_projetos) AS max_egps, any_value(path) AS path
FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map
GROUP BY membro, lib_canonica
ORDER BY max_egps DESC, membro
LIMIT 20;


-- ----------------------------------------------------------------------------
-- BLOCO 2 — marca as redundantes (ESCRITA)
-- ----------------------------------------------------------------------------
-- Guarda: só linhas ainda intocadas. Se alguém assumiu a linha entre o
-- levantamento e a execução, o MERGE não a toca.

MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
USING (
    SELECT chave_canonica, membro, lib, lib_canonica, path
    FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map
    WHERE rk > 1
) AS m
ON t.chave_canonica = m.chave_canonica
   AND t.etapa = 'A Receber' AND t.status = 'A Iniciar'
   AND t.responsavel IS NULL
   AND trim(coalesce(t.observacao, '')) = ''
WHEN MATCHED THEN UPDATE SET
    t.etapa      = 'Modernizado',
    t.status     = 'Sanitizado',
    t.observacao = concat(
        'Alias redundante de libname: mesma tabela física que ',
        m.lib_canonica, '.', m.membro, ' (path ', m.path, '). ',
        'A ingestão entra pela chave canônica, e esta linha não gera ingestão própria. ',
        'Consolidação de homônimos por libname, 23/09/2026 — critério e lista completa em ',
        'docs/analises/consolidacao_libname_2026-09-23.sql.'),
    t.updated_by = 'lucas.muller@indicium.ai',
    t.updated_at = current_timestamp();


-- ----------------------------------------------------------------------------
-- BLOCO 3 — verificação (LEITURA)
-- ----------------------------------------------------------------------------
-- Esperado: 72 redundantes agora em Modernizado/Sanitizado, 0 sobrando.
SELECT sum(CASE WHEN i.etapa = 'Modernizado' AND i.status = 'Sanitizado' THEN 1 ELSE 0 END) AS consolidadas,
       sum(CASE WHEN i.etapa = 'A Receber' THEN 1 ELSE 0 END)                               AS ainda_na_fila
FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map m
JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor i ON i.chave_canonica = m.chave_canonica
WHERE m.rk > 1;

-- Esperado: as 63 canônicas seguem intactas na fila.
SELECT i.etapa, i.status, count(*) AS n
FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map m
JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor i ON i.chave_canonica = m.chave_canonica
WHERE m.rk = 1
GROUP BY i.etapa, i.status ORDER BY n DESC;


-- ----------------------------------------------------------------------------
-- DESFAZER
-- ----------------------------------------------------------------------------
--   MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
--   USING bv_dev_db.monitoramento_sas._consolid_libname_20260923_map AS m
--     ON t.chave_canonica = m.chave_canonica AND m.rk > 1
--   WHEN MATCHED THEN UPDATE SET
--       t.etapa = m.etapa_antes, t.status = m.status_antes,
--       t.observacao = m.observacao_antes;
--
-- O mapa é o desfazer — não drope antes de o resultado estar conferido.
-- ============================================================================


-- ============================================================================
-- O QUE ESTE SCRIPT NÃO FAZ
-- ============================================================================
-- 1. Não colapsa nem apaga linha nenhuma. CLAUDE.md é explícito: identidade física
--    entra como coluna aditiva (paths_fisicos), nunca colapsando homônimos, porque
--    colapsar destrói status digitado por analista.
-- 2. Não toca no balde B (92 grupos, paths distintos). DIAS_UTEIS aparece em 6
--    libnames e 6 diretórios: são seis calendários diferentes, um por analista.
-- 3. Não toca nos 72 grupos do balde C — falta o path para decidir. O path vem do
--    resolvedor de libname e fica vazio quando o LIBNAME é declarado fora do EGP ou
--    montado por macro. Resolver isso é trabalho no extractor, não aqui.
-- 4. Não mexe nos 15 grupos mistos nem nos 7 já resolvidos: o time já consolidou
--    esses à mão, e na direção certa.

-- ============================================================================
-- Unificação de estado entre aliases da MESMA tabela física — 23/09/2026
-- ============================================================================
-- POR QUE ESTE SCRIPT EXISTE (e substitui o consolidacao_libname_2026-09-23.sql)
--   O script de consolidação rodado mais cedo hoje marcou 72 aliases redundantes
--   como 'Modernizado / Sanitizado'. Isso resolveu a contagem dupla da fila e
--   QUEBROU a prontidão: o EGP que lê o alias redundante passou a contar aquele
--   input como resolvido, enquanto a tabela física continua pendente pelo
--   canônico. Medido depois: 78 grupos divergentes, 128 EGPs com prontidão
--   inflada, 172 pares (EGP, input). Só TBSIMULACOES/INFCVS infla 30 EGPs.
--
--   O mesmo defeito já existia em 20 linhas sanitizadas à mão entre jul e set
--   (17 da Morgana/Francielly, 3 do Lucas em 23/09) — sempre o alias com MENOS
--   EGPs sanitizado enquanto o gêmeo físico, com mais, segue pendente.
--
-- O PRINCÍPIO
--   Estado segue a TABELA FÍSICA, não o alias. Todos os aliases que apontam para
--   o mesmo path têm de exibir o mesmo etapa/status. Um EGP não pode ver "pronto"
--   só porque escreveu o libname com outro nome.
--
-- A REGRA
--   Peso de progresso REAL de ingestão por alias:
--     Modernizado 6 · Ingestão PRD 5 · Ingestão UAT 4 · Aplicação de Grant 3
--     Pré-Working 2 · Recebido 1 · A Receber 0
--     Sanitizado = 0 SEMPRE. Sanitizado é decisão de descarte, não progresso, e
--     por isso nunca vence de um alias que está de fato sendo ingerido.
--
--   Se algum alias do grupo tem peso > 0  -> todos recebem o estado DELE.
--   Se nenhum tem                         -> todos voltam a 'A Receber / A Iniciar'.
--
-- ESCOPO
--   Só o balde A (mesmo membro, path físico conhecido e idêntico em todas as
--   linhas). Balde B (paths distintos) e C (path ausente) ficam de fora — ver
--   docs/analises/inputs_homonimos_libname_2026-09-23.csv.
--
-- O QUE ISTO CUSTA (explícito)
--   88 linhas voltam para a fila, 1 sai. A contagem dupla da fila VOLTA: a mesma
--   tabela física passa a ser contada uma vez por alias. É o preço de a prontidão
--   dizer a verdade. A correção certa para a contagem é uma CAMADA DE CONTAGEM por
--   path físico, no backend, como FAMILIAS_SAFRA faz para safras — não um status
--   que mente sobre o estado. Isso é mudança de código, não de dado.
--
--   Alvo: bv_dev_db.monitoramento_sas  (PROD)
--
-- EXECUTADO EM PROD — 23/09/2026, por lucas.muller@indicium.ai
--   bloco 0  _unif_libname_20260923_map criada (85 grupos, 186 linhas)
--   bloco 1  devolver_para_pendente 71 grupos/81 a mudar · alinhar_ao_progresso 14/14
--            volta_para_fila 88 · sai_da_fila 1 · alvo ambiguo 0
--            20 decisoes de outras pessoas sobrescritas (17 Morgana/Francielly, 3 Lucas)
--   bloco 2  95 linhas atualizadas
--   bloco 3  grupos_ainda_divergentes = 0
--   medido depois: EGPs com prontidao inflada 128 -> 0 (pares 172 -> 0)
--   fila viva: A Receber 7.730 -> 7.807
-- ============================================================================


-- ----------------------------------------------------------------------------
-- BLOCO 0 — mapa do alvo por grupo (fonte do MERGE e desfazer)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE TABLE bv_dev_db.monitoramento_sas._unif_libname_20260923_map AS
WITH base AS (
    SELECT chave_canonica,
           split_part(upper(artifact), '.', 1)               AS lib,
           split_part(upper(artifact), '.', 2)               AS membro,
           nullif(trim(coalesce(paths_fisicos, '')), '')     AS path,
           n_paths_fisicos, etapa, status, observacao, responsavel, qtd_projetos,
           CASE WHEN trim(coalesce(etapa, '')) <> '' THEN etapa
                WHEN modernizada_auto = 'Disponível'  THEN 'Modernizado'
                ELSE 'A Receber' END                          AS et_eff,
           CASE WHEN trim(coalesce(status, '')) <> '' THEN status
                WHEN (CASE WHEN trim(coalesce(etapa, '')) <> '' THEN etapa
                           WHEN modernizada_auto = 'Disponível' THEN 'Modernizado'
                           ELSE 'A Receber' END) = 'Modernizado' THEN 'Concluído'
                ELSE 'A Iniciar' END                          AS st_eff
    FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor
    WHERE orfao = false
      AND categoria = 'tabela'
      AND origem IN ('SAS/Local (externo)', 'SAS/Local (dependência)')
      AND length(artifact) - length(replace(artifact, '.', '')) = 1
),
com_peso AS (
    SELECT *, CASE WHEN st_eff = 'Sanitizado'          THEN 0
                   WHEN et_eff = 'Modernizado'         THEN 6
                   WHEN et_eff = 'Ingestão PRD'        THEN 5
                   WHEN et_eff = 'Ingestão UAT'        THEN 4
                   WHEN et_eff = 'Aplicação de Grant'  THEN 3
                   WHEN et_eff = 'Pré-Working'         THEN 2
                   WHEN et_eff = 'Recebido'            THEN 1
                   ELSE 0 END AS peso
    FROM base
),
balde_a AS (
    SELECT membro FROM com_peso
    GROUP BY membro
    HAVING count(DISTINCT lib) > 1
       AND count(path) = count(*)
       AND count(DISTINCT path) = 1
       AND max(n_paths_fisicos) <= 1
),
r AS (SELECT c.* FROM com_peso c JOIN balde_a a USING (membro)),
g AS (SELECT membro, max(peso) AS peso_max FROM r GROUP BY membro),
-- alias que define a verdade do grupo (só quando existe progresso real)
alvo AS (
    SELECT membro, lib AS lib_alvo, et_eff AS et_alvo, st_eff AS st_alvo
    FROM (SELECT r.*, row_number() OVER (PARTITION BY r.membro
              ORDER BY r.peso DESC, r.qtd_projetos DESC, r.lib) AS rk
          FROM r JOIN g USING (membro) WHERE g.peso_max > 0)
    WHERE rk = 1
)
SELECT r.chave_canonica, r.membro, r.lib, r.path, r.qtd_projetos,
       r.etapa       AS etapa_antes,
       r.status      AS status_antes,
       r.observacao  AS observacao_antes,
       r.et_eff, r.st_eff, g.peso_max,
       CASE WHEN g.peso_max > 0 THEN 'alinhar_ao_progresso'
            ELSE 'devolver_para_pendente' END                  AS regra,
       coalesce(a.lib_alvo, r.lib)         AS lib_alvo,
       coalesce(a.et_alvo, 'A Receber')    AS etapa_alvo,
       coalesce(a.st_alvo, 'A Iniciar')    AS status_alvo
FROM r JOIN g USING (membro) LEFT JOIN alvo a USING (membro);


-- ----------------------------------------------------------------------------
-- BLOCO 1 — pré-checks (LEITURA)
-- ----------------------------------------------------------------------------
-- Esperado: alinhar_ao_progresso 14 grupos / 14 linhas a mudar
--           devolver_para_pendente 71 grupos / 81 linhas a mudar
SELECT regra, count(DISTINCT membro) AS grupos, count(*) AS linhas,
       sum(CASE WHEN et_eff <> etapa_alvo OR st_eff <> status_alvo THEN 1 ELSE 0 END) AS a_mudar
FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map
GROUP BY regra ORDER BY grupos DESC;

-- Esperado: volta_para_fila 88 · sai_da_fila 1
SELECT sum(CASE WHEN (st_eff = 'Sanitizado' OR et_eff = 'Modernizado')
                 AND NOT (status_alvo = 'Sanitizado' OR etapa_alvo = 'Modernizado')
                THEN 1 ELSE 0 END) AS volta_para_fila,
       sum(CASE WHEN NOT (st_eff = 'Sanitizado' OR et_eff = 'Modernizado')
                 AND (status_alvo = 'Sanitizado' OR etapa_alvo = 'Modernizado')
                THEN 1 ELSE 0 END) AS sai_da_fila
FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map;

-- Nenhum grupo pode ficar com dois alvos distintos. Esperado: 0.
SELECT count(*) AS grupos_com_alvo_ambiguo FROM (
    SELECT membro FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map
    GROUP BY membro HAVING count(DISTINCT concat(etapa_alvo, '|', status_alvo)) > 1);

-- Decisões de OUTRAS pessoas que este script sobrescreve — leia antes de rodar.
SELECT m.membro, m.lib, m.etapa_antes, m.status_antes, m.etapa_alvo, m.status_alvo,
       i.updated_by, m.qtd_projetos
FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map m
JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor i USING (chave_canonica)
WHERE m.st_eff = 'Sanitizado'
  AND m.chave_canonica NOT IN (
      SELECT chave_canonica FROM bv_dev_db.monitoramento_sas._consolid_libname_20260923_map WHERE rk > 1)
ORDER BY m.membro, m.lib;


-- ----------------------------------------------------------------------------
-- BLOCO 2 — unifica o estado (ESCRITA)
-- ----------------------------------------------------------------------------

MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
USING (
    SELECT chave_canonica, membro, lib, lib_alvo, path, regra, etapa_alvo, status_alvo
    FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map
    WHERE et_eff <> etapa_alvo OR st_eff <> status_alvo
) AS m
ON t.chave_canonica = m.chave_canonica
WHEN MATCHED THEN UPDATE SET
    t.etapa      = m.etapa_alvo,
    t.status     = m.status_alvo,
    t.observacao = concat(
        'Estado unificado por tabela física (path ', m.path, '): os aliases ',
        'de libname deste membro compartilham o mesmo arquivo, então exibem o ',
        'mesmo estado. Referência do grupo: ', m.lib_alvo, '.', m.membro,
        CASE WHEN m.regra = 'alinhar_ao_progresso'
             THEN ', que está em ingestão.'
             ELSE ', ainda pendente — nenhum alias do grupo tem ingestão em andamento.' END,
        ' Unificação de 23/09/2026, critério em docs/analises/unificacao_estado_libname_2026-09-23.sql.'),
    t.updated_by = 'lucas.muller@indicium.ai',
    t.updated_at = current_timestamp();


-- ----------------------------------------------------------------------------
-- BLOCO 3 — verificação (LEITURA)
-- ----------------------------------------------------------------------------
-- Esperado: 0. Nenhum grupo do balde A pode ter alias resolvido e alias pendente.
WITH est AS (
    SELECT m.membro,
           (i.etapa = 'Modernizado' OR i.status IN ('Sanitizado', 'Autoprodutor')) AS resolvido
    FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map m
    JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor i USING (chave_canonica))
SELECT count(*) AS grupos_ainda_divergentes FROM (
    SELECT membro FROM est GROUP BY membro
    HAVING count(DISTINCT resolvido) > 1);

-- Estado final por grupo, para conferência.
SELECT i.etapa, i.status, count(*) AS n
FROM bv_dev_db.monitoramento_sas._unif_libname_20260923_map m
JOIN bv_dev_db.monitoramento_sas.sas_inputs_monitor i USING (chave_canonica)
GROUP BY i.etapa, i.status ORDER BY n DESC;


-- ----------------------------------------------------------------------------
-- DESFAZER
-- ----------------------------------------------------------------------------
--   MERGE INTO bv_dev_db.monitoramento_sas.sas_inputs_monitor AS t
--   USING bv_dev_db.monitoramento_sas._unif_libname_20260923_map AS m
--     ON t.chave_canonica = m.chave_canonica
--   WHEN MATCHED THEN UPDATE SET
--       t.etapa = m.etapa_antes, t.status = m.status_antes,
--       t.observacao = m.observacao_antes;
--
-- Isto devolve ao estado imediatamente ANTES desta unificação, que já inclui a
-- consolidação de mais cedo. Para voltar ao estado de antes das duas, use depois
-- o desfazer do _consolid_libname_20260923_map.
-- ============================================================================


-- ============================================================================
-- PENDENTE DEPOIS DISTO
-- ============================================================================
-- A contagem dupla da fila volta e fica: 101 linhas a mais do que tabelas físicas
-- no balde A. Resolver isso com status é o que acabou de dar errado. O caminho é
-- uma camada de contagem por path físico no backend, espelhando o que
-- backend/familias.py faz para safras: o grafo e a linhagem continuam por alias,
-- e só a CONTAGEM colapsa. Ver docs/adr/0002 para o precedente.

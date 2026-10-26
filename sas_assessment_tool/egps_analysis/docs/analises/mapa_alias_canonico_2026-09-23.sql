-- ============================================================================
-- Mapa alias -> canônico para tabelas homônimas por libname — 23/09/2026
-- ============================================================================
-- O QUE É
--   Uma tabela de DECISÃO, fora do publish, dizendo qual alias de libname é o
--   canônico de cada tabela física. É o insumo para unificar N linhas de
--   sas_inputs_monitor em 1 input por arquivo.
--
-- POR QUE UMA TABELA, E NÃO UM PATCH DE DADO
--   sas_inputs_monitor é reconstruída pelo publish a partir do corpus, com chave
--   tabela::LIB.MEMBRO. Apagar ou fundir linhas lá dura até o próximo publish do
--   Eduardo — é o mesmo formato do rename do CPF_Contrato, que reverte a cada
--   Processar e precisa de script de reaplicação. Uma tabela própria sobrevive,
--   como sas_gestao_status/_datas, que o publish nunca dropa.
--
-- ESTADO: INERTE. Nada lê esta tabela ainda. Criá-la não muda número nenhum no
--   app. Ela só passa a valer quando o backend colapsar a CONTAGEM por
--   chave_canonica_alvo — nos moldes de backend/familias.py para safras (ADR 0002),
--   onde o grafo continua no grão fino e só a contagem agrupa.
--
--   Decisão: docs/adr/0003-alias-de-libname-como-unidade-de-input.md (raiz do repo)
--   Plano e tickets: egps_analysis/app/docs/superpowers/plans/2026-09-23-alias-de-libname.md
--
-- ESCOPO DA CARGA INICIAL
--   Só o balde A: mesmo membro, path físico conhecido e idêntico em todas as
--   linhas (85 grupos, 186 linhas -> 85 inputs, 101 absorvidas). Balde B (paths
--   distintos = tabelas diferentes) e C (path ausente) ficam FORA de propósito.
--
-- REGRA DA PROPOSTA (origem_decisao = 'proposta_automatica')
--   canônico = mais EGPs consumidores -> etapa mais avançada -> dentro do escopo
--   Indicium -> nome do libname como desempate. Revisão humana entra por
--   docs/analises/unificacao_escolha_alias_2026-09-23.csv (coluna alias_escolhido)
--   e vira origem_decisao = 'revisao_humana'.
--
--   Alvo: bv_dev_db.monitoramento_sas  (PROD)
--
-- EXECUTADO EM PROD — 23/09/2026, por lucas.muller@indicium.ai
--   bloco 0  sas_input_alias_canonico criada
--   bloco 1  186 linhas inseridas (0 atualizadas)
--   bloco 2  186 linhas · 85 grupos · 85 canonicas · 101 absorvidas
--            invariantes: um-canonico-por-grupo 0 · alvo-nao-canonico 0
--                         cadeia-de-dois-saltos 0 · sem-path 0
--            contagem se o app colapsasse: 10.087 vs 10.188 hoje (-101)
--   TABELA INERTE: nada a le ainda, nenhum numero do app mudou.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- BLOCO 0 — DDL (fora do publish; nunca dropar no Processar)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_input_alias_canonico (
    chave_canonica       STRING NOT NULL,   -- a linha do monitor (alias)
    chave_canonica_alvo  STRING,            -- canônico do grupo (auto-referência p/ o próprio)
    membro               STRING,            -- nome da tabela sem o libname
    lib                  STRING,
    lib_canonica         STRING,
    path_fisico          STRING,            -- o que define o grupo
    n_egps               INT,               -- consumidores deste alias na carga
    eh_canonico          BOOLEAN,
    origem_decisao       STRING,            -- proposta_automatica | revisao_humana
    motivo               STRING,
    ativo                BOOLEAN,           -- desligar um grupo sem apagar a linha
    updated_by           STRING,
    updated_at           TIMESTAMP
) USING DELTA;


-- ----------------------------------------------------------------------------
-- BLOCO 1 — carga da proposta (ESCRITA, idempotente por chave_canonica)
-- ----------------------------------------------------------------------------
-- MERGE, não INSERT: re-rodar não duplica, e linhas já revisadas por humano
-- (origem_decisao = 'revisao_humana') NÃO são sobrescritas pela proposta.

MERGE INTO bv_dev_db.monitoramento_sas.sas_input_alias_canonico AS t
USING (
    WITH base AS (
        SELECT chave_canonica,
               split_part(upper(artifact), '.', 1)            AS lib,
               split_part(upper(artifact), '.', 2)            AS membro,
               nullif(trim(coalesce(paths_fisicos, '')), '')  AS path,
               n_paths_fisicos, escopo_indi,
               CASE WHEN trim(coalesce(etapa, '')) <> '' THEN etapa
                    WHEN modernizada_auto = 'Disponível'  THEN 'Modernizado'
                    ELSE 'A Receber' END                       AS et_eff
        FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor
        WHERE orfao = false
          AND categoria = 'tabela'
          AND origem IN ('SAS/Local (externo)', 'SAS/Local (dependência)')
          AND length(artifact) - length(replace(artifact, '.', '')) = 1
    ),
    balde_a AS (
        SELECT membro FROM base
        GROUP BY membro
        HAVING count(DISTINCT lib) > 1
           AND count(path) = count(*)
           AND count(DISTINCT path) = 1
           AND max(n_paths_fisicos) <= 1
    ),
    -- consumidores REAIS por alias (sas_egp_inputs), não o qtd_projetos do monitor
    r AS (
        SELECT b.*,
               (SELECT count(DISTINCT e.projeto)
                  FROM bv_dev_db.monitoramento_sas.sas_egp_inputs e
                 WHERE e.chave_canonica = b.chave_canonica) AS n_egps
        FROM base b JOIN balde_a a USING (membro)
    ),
    ranqueado AS (
        SELECT r.*, row_number() OVER (PARTITION BY membro
            ORDER BY n_egps DESC,
                     CASE et_eff WHEN 'Modernizado'        THEN 6
                                 WHEN 'Ingestão PRD'       THEN 5
                                 WHEN 'Ingestão UAT'       THEN 4
                                 WHEN 'Aplicação de Grant' THEN 3
                                 WHEN 'Pré-Working'        THEN 2
                                 WHEN 'Recebido'           THEN 1
                                 ELSE 0 END DESC,
                     CASE WHEN escopo_indi THEN 0 ELSE 1 END,
                     lib) AS rk
        FROM r
    ),
    canon AS (
        SELECT membro, lib AS lib_canonica, chave_canonica AS chave_alvo
        FROM ranqueado WHERE rk = 1
    )
    SELECT q.chave_canonica, c.chave_alvo AS chave_canonica_alvo, q.membro, q.lib,
           c.lib_canonica, q.path AS path_fisico, q.n_egps,
           (q.rk = 1)                       AS eh_canonico,
           'proposta_automatica'            AS origem_decisao,
           concat(cast(q.n_egps AS string), ' EGP(s) neste alias. Canônico por ',
                  'mais consumidores, depois etapa mais avançada, depois escopo.') AS motivo
    FROM ranqueado q JOIN canon c USING (membro)
) AS m
ON t.chave_canonica = m.chave_canonica
WHEN MATCHED AND t.origem_decisao <> 'revisao_humana' THEN UPDATE SET
    t.chave_canonica_alvo = m.chave_canonica_alvo,
    t.membro = m.membro, t.lib = m.lib, t.lib_canonica = m.lib_canonica,
    t.path_fisico = m.path_fisico, t.n_egps = m.n_egps,
    t.eh_canonico = m.eh_canonico, t.motivo = m.motivo,
    t.updated_by = 'lucas.muller@indicium.ai', t.updated_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (
    chave_canonica, chave_canonica_alvo, membro, lib, lib_canonica, path_fisico,
    n_egps, eh_canonico, origem_decisao, motivo, ativo, updated_by, updated_at
) VALUES (
    m.chave_canonica, m.chave_canonica_alvo, m.membro, m.lib, m.lib_canonica,
    m.path_fisico, m.n_egps, m.eh_canonico, m.origem_decisao, m.motivo, true,
    'lucas.muller@indicium.ai', current_timestamp()
);


-- ----------------------------------------------------------------------------
-- BLOCO 2 — verificação (LEITURA)
-- ----------------------------------------------------------------------------
-- Esperado: 186 linhas · 85 grupos · 85 canônicas · 101 absorvidas
SELECT count(*) AS linhas, count(DISTINCT membro) AS grupos,
       sum(CASE WHEN eh_canonico THEN 1 ELSE 0 END)     AS canonicas,
       sum(CASE WHEN NOT eh_canonico THEN 1 ELSE 0 END) AS absorvidas
FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico WHERE ativo;

-- Invariantes. Todos têm de dar 0.
SELECT
  (SELECT count(*) FROM (SELECT membro FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico
     WHERE ativo GROUP BY membro HAVING sum(CASE WHEN eh_canonico THEN 1 ELSE 0 END) <> 1))
     AS grupos_sem_exatamente_um_canonico,
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico a
     WHERE ativo AND NOT EXISTS (SELECT 1 FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico b
       WHERE b.chave_canonica = a.chave_canonica_alvo AND b.eh_canonico))
     AS alvo_que_nao_e_canonico,
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico a
     JOIN bv_dev_db.monitoramento_sas.sas_input_alias_canonico b
       ON a.chave_canonica_alvo = b.chave_canonica
     WHERE a.ativo AND b.ativo AND NOT b.eh_canonico)
     AS cadeia_de_dois_saltos,
  (SELECT count(*) FROM bv_dev_db.monitoramento_sas.sas_input_alias_canonico
     WHERE ativo AND (path_fisico IS NULL OR trim(path_fisico) = ''))
     AS sem_path;

-- Como ficaria a contagem se o app colapsasse por chave_canonica_alvo.
SELECT count(DISTINCT coalesce(a.chave_canonica_alvo, i.chave_canonica)) AS inputs_colapsados,
       count(*) AS linhas_hoje
FROM bv_dev_db.monitoramento_sas.sas_inputs_monitor i
LEFT JOIN bv_dev_db.monitoramento_sas.sas_input_alias_canonico a
       ON a.chave_canonica = i.chave_canonica AND a.ativo
WHERE i.orfao = false;


-- ----------------------------------------------------------------------------
-- COMO APLICAR A REVISÃO HUMANA
-- ----------------------------------------------------------------------------
-- Editar alias_escolhido em docs/analises/unificacao_escolha_alias_2026-09-23.csv
-- e, para cada grupo alterado:
--
--   UPDATE bv_dev_db.monitoramento_sas.sas_input_alias_canonico
--      SET eh_canonico = (lib = '<ALIAS_ESCOLHIDO>'),
--          chave_canonica_alvo = 'tabela::<ALIAS_ESCOLHIDO>.<MEMBRO>',
--          lib_canonica = '<ALIAS_ESCOLHIDO>',
--          origem_decisao = 'revisao_humana',
--          motivo = '<por que>',
--          updated_by = '<voce>', updated_at = current_timestamp()
--    WHERE membro = '<MEMBRO>' AND ativo;
--
-- O MERGE do bloco 1 respeita origem_decisao = 'revisao_humana' e não
-- sobrescreve. Para tirar um grupo da unificação sem apagar o registro da
-- análise: UPDATE ... SET ativo = false WHERE membro = '<MEMBRO>'.
-- ============================================================================


-- ============================================================================
-- O QUE FALTA PARA ISTO VALER DE FATO
-- ============================================================================
-- 1. Backend colapsar a contagem por chave_canonica_alvo nas superfícies de
--    universo e de fila (Resumo, Inputs, prontidão por EGP, ondas), do mesmo
--    jeito que backend/familias.py faz para safras. O grafo e a linhagem
--    continuam por alias — só a contagem agrupa.
-- 2. Escrita com fan-out: editar o input colapsado tem de gravar nas N linhas,
--    com auditoria por linha (mesmo desenho das famílias de safra).
-- 3. publish_to_databricks nunca dropar nem reescrever esta tabela.
-- 4. Decidir o que a UI mostra como nome do input colapsado (o canônico) e como
--    expõe os aliases absorvidos (provável: lista no drawer, como paths_fisicos).
-- ============================================================================

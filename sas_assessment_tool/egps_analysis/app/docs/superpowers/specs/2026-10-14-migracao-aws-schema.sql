-- =============================================================================
-- monitoramento-sas — PROPOSTA de schema para PostgreSQL 17   (RASCUNHO, NÃO APLICAR)
-- =============================================================================
-- Vocabulário: CONTEXT.md (EGP, Input, Família de safras, Safra, Vínculo, Antecessor,
-- Sucessor, Pipeline, Escopo, Linha de base, Extra, Casca, Responsável BV, Sub-área BV,
-- Papel, Versão recebida, Profundidade necessária/ingerida, Mês do plano).
--
-- CAMADAS (um schema por dono/ciclo de vida):
--   cadastro    registros e vocabulários, editados por gestão/admin; raramente mudam
--   corpus      publicado pelo pipeline. Dono único: o publish (fase 1: o sync).
--                 * ÂNCORAS (egp, input, output): UPSERT + flag `orfao`; NUNCA apagadas.
--                 * FATOS DERIVADOS (egp_input, egp_output, aresta_linhagem, resumo_*):
--                   DELETE + COPY na MESMA transação do publish (não TRUNCATE: não é
--                   MVCC-safe e pega ACCESS EXCLUSIVE).
--   trabalho    estado humano durável. FK SÓ para âncoras do corpus — nunca para um
--               fato substituível. Par (EGP, input) referencia as duas âncoras, não o par.
--   historico   append-only: evento (auditoria única), publicação, métricas.
--   atualizados versões recebidas (script local; ADR 0001 — isolamento de ESCRITA).
--   derivado    views (nunca escrever). Substituem flags hoje copiadas em 4 tabelas.
--   compat      (só fase 1) views com o nome/forma das tabelas Delta antigas, para o app
--               trocar de DIALETO antes de trocar de MODELO. Some na fase 2.
--
-- CONVENÇÕES
--   * Chaves naturais em text como PK (projeto, chave do input, chave do output): são as
--     que URL /egps/<id>, auditoria, CSVs e scripts já usam. FKs com ON UPDATE CASCADE
--     para que um re-key (CPF_Contrato, [SHEET=]) seja UM UPDATE na âncora, não N scripts.
--   * FKs DEFERRABLE INITIALLY IMMEDIATE: o app vê checagem imediata; publish/sync podem
--     `SET CONSTRAINTS ALL DEFERRED` dentro da transação de carga.
--   * ON DELETE: padrão (NO ACTION). Âncora não se apaga; se alguém tentar, falha alto.
--   * Datas de negócio = date; instantes = timestamptz (sessão do app em TimeZone=UTC;
--     conversão p/ São Paulo continua NA EXIBIÇÃO — README §Timestamps).
--   * Ator: o app faz `SELECT set_config('app.usuario', <email>, true)` (= SET LOCAL) em
--     toda transação de escrita; defaults e triggers leem daí (substitui current_user()).
--
-- PUBLISH (fase 2) — tudo numa transação; leitor vê o corpus velho até o COMMIT:
--   1. INSERT historico.publicacao (autocommit à parte, p/ registrar também a falha)
--   2. COPY do build para tabelas TEMP
--   3. aplica trabalho.egp_decisao_identidade (renomear/remover) sobre o TEMP
--   4. MERGE nas âncoras corpus.egp/input/output
--        WHEN MATCHED -> atualiza só colunas do corpus, orfao=false
--        WHEN NOT MATCHED BY TARGET -> insere
--        WHEN NOT MATCHED BY SOURCE -> orfao=true          (nunca DELETE)
--   5. DELETE + INSERT dos fatos (egp_input, egp_output, aresta_linhagem, resumo_*)
--   6. reaplica trabalho.input_alias_canonico (reponta egp_input, resumo_egp_input e
--      leitura_dispensada; alias vira orfao=true) com as duas recusas de
--      identidade_reaplica.py — e a recusa "alias tem estado humano" passa a olhar TODA
--      tabela de trabalho que referencia a âncora (lista vem de pg_constraint), não só as
--      4 colunas do monitor (hoje 13 comentários da Gestão ficaram em aliases colapsados)
--   7. guardas (identidade_guard + contagem de derivado.v_trabalho_orfao) -> se falhar,
--      ROLLBACK (hoje: "concluiu a escrita, mas..." + exit 1 com o dado já trocado)
--   8. COMMIT; UPDATE historico.publicacao SET ok/resumo
-- =============================================================================

BEGIN;

CREATE SCHEMA cadastro;
CREATE SCHEMA corpus;
CREATE SCHEMA trabalho;
CREATE SCHEMA historico;
CREATE SCHEMA atualizados;
CREATE SCHEMA derivado;
CREATE SCHEMA compat;

-- -----------------------------------------------------------------------------
-- Ator e carimbo de atualização
-- -----------------------------------------------------------------------------
CREATE FUNCTION cadastro.usuario_atual() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('app.usuario', true), ''), session_user::text)
$$;

CREATE FUNCTION cadastro.carimba() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.atualizado_em  := now();
  NEW.atualizado_por := cadastro.usuario_atual();
  RETURN NEW;
END $$;

-- =============================================================================
-- CADASTRO
-- =============================================================================

-- Pessoas que usam o app. "papel" = leitor | gestao | admin (CONTEXT.md §Papel), cada um
-- incluindo o anterior. Quem não tem linha é leitor. O antigo sas_analistas.papel ('DE',
-- 'Tech Lead'...) é CARGO — renomeado para não colidir com o termo do glossário.
CREATE TABLE cadastro.usuario (
  email          text PRIMARY KEY CHECK (email = lower(btrim(email)) AND email LIKE '%_@_%'),
  nome           text NOT NULL,
  papel          text NOT NULL DEFAULT 'leitor' CHECK (papel IN ('leitor', 'gestao', 'admin')),
  cargo          text,
  organograma    boolean NOT NULL DEFAULT false,
  ativo          boolean NOT NULL DEFAULT true,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  criado_por     text NOT NULL DEFAULT cadastro.usuario_atual(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON cadastro.usuario FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Responsável BV -> Sub-área BV (atributo da PESSOA, herdado pelo EGP).
-- nome_chave = _norm_nome_bv(nome) (main.py), regra replicada em subareas.ts e no seed.
CREATE TABLE cadastro.responsavel_bv (
  nome_chave     text PRIMARY KEY CHECK (nome_chave <> ''),
  nome           text NOT NULL,
  subarea        text CHECK (subarea IN ('Digital', 'MIS', 'Operações',
                                         'Estratégia - cartões', 'Estratégia - rodas', 'Riscos')),
  ativo          boolean NOT NULL DEFAULT true,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  criado_por     text NOT NULL DEFAULT cadastro.usuario_atual(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON cadastro.responsavel_bv FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Vocabulários de etapa/status: tabela de consulta com a PRÓPRIA etiqueta como PK.
-- Não precisa de JOIN para exibir; a FK só valida, e ON UPDATE CASCADE torna o rename
-- (scripts/rename_migracao_etapas.py) um UPDATE só. Ordem e atributos (fantasma, banda)
-- deixam de existir só em Python + pipeline.ts. As listas de main.py continuam sendo a
-- régua; um teste de paridade compara as duas (molde de test_familias.py).
CREATE TABLE cadastro.etapa_migracao (
  etapa        text PRIMARY KEY,
  ordem        smallint UNIQUE,              -- posição no funil; NULL = etapa fantasma
  fantasma_tom text CHECK (fantasma_tom IN ('wip', 'mut')),
  CHECK ((ordem IS NULL) = (fantasma_tom IS NOT NULL))
);
INSERT INTO cadastro.etapa_migracao VALUES
  ('Projetos Habilitados', 1, NULL), ('Pré-Working + Outputs', 2, NULL),
  ('Conversão do Código', 3, NULL), ('Validação em DES', 4, NULL),
  ('Aprv. PR + Validação Governança', 5, NULL), ('Implant. em PRD', 6, NULL),
  ('Aplicação de Grant', 7, NULL), ('Validação da Área', 8, NULL), ('Migrado', 9, NULL),
  ('Pré-conversão', NULL, 'wip'), ('Conversão pela Área', NULL, 'mut');

-- 'Desatualizado' NÃO entra: é derivado do vínculo e nunca gravado (CONTEXT.md).
CREATE TABLE cadastro.status_migracao (
  status      text PRIMARY KEY,
  banda       boolean NOT NULL DEFAULT false,   -- reflete em todas as colunas do funil
  conta_tempo boolean NOT NULL DEFAULT true     -- 'Em espera' fica fora das métricas de tempo
);
INSERT INTO cadastro.status_migracao VALUES
  ('A Iniciar', false, true), ('Em Andamento', false, true), ('Em espera', false, false),
  ('Concluído', false, true), ('Block', false, true),
  ('Despriorizado e Contabilizado', true, true), ('Migrado', false, true);

CREATE TABLE cadastro.etapa_ingestao (
  etapa text PRIMARY KEY,
  ordem smallint NOT NULL UNIQUE
);
INSERT INTO cadastro.etapa_ingestao VALUES
  ('A Receber', 1), ('Recebido', 2), ('Pré-Working', 3), ('Ingestão UAT', 4),
  ('PDI + GMUD', 5), ('Ingestão PRD', 6), ('Aplicação de Grant', 7), ('Modernizado', 8);

CREATE TABLE cadastro.status_input (
  status   text PRIMARY KEY,
  terminal boolean NOT NULL      -- Sanitizado (sai do universo) / Autoprodutor (conta como feito)
);
INSERT INTO cadastro.status_input VALUES
  ('A Iniciar', false), ('Em Andamento', false), ('Concluído', false), ('Block', false),
  ('Sanitizado', true), ('Autoprodutor', true);

-- Vocabulário do histórico: (entidade, campo) válidos. É o que impede o desvio de hoje
-- ('etapa' x 'etapa_migracao' para o mesmo campo; acao 'desativar' lida como 'add').
CREATE TABLE cadastro.campo_evento (
  entidade text NOT NULL,
  campo    text NOT NULL,
  PRIMARY KEY (entidade, campo)
);
INSERT INTO cadastro.campo_evento VALUES
  ('egp', 'etapa'), ('egp', 'status'), ('egp', 'responsavel'), ('egp', 'responsavel_bv'),
  ('egp', 'jira_id'), ('egp', 'mes_prioridade'), ('egp', 'preworking_preenchido'),
  ('egp', 'preworking_data'), ('egp', 'egp_atualizado_key'), ('egp', 'rename'),
  ('vinculo', 'tipo'), ('vinculo', 'sucessor'),
  ('input', 'etapa'), ('input', 'status'), ('input', 'responsavel'), ('input', 'observacao'),
  ('input', 'status_humano'),                                   -- legado, só histórico
  ('preworking', 'origem_arquivo'), ('preworking', 'frequencia'), ('preworking', 'horario'),
  ('preworking', 'tipo_carga'), ('preworking', 'pos_processamento'),
  ('preworking', 'dados_sensiveis'), ('preworking', 'recebido'),
  ('preworking', 'data_recebimento'), ('preworking', 'modernizado_bv'),
  ('preworking', 'data_modernizado_bv'),
  ('escopo', 'add'), ('escopo', 'remove'), ('escopo', 'desativar'), ('escopo', 'reativar'),
  ('leitura_dispensada', 'link_broken'), ('dependencia_mantida', 'dep_mantida'),
  ('profundidade_necessaria', 'tipo'), ('profundidade_necessaria', 'valor'),
  ('profundidade_ingerida', 'desde'), ('profundidade_ingerida', 'ingerida_em'),
  ('gestao', 'inicio'), ('gestao', 'fim_conversao'), ('gestao', 'fim'), ('gestao', 'com_bv'),
  ('config', 'prio_capacidade'), ('config', 'egps_novos'), ('config', 'ex_deps_manuais'),
  ('priorizacao', 'plano_salvo'),
  ('identidade', 'colapso'), ('identidade', 'renomear'), ('identidade', 'remover'),
  ('identidade', 'ajuste_manual'),                 -- one-offs de hoje (escopo_output, rename no payload)
  ('versao_recebida', 'etapa'), ('versao_recebida', 'status'),          -- legado: funil da aba
  ('versao_recebida', 'responsavel'), ('versao_recebida', 'tipo_vinculo'); -- aposentada (ADR 0001)

-- Parâmetros escalares da gestão. Listas (egps_novos, ex_deps_manuais) viraram tabelas.
CREATE TABLE cadastro.parametro (
  chave          text PRIMARY KEY CHECK (chave IN ('prio_capacidade')),
  valor          jsonb NOT NULL,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON cadastro.parametro FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- =============================================================================
-- CORPUS — dono único: publish (fase 1: sync Databricks -> Postgres)
-- =============================================================================

-- ÂNCORA do EGP (antigo sas_lineage_nodes). MERGE ... WHEN NOT MATCHED BY SOURCE THEN
-- UPDATE SET orfao = true (PG17). Atributos derivados são NULLable: a linha órfã guarda o
-- último valor conhecido (hoje 706 inputs órfãos têm origem/paths NULL porque a coluna
-- veio por ALTER depois que eles saíram do corpus).
CREATE TABLE corpus.egp (
  projeto      text PRIMARY KEY CHECK (projeto <> ''),   -- 'Área__nome'
  area         text,
  onda         text,                     -- legado (substituída pelo Mês do plano); ainda lida
  ciclo_id     integer NOT NULL DEFAULT 0,
  casca        boolean NOT NULL DEFAULT false,  -- src/egps_casca.csv; fase 2 aposenta a linha
                                                -- 'casca' em sas_escopo e o input sintético casco::
  n_inputs     integer,
  n_outputs    integer,
  loc          integer,
  code_tasks_count integer,
  n_outputs_avaliados integer,
  n_outputs_consumidos_por_outro_egp integer,
  pct_outputs_consumidos_por_outro_egp numeric,
  n_egps_consumidores integer,
  n_exports_arquivos integer,
  flag_output_100pct_egp boolean,
  flag_algum_output_egp boolean,
  flag_sem_export_arquivo boolean,
  flag_output_unico boolean,
  flag_hub_multiplos_consumidores boolean,
  orfao        boolean NOT NULL DEFAULT false,  -- sumiu do último publish; âncora preservada
  publicado_em timestamptz NOT NULL DEFAULT now()
);

-- ÂNCORA do Input (grão SAFRA / tabela física — o grafo continua neste grão: ADR 0002/0003).
-- A chave NÃO muda de formato: 'categoria::CANON' (estado, auditoria e URLs dependem dela).
CREATE TABLE corpus.input (
  chave           text PRIMARY KEY,
  categoria       text NOT NULL CHECK (categoria IN ('tabela', 'arquivo', 'script')),
  artefato        text NOT NULL,
  -- casa com corpus.output.chave (que é PURA, sem prefixo) sem o upper(artifact) de hoje
  artefato_canon  text GENERATED ALWAYS AS (substr(chave, strpos(chave, '::') + 2)) STORED,
  origem          text CHECK (origem IN ('BigQuery', 'Transacional', 'SAS/Local (externo)',
                                         'SAS/Local (dependência)', 'Arquivo', 'Script',
                                         'Casco (EGP unificado)')),  -- 7º valor: fase 1 só
  source_types    text[] NOT NULL DEFAULT '{}',
  areas           text[] NOT NULL DEFAULT '{}',
  qtd_projetos    integer,
  disponivel_auto boolean,               -- antigo modernizada_auto: 'Disponível' = true
  paths_fisicos   text[] NOT NULL DEFAULT '{}',   -- identidade física ADITIVA (não colapsa linha)
  n_paths_fisicos integer GENERATED ALWAYS AS (cardinality(paths_fisicos)) STORED,
  orfao           boolean NOT NULL DEFAULT false, -- também marca alias COLAPSADO (ADR 0003)
  publicado_em    timestamptz NOT NULL DEFAULT now(),
  -- 13.064 de 13.069 chaves obedecem; as 5 fora são os inputs sintéticos 'casco::' (fase 1)
  CHECK (split_part(chave, '::', 1) = categoria OR chave LIKE 'casco::%')
);
CREATE INDEX input_artefato_canon ON corpus.input (artefato_canon);

-- ÂNCORA do Output. Hoje é DROP+CREATE (16 recebimentos e 1 escolha de produtor já apontam
-- para outputs que sumiram); passa ao mesmo molde de input: UPSERT + orfao.
CREATE TABLE corpus.output (
  chave            text PRIMARY KEY,     -- canon(artefato), SEM prefixo (convenção do pipeline)
  categoria        text NOT NULL CHECK (categoria IN ('table_out', 'file_out')),
  artefato         text NOT NULL,
  areas            text[] NOT NULL DEFAULT '{}',
  qtd_produtores   integer,
  qtd_criadores    integer,
  qtd_consumidores integer,
  terminal         boolean,
  disponivel_auto  boolean,
  paths_fisicos    text[] NOT NULL DEFAULT '{}',
  orfao            boolean NOT NULL DEFAULT false,
  publicado_em     timestamptz NOT NULL DEFAULT now()
);

-- FATO: EGP lê Input (antigo sas_egp_inputs). Saem area/onda/ciclo_id/categoria/
-- modernizada_auto (função de projeto ou de chave) e escopo_indi (derivado do escopo).
CREATE TABLE corpus.egp_input (
  projeto      text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave  text NOT NULL REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  artefato     text NOT NULL,              -- grafia vista NESTE EGP
  source_types text[] NOT NULL DEFAULT '{}',  -- do PAR, não do input
  PRIMARY KEY (projeto, input_chave)
);
CREATE INDEX egp_input_input ON corpus.egp_input (input_chave);

-- FATO: EGP produz Output (antigo sas_egp_outputs).
CREATE TABLE corpus.egp_output (
  projeto          text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  output_chave     text NOT NULL REFERENCES corpus.output ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  artefato         text NOT NULL,
  apenas_contribui boolean NOT NULL DEFAULT false,  -- apensa, não cria (regra do criador)
  PRIMARY KEY (projeto, output_chave)
);
CREATE INDEX egp_output_output ON corpus.egp_output (output_chave);

-- FATO: aresta de linhagem consumidor -> produtor (antigo sas_lineage_edges). Não se chama
-- "dependência" de propósito: no glossário Dependência é a CLASSIFICAÇÃO do EGP.
CREATE TABLE corpus.aresta_linhagem (
  consumidor     text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  produtor       text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  via_tabelas    text[] NOT NULL CHECK (cardinality(via_tabelas) > 0),
  qtd_via        integer GENERATED ALWAYS AS (cardinality(via_tabelas)) STORED,
  max_produtores integer NOT NULL DEFAULT 1,
  PRIMARY KEY (consumidor, produtor),
  CHECK (consumidor <> produtor)
);
CREATE INDEX aresta_linhagem_produtor ON corpus.aresta_linhagem (produtor);

-- Universo da aba Resumo: inclui categoria 'lib' (libname_in), que NÃO é input do monitor.
-- Mantido como relatório desnormalizado de propósito (ver relatório §3).
CREATE TABLE corpus.resumo_input (
  chave           text PRIMARY KEY,
  area_principal  text NOT NULL DEFAULT '(sem área)',  -- voto no frontier (Python)
  origem_bucket   text NOT NULL CHECK (origem_bucket IN ('BigQuery', 'Libname_in', 'Arquivo',
                                                         'Transacional', 'SAS/Local')),
  disponivel_auto boolean NOT NULL
);
CREATE TABLE corpus.resumo_egp_input (       -- antigo sas_resumo_proj
  chave   text NOT NULL REFERENCES corpus.resumo_input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  projeto text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  PRIMARY KEY (chave, projeto)
);
CREATE INDEX resumo_egp_input_projeto ON corpus.resumo_egp_input (projeto);

-- =============================================================================
-- TRABALHO — estado humano durável (dono: app; scripts de admin com app.usuario setado)
-- =============================================================================

-- Escopo (lista DOR1). `projeto` é referência SOFT de propósito: uma entrada 'faltante'
-- nomeia EGP que ainda não chegou ao corpus (o self-heal promove a 'exato' depois).
CREATE TABLE trabalho.escopo_item (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),  -- ids hex atuais fazem cast direto
  egp_dor1        text NOT NULL UNIQUE,
  area            text,
  status_extracao text NOT NULL CHECK (status_extracao IN
                    ('exato', 'variante', 'confirmado_area', 'ingerido_extraido', 'faltante')),
  projeto         text CHECK (projeto <> ''),
  origem          text NOT NULL CHECK (origem IN ('csv', 'manual', 'casca')),  -- 'casca' sai na fase 2
  ativo           boolean NOT NULL DEFAULT true,
  criado_em       timestamptz,          -- NULL nas 227 linhas cujo created_at hoje é a string 'seed'
  criado_por      text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE UNIQUE INDEX escopo_item_projeto ON trabalho.escopo_item (projeto) WHERE projeto IS NOT NULL;

-- Pipeline do EGP (etapa/status/responsável/mês/Jira). Vínculo saiu para tabela própria;
-- etapa_progresso/status_progresso (100% NULL) saíram.
CREATE TABLE trabalho.pipeline_egp (
  projeto               text PRIMARY KEY REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  etapa                 text REFERENCES cadastro.etapa_migracao ON UPDATE CASCADE,
  status                text REFERENCES cadastro.status_migracao ON UPDATE CASCADE,
  responsavel           text REFERENCES cadastro.usuario (email) ON UPDATE CASCADE,
  responsavel_bv        text REFERENCES cadastro.responsavel_bv (nome_chave) ON UPDATE CASCADE,
  jira_id               text CHECK (jira_id ~ '^[A-Z][A-Z0-9]+-[0-9]+$'),
  mes_prioridade        smallint CHECK (mes_prioridade > 0),   -- pin de mês do plano
  preworking_preenchido boolean,
  preworking_data       date,
  egp_atualizado_key    text,   -- SUGESTÃO da chegada (atualizados.versao_recebida.egp_key; não única)
  atualizado_em         timestamptz NOT NULL DEFAULT now(),
  atualizado_por        text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.pipeline_egp FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Vínculo Antecessor -> Sucessor. Mora no Antecessor (PK) — um Sucessor por Antecessor;
-- Unificado = N antecessores apontando para o mesmo sucessor. Status 'Desatualizado' e
-- etapa espelhada são DERIVADOS (nunca gravados). Ciclo (v1->v2->v1) fica a cargo do app.
CREATE TABLE trabalho.vinculo (
  antecessor     text PRIMARY KEY REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  sucessor       text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  tipo           text NOT NULL CHECK (tipo IN ('Atualizado', 'Substituído', 'Unificado')),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual(),
  CHECK (antecessor <> sucessor)
);
CREATE INDEX vinculo_sucessor ON trabalho.vinculo (sucessor);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.vinculo FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Estado humano do Input (as 4 colunas humanas que hoje dividem linha com o derivado em
-- sas_inputs_monitor). Grão SAFRA: escrita de família faz fan-out (ADR 0002).
-- Linha ausente / NULL = "ninguém decidiu" -> o estado efetivo é derivado do auto pelas
-- geradoras de input_state.py (não há view SQL disso de propósito: seria a 3ª cópia).
CREATE TABLE trabalho.estado_input (
  chave          text PRIMARY KEY REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  etapa          text REFERENCES cadastro.etapa_ingestao ON UPDATE CASCADE,
  status         text REFERENCES cadastro.status_input ON UPDATE CASCADE,
  responsavel    text REFERENCES cadastro.usuario (email) ON UPDATE CASCADE,
  observacao     text,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.estado_input FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- "Este EGP não precisa deste input" (antigo sas_egp_input_link). A coluna link_broken era
-- sempre true (invariante "linha ausente ≡ linkado"): a PRESENÇA da linha é o fato.
-- Renomeada: "vínculo" no glossário é Antecessor -> Sucessor. FK às duas âncoras, NÃO ao
-- par (o par é fato substituível). Par que sumiu do corpus aparece em derivado.v_trabalho_orfao.
CREATE TABLE trabalho.leitura_dispensada (
  projeto        text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave    text NOT NULL REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual(),
  PRIMARY KEY (projeto, input_chave)
);
CREATE INDEX leitura_dispensada_input ON trabalho.leitura_dispensada (input_chave);

-- "Ainda dependo do PRODUTOR deste input" (espelho do anterior; tabela separada de propósito).
CREATE TABLE trabalho.dependencia_mantida (
  projeto        text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave    text NOT NULL REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  motivo         text,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual(),
  PRIMARY KEY (projeto, input_chave)
);
CREATE INDEX dependencia_mantida_input ON trabalho.dependencia_mantida (input_chave);

-- Família de safras: NÃO é materializada (régua em familias.py + familias_overrides.json,
-- corpus inteiro, >=2 membros). Tabelas no grão família guardam (familia_categoria,
-- familia_nome) como referência SOFT; derivado.v_familia_ref lista as que pendem.
-- Profundidade NECESSÁRIA: propriedade do par (EGP, família); união discriminada.
CREATE TABLE trabalho.profundidade_necessaria (
  projeto           text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  familia_categoria text NOT NULL CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome      text NOT NULL,
  tipo              text NOT NULL CHECK (tipo IN ('todas', 'desde', 'rolling')),
  desde             date CHECK (extract(day FROM desde) = 1),   -- 'AAAAMM' -> 1º dia do mês
  ultimos_meses     smallint CHECK (ultimos_meses > 0),
  atualizado_em     timestamptz NOT NULL DEFAULT now(),
  atualizado_por    text NOT NULL DEFAULT cadastro.usuario_atual(),
  PRIMARY KEY (projeto, familia_categoria, familia_nome),
  CHECK ((tipo = 'todas'   AND desde IS NULL     AND ultimos_meses IS NULL)
      OR (tipo = 'desde'   AND desde IS NOT NULL AND ultimos_meses IS NULL)
      OR (tipo = 'rolling' AND desde IS NULL     AND ultimos_meses IS NOT NULL))
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.profundidade_necessaria FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Profundidade INGERIDA: fato declarado por quem ingere; só avisa, nunca bloqueia.
CREATE TABLE trabalho.profundidade_ingerida (
  familia_categoria text NOT NULL CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome      text NOT NULL,
  desde             date NOT NULL CHECK (extract(day FROM desde) = 1),
  ingerida_em       date,
  atualizado_em     timestamptz NOT NULL DEFAULT now(),
  atualizado_por    text NOT NULL DEFAULT cadastro.usuario_atual(),
  PRIMARY KEY (familia_categoria, familia_nome)
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.profundidade_ingerida FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Checklist de pré-working. Arco exclusivo: pertence a UM input (safra/tabela solta) OU a
-- UMA família (hoje: chave 'familia::...' gravada em chave_canonica). UNIQUE NULLS NOT
-- DISTINCT (PG15+) dá "uma linha por dono" sem PK em coluna NULLable.
CREATE TABLE trabalho.preworking (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  input_chave         text REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  familia_categoria   text CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome        text,
  origem_arquivo      text,
  frequencia          text CHECK (frequencia IN ('Diária', 'Semanal', 'Quinzenal', 'Mensal',
                                                 'Sob demanda', 'Carga única')),
  horario             text,      -- texto livre de fato ('Terceiro dia útil, 08:00')
  tipo_carga          text CHECK (tipo_carga IN ('Full', 'Incremental', 'Full + Incremental')),
  pos_processamento   text CHECK (pos_processamento IN ('Mover', 'Apagar', 'Manter (nenhuma ação)')),
  dados_sensiveis     boolean,   -- 'Sim'/'Não'
  recebido            boolean,   -- 'true'/'false' string hoje
  data_recebimento    date,
  modernizado_bv      boolean,
  data_modernizado_bv date,
  iniciado_em         timestamptz,   -- 1º toque
  concluido_em        timestamptz,   -- 1ª vez 100%
  atualizado_em       timestamptz NOT NULL DEFAULT now(),
  atualizado_por      text NOT NULL DEFAULT cadastro.usuario_atual(),
  CHECK (num_nonnulls(input_chave, familia_nome) = 1),
  CHECK ((familia_nome IS NULL) = (familia_categoria IS NULL)),
  UNIQUE NULLS NOT DISTINCT (input_chave, familia_categoria, familia_nome)
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.preworking FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Recebimento manual por Output (grão output, global).
-- Prod já tem carga_fria/cf_* nesta tabela, criadas por código que não está nesta árvore:
-- entram aqui quando o branch dono for mergeado (não adivinhar tipos).
CREATE TABLE trabalho.output_recebimento (
  output_chave   text PRIMARY KEY REFERENCES corpus.output ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  recebido       boolean NOT NULL,
  recebido_data  date,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.output_recebimento FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Produtor canônico escolhido p/ output multi-produtor (poda o grafo no publish).
-- "projeto é produtor do output" é validado na escrita (o par é fato substituível).
CREATE TABLE trabalho.produtor_escolhido (
  output_chave   text PRIMARY KEY REFERENCES corpus.output ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  projeto        text NOT NULL REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);

-- Gestão: datas por entidade. Arco exclusivo EGP | input | família (fim do entity/entity_id
-- polimórfico, que hoje não aceita FK e já carrega 17 chaves 'familia::').
CREATE TABLE trabalho.gestao_datas (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  projeto           text REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave       text REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  familia_categoria text CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome      text,
  inicio            date,
  fim_conversao     date,
  fim               date,
  atualizado_em     timestamptz NOT NULL DEFAULT now(),
  atualizado_por    text NOT NULL DEFAULT cadastro.usuario_atual(),
  CHECK (num_nonnulls(projeto, input_chave, familia_nome) = 1),
  CHECK ((familia_nome IS NULL) = (familia_categoria IS NULL)),
  UNIQUE NULLS NOT DISTINCT (projeto, input_chave, familia_categoria, familia_nome)
);
CREATE TRIGGER carimba BEFORE UPDATE ON trabalho.gestao_datas FOR EACH ROW EXECUTE FUNCTION cadastro.carimba();

-- Gestão: comentários/status (append-only; o mais recente é o "último status").
CREATE TABLE trabalho.gestao_comentario (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  projeto           text REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave       text REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  familia_categoria text CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome      text,
  autor             text NOT NULL,          -- quem a gestão diz que falou
  texto             text NOT NULL CHECK (btrim(texto) <> ''),
  criado_por        text NOT NULL DEFAULT cadastro.usuario_atual(),   -- quem digitou
  criado_em         timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(projeto, input_chave, familia_nome) = 1),
  CHECK ((familia_nome IS NULL) = (familia_categoria IS NULL))
);
CREATE INDEX gestao_comentario_egp ON trabalho.gestao_comentario (projeto, criado_em DESC) WHERE projeto IS NOT NULL;
CREATE INDEX gestao_comentario_input ON trabalho.gestao_comentario (input_chave, criado_em DESC) WHERE input_chave IS NOT NULL;

-- Gestão: switch "Com BV" — log de eventos com data de NEGÓCIO (data retroativa = admin).
-- É estado (a tela deriva o período "com o BV"), não auditoria; remoção é hard-delete de admin
-- e fica registrada em historico.evento.
CREATE TABLE trabalho.gestao_com_bv (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  projeto      text REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  input_chave  text REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  familia_categoria text CHECK (familia_categoria IN ('tabela', 'arquivo')),
  familia_nome      text,                   -- 7 eventos de hoje já são de família
  com_bv       boolean NOT NULL,
  data         date NOT NULL,               -- data de SP (não converter)
  autor        text NOT NULL DEFAULT cadastro.usuario_atual(),
  registrado_em timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(projeto, input_chave, familia_nome) = 1),
  CHECK ((familia_nome IS NULL) = (familia_categoria IS NULL))
);
CREATE INDEX gestao_com_bv_egp ON trabalho.gestao_com_bv (projeto, data, registrado_em) WHERE projeto IS NOT NULL;
CREATE INDEX gestao_com_bv_input ON trabalho.gestao_com_bv (input_chave, data, registrado_em) WHERE input_chave IS NOT NULL;

-- Extras "novos" declarados pela gestão (antes: JSON em sas_app_config.egps_novos). LISTA,
-- nunca regra: ninguém é Extra sem ter sido nomeado.
CREATE TABLE trabalho.egp_novo_declarado (
  projeto       text PRIMARY KEY REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  declarado_em  timestamptz NOT NULL DEFAULT now(),
  declarado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);

-- Ex-dependências retidas à mão (antes: JSON em sas_app_config.ex_deps_manuais).
CREATE TABLE trabalho.ex_dependencia_retida (
  projeto     text PRIMARY KEY REFERENCES corpus.egp ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  motivo      text,
  retida_em   timestamptz NOT NULL DEFAULT now(),
  retida_por  text NOT NULL DEFAULT cadastro.usuario_atual()
);

-- Decisões de identidade do EGP que o publish tem de HONRAR (hoje são scripts manuais que
-- o publish seguinte desfaz: 'rekey_pos_publish' do CPF_Contrato gravado 4x; duplicata
-- __v2 "removida 2x, reapareceu"). O publish aplica dentro da transação: 'renomear' =
-- UPDATE da âncora (ON UPDATE CASCADE leva o estado junto); 'remover' = âncora fica
-- orfao=true e os fatos do projeto não são carregados.
CREATE TABLE trabalho.egp_decisao_identidade (
  projeto_corpus text PRIMARY KEY,            -- como o publish/extrator o nomeia
  acao           text NOT NULL CHECK (acao IN ('renomear', 'remover')),
  projeto_novo   text,
  motivo         text NOT NULL,
  decidido_em    timestamptz NOT NULL DEFAULT now(),
  decidido_por   text NOT NULL DEFAULT cadastro.usuario_atual(),
  CHECK ((acao = 'renomear') = (projeto_novo IS NOT NULL)),
  CHECK (projeto_novo IS DISTINCT FROM projeto_corpus)
);

-- Decisão de identidade alias -> canônico (ADR 0003, balde A). eh_canonico passa a ser
-- GERADO (hoje é gravado e bate 186/186 com chave = chave_alvo).
CREATE TABLE trabalho.input_alias_canonico (
  chave          text PRIMARY KEY REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  chave_alvo     text NOT NULL REFERENCES corpus.input ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  eh_canonico    boolean GENERATED ALWAYS AS (chave = chave_alvo) STORED,
  membro         text NOT NULL,
  lib            text NOT NULL,
  lib_canonica   text NOT NULL,
  path_fisico    text NOT NULL,       -- o que define o grupo
  n_egps         integer,
  origem_decisao text NOT NULL CHECK (origem_decisao IN ('proposta_automatica', 'revisao_humana')),
  motivo         text,
  ativo          boolean NOT NULL DEFAULT true,
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  atualizado_por text NOT NULL DEFAULT cadastro.usuario_atual()
);
CREATE INDEX input_alias_canonico_alvo ON trabalho.input_alias_canonico (chave_alvo);

-- Plano de priorização congelado. Cada "Salvar" = nova versão; uma só vigente. Os ids
-- mágicos de hoje ('current', 'bkp_pre_dedup_20260818') viram versões com rótulo.
CREATE TABLE trabalho.plano_priorizacao (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vigente    boolean NOT NULL DEFAULT false,
  rotulo     text,
  capacidade integer NOT NULL CHECK (capacidade > 0),
  payload    jsonb NOT NULL,        -- o plano como a tela mostra (meses, resumo, etc.)
  salvo_por  text NOT NULL DEFAULT cadastro.usuario_atual(),
  salvo_em   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX plano_priorizacao_um_vigente ON trabalho.plano_priorizacao (vigente) WHERE vigente;

-- Extraído do payload na mesma escrita: "Mês do plano" vira JOIN, não parse de JSON.
-- projeto SOFT de propósito: o plano congela nomes; re-key não reescreve o passado.
CREATE TABLE trabalho.plano_priorizacao_egp (
  plano_id       bigint NOT NULL REFERENCES trabalho.plano_priorizacao ON DELETE CASCADE,
  projeto        text NOT NULL,
  mes            smallint NOT NULL CHECK (mes > 0),
  ordem          integer NOT NULL,
  mes_pin        smallint,
  n_inputs_novos integer,
  ex_dependencia boolean NOT NULL DEFAULT false,
  PRIMARY KEY (plano_id, projeto)
);

-- =============================================================================
-- HISTÓRICO — append-only (REVOKE UPDATE, DELETE do papel do app)
-- =============================================================================

-- UMA tabela de eventos no lugar de 8 auditorias com formatos diferentes. Escrita
-- explícita pelo app (não trigger genérico): tempo-por-etapa, indicadores mensais e a aba
-- Histórico consultam (entidade, campo, ocorrido_em) — semântica que um diff jsonb de
-- linha não dá. Sem FK de propósito: histórico sobrevive a re-key e a órfão.
CREATE TABLE historico.evento (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ocorrido_em  timestamptz NOT NULL DEFAULT now(),
  ator         text NOT NULL DEFAULT cadastro.usuario_atual(),
  origem       text NOT NULL DEFAULT 'app' CHECK (origem IN ('app', 'publish', 'script', 'migracao')),
  lote         uuid,              -- agrupa o fan-out de UMA ação (família -> N safras;
                                  -- edição em lote) — substitui o GROUP BY ator+instante
  entidade     text NOT NULL,
  chave        text NOT NULL,     -- projeto | chave do input | 'cat::familia' | id do escopo | parâmetro
  chave_2      text,              -- 2º componente de par (input do par EGP×input; projeto do período)
  campo        text NOT NULL,
  valor_antigo text,
  valor_novo   text,
  FOREIGN KEY (entidade, campo) REFERENCES cadastro.campo_evento
);
CREATE INDEX evento_entidade_chave ON historico.evento (entidade, chave, ocorrido_em DESC);
CREATE INDEX evento_entidade_campo ON historico.evento (entidade, campo, ocorrido_em);
CREATE INDEX evento_ocorrido ON historico.evento (ocorrido_em DESC);

-- Uma linha por execução de publish/sync (hoje: só stdout).
CREATE TABLE historico.publicacao (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  origem        text NOT NULL CHECK (origem IN ('publish', 'sync_databricks', 'publish_atualizados')),
  iniciada_em   timestamptz NOT NULL DEFAULT now(),
  concluida_em  timestamptz,
  ok            boolean,
  executor      text NOT NULL DEFAULT cadastro.usuario_atual(),
  versao_codigo text,             -- commit do pipeline
  resumo        jsonb             -- contagens, recusas de identidade, macro_dropped, órfãos novos
);

-- Série do publish (antigo sas_pipeline_metrics; hoje escrita e nunca lida pelo app).
CREATE TABLE historico.metrica_publicacao (
  publicacao_id bigint NOT NULL REFERENCES historico.publicacao,
  escopo        text NOT NULL,
  metrica       text NOT NULL,
  valor         bigint NOT NULL,
  PRIMARY KEY (publicacao_id, escopo, metrica)
);

-- Contadores diários da sanitização derivada (antes: 'san_contadores::<dia>' no config).
CREATE TABLE historico.sanitizacao_dia (
  dia        date PRIMARY KEY,
  contadores jsonb NOT NULL
);

-- =============================================================================
-- ATUALIZADOS — Versões recebidas (script local publish_egps_atualizados.py; ADR 0001)
-- =============================================================================
CREATE TABLE atualizados.versao_recebida (
  versao_id         text PRIMARY KEY,
  egp_key           text NOT NULL,           -- agrupa versões do mesmo EGP Atualizado
  nome              text,
  area              text,
  arquivo           text,
  arquivo_hash      text CHECK (arquivo_hash ~ '^[0-9a-f]{32}$'),   -- MD5
  origem            text,
  confianca_par     text,
  overlap_tasks     double precision,
  autor_ultimo_save text,
  login_autor       text,
  data_ultimo_save  date,
  data_criacao      date,
  data_recebimento  date NOT NULL,
  valor             double precision,
  esforco           double precision,
  razao             double precision,
  quadrante         text,                    -- consultivo; não decide vínculo
  vetos             text,
  alertas           text,
  n_vetos integer,
  table_in_antigo integer, table_in_novo integer, a_ingerir_antigo integer, a_ingerir_novo integer,
  disponivel_antigo integer, disponivel_novo integer, file_in_antigo integer, file_in_novo integer,
  script_in_antigo integer, script_in_novo integer, outputs_antigo integer, outputs_novo integer,
  outputs_removidos_com_consumidor integer, outputs_removidos_privados integer,
  inputs_macro_nao_resolvido integer, inputs_rede_novos integer, deps_novas integer,
  loc_antigo integer, loc_novo integer, linhas_add integer, linhas_rem integer, tasks_novas integer,
  alcance_total integer, alcance_por_grafo integer, alcance_por_output integer,
  status_troca      text,
  publicado_por     text NOT NULL DEFAULT cadastro.usuario_atual(),
  publicado_em      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX versao_recebida_egp_key ON atualizados.versao_recebida (egp_key, data_recebimento DESC);

-- Antecessor(es) candidato(s): substitui a string 'A + B' de egp_original. SOFT: 6 nomes
-- de hoje já não estão no corpus.
CREATE TABLE atualizados.versao_antecessor (
  versao_id text NOT NULL REFERENCES atualizados.versao_recebida ON DELETE CASCADE,
  projeto   text NOT NULL,
  PRIMARY KEY (versao_id, projeto)
);

-- chave_canonica segue EXATAMENTE a régua do corpus (ADR 0001: senão o JOIN vivo não casa).
-- Sem FK ao corpus: input da versão pode estar fora do corpus (situacao_no_recebimento).
CREATE TABLE atualizados.versao_input (
  versao_id               text NOT NULL REFERENCES atualizados.versao_recebida ON DELETE CASCADE,
  chave_canonica          text NOT NULL,
  artefato                text,
  categoria               text,
  source                  text,
  situacao_no_recebimento text,
  novo                    boolean,
  PRIMARY KEY (versao_id, chave_canonica)
);
CREATE TABLE atualizados.versao_output (
  versao_id               text NOT NULL REFERENCES atualizados.versao_recebida ON DELETE CASCADE,
  chave_canonica          text NOT NULL,      -- PURA, como corpus.output
  artefato                text,
  categoria               text CHECK (categoria IN ('tabela', 'arquivo')),
  situacao                text,
  novo                    boolean,
  removido                boolean NOT NULL DEFAULT false,
  n_consumidores_externos integer,
  padrao                  boolean,
  PRIMARY KEY (versao_id, chave_canonica)
);

-- =============================================================================
-- DERIVADO — views (fonte única do que hoje é copiado e re-sincronizado)
-- =============================================================================

-- escopo_indi do EGP: hoje gravado em 4 tabelas e re-derivado por 2 cópias de recompute
-- (main.py + publish) + guarda de defasagem (identidade_guard.flags_defasadas).
CREATE VIEW derivado.v_egp_escopo AS
SELECT e.projeto,
       (e.casca OR EXISTS (SELECT 1 FROM trabalho.escopo_item s
                            WHERE s.projeto = e.projeto AND s.ativo)) AS escopo_indi
FROM corpus.egp e;

-- escopo_indi do Input: lido por >=1 EGP do Escopo.
CREATE VIEW derivado.v_input_escopo AS
SELECT i.chave,
       EXISTS (SELECT 1 FROM corpus.egp_input ei
                 JOIN derivado.v_egp_escopo ve ON ve.projeto = ei.projeto
                WHERE ei.input_chave = i.chave AND ve.escopo_indi) AS escopo_indi
FROM corpus.input i;

-- Funil por área (antigo sas_funil_area, DELETE+INSERT a cada edição de escopo).
CREATE VIEW derivado.v_funil_area AS
SELECT area,
       count(*)                                                      AS qtd_dor1,
       count(*) FILTER (WHERE status_extracao <> 'faltante')         AS egps_enviados,
       count(*) FILTER (WHERE status_extracao IN
                        ('exato', 'variante', 'confirmado_area', 'ingerido_extraido')) AS egps_analisados
FROM trabalho.escopo_item
WHERE ativo AND origem <> 'casca'
GROUP BY area;

-- Estado humano que perdeu o chão. O publish imprime/grava a contagem em
-- historico.publicacao.resumo (barulhento, nunca silencioso).
CREATE VIEW derivado.v_trabalho_orfao AS
SELECT 'leitura_dispensada' AS tabela, d.projeto AS chave, d.input_chave AS chave_2
  FROM trabalho.leitura_dispensada d
 WHERE NOT EXISTS (SELECT 1 FROM corpus.egp_input ei
                    WHERE ei.projeto = d.projeto AND ei.input_chave = d.input_chave)
UNION ALL
SELECT 'dependencia_mantida', d.projeto, d.input_chave
  FROM trabalho.dependencia_mantida d
 WHERE NOT EXISTS (SELECT 1 FROM corpus.egp_input ei
                    WHERE ei.projeto = d.projeto AND ei.input_chave = d.input_chave)
UNION ALL
SELECT 'estado_input', s.chave, NULL
  FROM trabalho.estado_input s JOIN corpus.input i ON i.chave = s.chave
 WHERE i.orfao AND (coalesce(s.etapa, 'A Receber') <> 'A Receber'
                 OR coalesce(s.status, 'A Iniciar') <> 'A Iniciar'
                 OR coalesce(s.responsavel, '') <> '' OR coalesce(s.observacao, '') <> '')
UNION ALL
SELECT 'output_recebimento', r.output_chave, NULL
  FROM trabalho.output_recebimento r JOIN corpus.output o ON o.chave = r.output_chave
 WHERE o.orfao
UNION ALL
SELECT 'produtor_escolhido', p.output_chave, p.projeto
  FROM trabalho.produtor_escolhido p
 WHERE NOT EXISTS (SELECT 1 FROM corpus.egp_output eo
                    WHERE eo.output_chave = p.output_chave AND eo.projeto = p.projeto)
UNION ALL
SELECT 'escopo_item', s.projeto, s.egp_dor1
  FROM trabalho.escopo_item s
 WHERE s.ativo AND s.projeto IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM corpus.egp e WHERE e.projeto = s.projeto AND NOT e.orfao);

-- =============================================================================
-- COMPAT (fase 1) — exemplo; uma view por tabela antiga que o app lê
-- =============================================================================
CREATE VIEW compat.sas_inputs_monitor AS
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
       s.atualizado_em                          AS updated_at,
       s.atualizado_por                         AS updated_by,
       i.orfao,
       i.publicado_em                           AS refreshed_at
FROM corpus.input i
LEFT JOIN trabalho.estado_input s   ON s.chave = i.chave
LEFT JOIN derivado.v_input_escopo ve ON ve.chave = i.chave;

CREATE VIEW compat.sas_egp_inputs AS
SELECT ei.projeto, e.area, e.onda, ve.escopo_indi, e.ciclo_id,
       ei.input_chave AS chave_canonica, ei.artefato AS artifact, i.categoria,
       array_to_string(ei.source_types, ' | ') AS source_types,
       CASE WHEN i.disponivel_auto THEN 'Disponível' ELSE 'A ingerir' END AS modernizada_auto
FROM corpus.egp_input ei
JOIN corpus.egp e   ON e.projeto = ei.projeto
JOIN corpus.input i ON i.chave = ei.input_chave
JOIN derivado.v_egp_escopo ve ON ve.projeto = ei.projeto;

-- =============================================================================
-- PAPÉIS DE BANCO (esboço)
-- =============================================================================
-- CREATE ROLE app_leitura NOLOGIN;  -- fase 1: SELECT em compat, derivado, corpus, trabalho, cadastro, historico, atualizados
-- CREATE ROLE app_escrita NOLOGIN;  -- fase 2: + INSERT/UPDATE/DELETE em trabalho, cadastro; INSERT em historico.evento
-- CREATE ROLE publicador  NOLOGIN;  -- escreve corpus, historico.publicacao/metrica; LÊ trabalho (despriorizados,
--                                   -- dependencia_mantida, produtor_escolhido, alias) e aplica o mapa de identidade
-- REVOKE UPDATE, DELETE, TRUNCATE ON historico.evento FROM app_escrita, publicador;
-- REVOKE CREATE ON SCHEMA public FROM PUBLIC;

ROLLBACK;   -- rascunho: troque por COMMIT numa migração numerada (0001_schema_inicial.sql)

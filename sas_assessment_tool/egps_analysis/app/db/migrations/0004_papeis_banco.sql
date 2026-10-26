-- Papéis de banco (ADR 0005), sem LOGIN: a sessão do mestre baixa para eles com SET ROLE.
--   app_leitura  — app na Fase 1 (prod): só lê.
--   sincronizador — tarefa de sincronização da Fase 1: regrava corpus/trabalho, acrescenta
--                   em cadastro.usuario e historico.publicacao.
-- Na Fase 2 entram app_escrita e publicador (esboço no fim do DDL da spec).
-- Papéis são do CLUSTER, não do banco: o IF NOT EXISTS deixa dev e prod no mesmo RDS.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_leitura') THEN
    CREATE ROLE app_leitura NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sincronizador') THEN
    CREATE ROLE sincronizador NOLOGIN;
  END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  TO app_leitura, sincronizador;
GRANT SELECT ON ALL TABLES IN SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  TO app_leitura, sincronizador;
GRANT SELECT ON public.schema_migracao TO app_leitura, sincronizador;

GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA corpus, trabalho TO sincronizador;
GRANT INSERT, UPDATE ON cadastro.usuario TO sincronizador;
GRANT INSERT ON historico.publicacao TO sincronizador;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA historico TO sincronizador;

-- O app e a sincronização entram com o usuário MESTRE (o único que o indicium-secret-rotation
-- gira, a cada 80 dias) e fazem SET ROLE para o papel da sessão: o mestre precisa ser membro.
-- CURRENT_USER = quem roda as migrações = o mestre.
GRANT app_leitura, sincronizador TO CURRENT_USER;

-- Tabelas e views das PRÓXIMAS migrações (rodadas pelo mesmo usuário que rodou esta)
-- nascem legíveis pelos dois papéis — sem isso, a 0005 em diante quebraria o app em silêncio.
ALTER DEFAULT PRIVILEGES IN SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  GRANT SELECT ON TABLES TO app_leitura, sincronizador;

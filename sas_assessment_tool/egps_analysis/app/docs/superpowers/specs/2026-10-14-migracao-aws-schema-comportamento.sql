-- Testes de comportamento do schema proposto (rodar num banco descartável).
SELECT set_config('app.usuario', 'lucas.muller@indicium.ai', false);

\echo '--- prepara: 1 EGP, 1 input, 1 leitura dispensada'
INSERT INTO corpus.egp (projeto) VALUES ('Area__EGP_A');
INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('tabela::LIB.T', 'tabela', 'LIB.T');
INSERT INTO trabalho.leitura_dispensada (projeto, input_chave) VALUES ('Area__EGP_A', 'tabela::LIB.T');

\echo '--- T1 (esperado: ERRO de FK) apagar a âncora com estado humano apontando'
DELETE FROM corpus.input WHERE chave = 'tabela::LIB.T';

\echo '--- T2 (esperado: tabela::LIB.T2) re-key da âncora propaga para o estado humano'
UPDATE corpus.input SET chave = 'tabela::LIB.T2', artefato = 'LIB.T2' WHERE chave = 'tabela::LIB.T';
SELECT input_chave FROM trabalho.leitura_dispensada;

\echo '--- T3 (esperado: ERRO de CHECK) comentário apontando para EGP e input ao mesmo tempo'
INSERT INTO trabalho.gestao_comentario (projeto, input_chave, autor, texto)
VALUES ('Area__EGP_A', 'tabela::LIB.T2', 'lucas.muller@indicium.ai', 'x');

\echo '--- T4 (esperado: 1 linha) comentário com um alvo só'
INSERT INTO trabalho.gestao_comentario (projeto, autor, texto)
VALUES ('Area__EGP_A', 'lucas.muller@indicium.ai', 'ok');
SELECT count(*) FROM trabalho.gestao_comentario;

\echo '--- T5 (esperado: ERRO de CHECK) prefixo da chave diferente da categoria'
INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('arquivo::X', 'tabela', 'X');

\echo '--- T6 (esperado: ator preenchido) carimbo do usuário vindo de app.usuario'
SELECT atualizado_por FROM trabalho.leitura_dispensada;

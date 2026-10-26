# 14: A derivação do vínculo vale em todas as superfícies que devem vê-la

**What to build:** Hoje `vinculos.anexa_vinculo()` é aplicado em **um lugar só** — o `/api/egp-readiness` (main.py:4817). Todas as demais superfícies leem `etapa_migracao` e `status_migracao` crus de `sas_egp_pipeline`. Resultado: **a aba EGPs e o Resumo discordam sobre a etapa do mesmo antecessor** — uma mostra a espelhada, a outra a antiga.

Isso contraria diretamente a régua fechada com a gestão: *"a etapa irá correr junto com o EGP atualizado — isso será visto nas tabelas de resumo dos funis atuais"*. É defeito do commit `be9b00d2`, latente enquanto não existir vínculo gravado (hoje são zero).

**O trabalho NÃO é "aplicar a derivação em tudo".** É decidir, superfície por superfície, quem vê o valor derivado e quem precisa do real — e deixar essa decisão explícita no código, em vez de acidental. Pelo menos um ponto precisa do valor **real**: a consulta que descobre quem está despriorizado (main.py:3697) — `Desatualizado` é derivado e o status verdadeiro continua por baixo; derivar ali inverteria a regra.

**Blocked by:** None (o núcleo já existe)

**Status:** ENTREGUE (29/09/2026, commits 73433f38)

- [ ] Cada superfície que lê etapa/status de `sas_egp_pipeline` tem uma escolha EXPLÍCITA: derivado ou real, com o porquê junto
- [ ] Os funis do Resumo mostram a etapa espelhada do antecessor — a aba EGPs e o Resumo param de discordar
- [ ] A consulta de quem está despriorizado continua lendo o status REAL
- [ ] `Desatualizado` nunca conta como migrado, em nenhuma superfície
- [ ] Existe um teste que falha se alguém adicionar uma leitura crua nova sem decidir

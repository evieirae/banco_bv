# 07: O vínculo leva o trabalho de gestão para o sucessor

**What to build:** No ato do vínculo, **etapa**, mês do plano, JIRA e responsável são **copiados** para o sucessor — daí em diante cada um segue sozinho. É o que faz quem executa achar o trabalho no lugar certo sem reconstruir o contexto à mão (medido em prod: dos 42 antecessores, 35 têm mês, 33 têm JIRA e 36 têm responsável).

No tipo `Substituído`, o app **sugere** fechar o antecessor como `Despriorizado e Contabilizado` — a ação é da gestão, nunca automática. Classificar não muda status sozinho: o repo já tem a invariante de nunca cascatear status.

**Blocked by:** 03 (a cópia acontece no ato do vínculo)

**Status:** ENTREGUE (29/09/2026, commits db370d34)

- [ ] Criar o vínculo copia etapa, mês, JIRA e responsável para o sucessor
- [ ] O funil `+deps` não perde nenhum EGP de coluna ao criar o vínculo — sem a cópia da
      etapa, o antecessor espelharia a etapa vazia do sucessor e sumiria da distribuição
- [ ] Depois da cópia, editar um dos campos no sucessor não altera o antecessor, e vice-versa
- [ ] No tipo Substituído aparece a sugestão de fechar o antecessor, com um clique para aplicar
- [ ] Nenhum status é alterado sem alguém ter clicado
- [ ] O antecessor continua ocupando a vaga dele no escopo e no plano do mês

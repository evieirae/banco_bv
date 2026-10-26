# 11: A aba EGPs Atualizados é aposentada

**What to build:** A aba dedicada sai da barra e o que ela tinha de único — a comparação com o antecessor (deltas, impactos, inputs novos, outputs removidos com consumidor, histórico de versões, autor e data do último save) — vira uma seção do detalhe do EGP. Depois dos tickets anteriores, manter as duas telas significaria o mesmo EGP em dois lugares, com duas taxonomias e dois funis.

A taxonomia "Situação" morre e fica o Tipo de vínculo. Os dois valores dela que não são tipo — pareamento não resolvido e falha na extração — viram **pendência**: descartá-los junto faria um arquivo cuja extração falhou parecer normal, que é um bug que já foi corrigido uma vez.

**Blocked by:** 04, 05 e 10 (a aba EGPs precisa carregar o vínculo, a contagem e a fila de chegada antes)

**Status:** ENTREGUE (29/09/2026, commits a15c3b64 + c3e60215)

- [ ] A comparação com o antecessor está disponível no detalhe do EGP, com o mesmo conteúdo de hoje
- [ ] A aba dedicada saiu da barra e o link antigo não leva a lugar nenhum quebrado
- [ ] As tabelas da comparação e o script de carga continuam existindo — só a tela saiu
- [ ] O estado editável que vivia no funil próprio foi para o funil de migração do sucessor, sem perda
- [ ] Pareamento não resolvido e falha na extração continuam visíveis como pendência
- [ ] Nenhum dos 10 vínculos já confirmados foi perdido

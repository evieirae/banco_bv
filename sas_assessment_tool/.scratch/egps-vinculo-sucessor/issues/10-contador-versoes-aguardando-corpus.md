# 10: Versão recebida que ainda não entrou no corpus fica visível

**What to build:** Entre o recebimento do arquivo e a entrada dele no corpus, o sucessor não existe em superfície nenhuma — deveria durar o tempo de uma rodada do pipeline, mas se ninguém rodar, dura dias e o arquivo some de vista. A aba EGPs passa a mostrar quantas versões estão nesse limbo, e quais.

É a guarda que repõe o que a aba dedicada fazia quando ela for aposentada: sem isso, "chegou versão nova" vira um fato que ninguém vê.

**Blocked by:** 01 (a regra de nomeação é o que permite saber qual chave esperar no corpus)

**Status:** ENTREGUE (29/09/2026, commits f86de95a + 5e7952fc)

- [ ] A aba EGPs mostra quantas versões recebidas ainda não viraram projeto do corpus
- [ ] Dá para ver quais são, não só o número
- [ ] O contador zera sozinho depois de uma rodada do pipeline
- [ ] Versão descartada some do contador sem exigir limpeza manual
- [ ] Nenhuma versão recebida some de vista sem ter entrado no corpus ou sido descartada

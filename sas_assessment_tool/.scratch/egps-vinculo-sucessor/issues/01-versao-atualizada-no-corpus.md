# 01: A versão atualizada vira um projeto do corpus

**What to build:** O `.egp` reenviado pelo cliente entra no inventário como um projeto próprio, ao lado do antecessor em vez de por cima dele. O arquivo vai para a pasta irmã de recebidos, nomeado com o sufixo da data de recebimento, e passa pelo extrator e pelo orquestrador na mesma rodada dos demais. Ao fim, ele aparece na aba EGPs (recorte "base completa") como qualquer outro EGP: com os inputs, os outputs e a linhagem dele, e sem colidir com o antecessor de mesmo nome.

É o tracer bullet que prova a arquitetura inteira — e não tem código: a chave do corpus é derivada do nome do arquivo, então a separação física e o sufixo resolvem sozinhos. O que este ticket produz de permanente é o procedimento documentado.

**Blocked by:** None (can start immediately)

**Status:** ENTREGUE (29/09/2026, commits 08ea1ea9 + 1e6d35ed)

- [ ] Um `.egp` atualizado real, colocado na pasta irmã com o sufixo de recebimento, vira um projeto no inventário com a área correta
- [ ] O antecessor de mesmo nome continua existindo, com os inputs dele intactos — nada foi sobrescrito
- [ ] Os inputs, outputs e a linhagem do sucessor são os da versão NOVA, não os do antecessor
- [ ] O procedimento (onde o arquivo mora, como se chama, em que ordem rodar) está documentado junto do restante do pipeline, incluindo por que o sufixo não pode ser `__v2`/`__v3`
- [ ] Rodar o pipeline duas vezes não duplica nem apaga nada

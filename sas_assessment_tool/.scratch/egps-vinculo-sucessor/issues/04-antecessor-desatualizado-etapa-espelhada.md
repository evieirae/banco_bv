# 04: O antecessor fica Desatualizado com a etapa do sucessor

**What to build:** Criado o vínculo, o antecessor passa a exibir o status `Desatualizado` e a **etapa do sucessor** — porque o trabalho migrou para lá. A etapa dele vira somente leitura: quem tentar mudá-la é recusado pelo servidor, com a mensagem mandando editar no sucessor.

Tudo derivado, nada gravado: o status real do antecessor continua no banco e reaparece inteiro se o vínculo for desfeito. Duas exceções: quem já é `Despriorizado e Contabilizado` continua despriorizado (decisão de gestão não é apagada por fato derivado), e `Substituído` não espelha nada — ali as trajetórias são independentes.

**Blocked by:** 03 (o vínculo é o que dispara o espelhamento)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] Antecessor com vínculo Atualizado ou Unificado mostra `Desatualizado` e a etapa do sucessor
- [ ] Tentar editar a etapa desse antecessor é recusado pelo servidor, não só desabilitado na tela
- [ ] Desfazer o vínculo devolve o status e a etapa reais, sem nenhum passo manual
- [ ] Antecessor despriorizado continua despriorizado, com o vínculo aparecendo como marca
- [ ] Antecessor de um vínculo Substituído mantém etapa e status editáveis
- [ ] Sucessor fora do recorte carregado deixa a etapa vazia em vez de mostrar a etapa antiga como se fosse a nova
- [ ] `Desatualizado` nunca é contado como migrado em nenhuma superfície

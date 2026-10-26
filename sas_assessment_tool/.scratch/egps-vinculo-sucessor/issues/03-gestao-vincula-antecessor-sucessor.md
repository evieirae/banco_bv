# 03: A gestão vincula o antecessor ao sucessor

**What to build:** Na aba EGPs, quem é da gestão escolhe o tipo do vínculo (`Atualizado`, `Substituído` ou `Unificado`) e aponta qual projeto é o sucessor. A linha do antecessor passa a mostrar o vínculo, e ele fica filtrável.

O app **sugere** o tipo pelo pareamento (dois ou mais antecessores → Unificado; um antecessor de mesmo nome → Atualizado; nome diferente → Substituído) mas nunca decide: medido em prod, nem o nome nem a sobreposição de tasks separam Atualizado de Substituído — há caso de nome igual com sobreposição zero e renomeação com sobreposição de 0,94. A distinção é de intenção do cliente.

**Blocked by:** 01 (o sucessor precisa existir no corpus para ser apontado)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] A gestão cria, troca e desfaz o vínculo pela aba EGPs, e a mudança fica auditada
- [ ] O servidor recusa: tipo inválido, sucessor que não está no corpus, e antecessor com status Migrado — cada um com mensagem dizendo o que fazer
- [ ] Quem não é da gestão recebe 403 ao mexer no vínculo, mas continua podendo editar etapa e status como hoje
- [ ] Vínculo pela metade (tipo sem sucessor, ou sucessor sem tipo) não vale como vínculo e não produz efeito nenhum
- [ ] O tipo sugerido aparece como sugestão, visivelmente distinto de um tipo confirmado

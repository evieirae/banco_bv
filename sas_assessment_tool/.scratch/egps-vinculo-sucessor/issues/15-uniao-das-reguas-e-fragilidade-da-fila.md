# 15: União das duas réguas de sanitização + aviso de fragilidade da fila

**What to build:** Duas decisões da gestão em 28/09/2026, uma de régua e uma de visibilidade.

**(a) As duas origens se somam.** Hoje `motivos_derivados` aplica as réguas de despriorizado e de antecessor **separadamente**, então um input lido por um despriorizado E um antecessor (projetos distintos) fica na fila, porque cada regra sozinha recusa. Passa a sair: a chave sai quando **todos** os consumidores no escopo estão resolvidos, misturando as origens. Ver §3.4.17 da spec.

**Trava obrigatória:** o **sucessor segura o input sozinho**. Ele está no recorte e não é antecessor, logo conta como consumidor vivo — se a versão nova também lê a chave, ela continua na fila. É o que impede a régua de sanitizar justamente o inventário que passou a valer.

**(b) A fila pode crescer sozinha, e isso fica visível.** Dois mecanismos, ambos pedidos:

1. **Fragilidade (presente, nada gravado):** aviso permanente — *"N chaves estão fora da fila só porque M EGPs estão fora do escopo; se qualquer um deles entrar, elas voltam"* — com o rollup inverso `EGP fora → quantas chaves voltariam`, que é a pergunta acionável. Medido em 24/09: até **73 chaves**.
2. **Log diário de contadores (passado):** uma linha por dia em `sas_app_config` com `{data, n_sanitizadas_por_origem, n_frageis}`. Grava **só contador, nunca estado** — a régua continua derivada e reversível. Começa a acumular agora porque histórico não se reconstrói.

**Blocked by:** 02 e 08 (a maquinaria)

**Status:** ENTREGUE (29/09/2026, commits 2d77a40c)

- [ ] Input cujos consumidores misturam as duas origens sai da fila
- [ ] Input que o SUCESSOR também lê continua na fila, por mais resolvidos que estejam os outros consumidores
- [ ] O motivo mostrado num caso misto é compreensível (não mente sobre a origem)
- [ ] O aviso de fragilidade mostra N chaves e M EGPs, e permite ver quais
- [ ] O log diário grava contadores e NUNCA o estado derivado
- [ ] Nada do log realimenta a régua — desligar o log não muda nenhum número da fila

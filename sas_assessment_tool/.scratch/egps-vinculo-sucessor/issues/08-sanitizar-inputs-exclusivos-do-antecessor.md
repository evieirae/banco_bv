# 08: Input que só o antecessor lê sai da fila

**What to build:** Vinculado o sucessor, os inputs que **só o antecessor** lê param de contar na fila: o que vale passa a ser o inventário da versão nova. Eles contam como Sanitizado — derivado, visíveis, com o motivo — e voltam sozinhos se o vínculo for desfeito.

A exclusividade é medida **contra o escopo ativo**, não contra o corpus inteiro: foi decisão explícita da gestão, ciente de que até 73 chaves voltam à fila sozinhas no dia em que um EGP hoje fora do escopo entrar. Input lido por qualquer outro EGP do escopo não é tocado.

**Blocked by:** 03 (precisa do vínculo) e 02 (reusa a maquinaria de sanitização derivada)

**Status:** ENTREGUE (29/09/2026, commits f82a1be4)

- [ ] Input lido só pelo antecessor aparece como Sanitizado assim que o vínculo é criado
- [ ] Input lido por outro EGP do escopo não é tocado
- [ ] Desfazer o vínculo devolve os inputs à fila sem intervenção
- [ ] O motivo distingue as duas origens ("só consumidores despriorizados" × "só o antecessor, que tem sucessor")
- [ ] Quando um EGP hoje fora do escopo entra e devolve inputs à fila, isso é ANUNCIADO — a fila crescer sem ninguém ter agido não pode ser descoberto por acaso

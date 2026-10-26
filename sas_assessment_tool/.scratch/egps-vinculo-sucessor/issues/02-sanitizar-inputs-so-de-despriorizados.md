# 02: Input lido só por EGPs despriorizados sai da fila

**What to build:** A fila de ingestão para de pedir ao BV tabelas que só EGPs despriorizados leem. Um input cujos consumidores são todos EGPs despriorizados passa a contar como Sanitizado — **derivado**, sem gravar status: continua visível na aba Inputs, com o rótulo e o motivo, e volta sozinho se algum consumidor for repriorizado.

Não depende do vínculo: é a mesma regra de "input exclusivo de quem não vai ser migrado não é trabalho", e entrega valor sozinha. Medido em prod (24/09/2026): 370 chaves são lidas só por despriorizados; 202 delas já foram sanitizadas na mão, e ~132 ainda estão na fila.

**Blocked by:** None (can start immediately)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] Input cujos consumidores são todos despriorizados aparece como Sanitizado sem que nenhum status tenha sido gravado
- [ ] Input lido por pelo menos um EGP não despriorizado NÃO é tocado
- [ ] As ~132 chaves pendentes saem da fila de ingestão; as 202 já sanitizadas na mão continuam como estão
- [ ] Repriorizar um EGP devolve os inputs dele à fila sem intervenção manual
- [ ] O motivo é visível no input ("só consumidores despriorizados"), não só o rótulo

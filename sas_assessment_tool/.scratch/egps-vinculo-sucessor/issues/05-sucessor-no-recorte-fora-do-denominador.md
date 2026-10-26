# 05: O sucessor aparece no recorte sem inflar a contagem

**What to build:** O sucessor passa a aparecer em "Indicium + dependências" — com um tipo próprio no filtro que já separa escopo, dependência e ex-dependência — e os inputs dele entram na fila de ingestão. Ele não é dependência de ninguém, então entra no recorte **por regra**, não pelo grafo.

Mas o card de total **não se mexe**: o avanço dele já é contado na linha do antecessor, via etapa espelhada, e somar os dois contaria o mesmo trabalho duas vezes. A exceção é `Substituído`, onde o sucessor conta — ali o antecessor saiu do fluxo. Em uma frase: quem espelha não conta duas vezes; quem substitui, conta.

**Blocked by:** 03 (sem vínculo não há sucessor a reconhecer)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] O sucessor aparece no recorte "Indicium + dependências", filtrável pelo tipo próprio
- [ ] Os inputs do sucessor entram na fila de ingestão; os do antecessor continuam como estavam
- [ ] Criar um vínculo Atualizado ou Unificado NÃO muda o card de total de EGPs — só acrescenta uma linha
- [ ] Criar um vínculo Substituído acrescenta 1 ao total
- [ ] Os quatro funis do Resumo devolvem exatamente os mesmos números de antes da mudança — se algum mexeu, o sucessor vazou para o denominador
- [ ] O recorte reflete o vínculo novo sem precisar reiniciar o app

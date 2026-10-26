# 06: EGP desatualizado ganha coluna própria no Kanban

**What to build:** No board de EGPs, quem tem sucessor sai da trilha de etapas e aparece numa coluna `Desatualizado` — porque o trabalho dele está acontecendo no sucessor, e deixá-lo numa etapa sugere um andamento que não é dele. O sucessor percorre as etapas normalmente.

A coluna reusa a precedência que já existe para despriorizado (status como chave de coluna, sobrepondo a etapa), e **despriorizado vence**: só cabe um status por EGP, e a despriorização é decisão de gestão.

**Blocked by:** 04 (a coluna depende do status Desatualizado existir)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] EGP com vínculo que espelha aparece na coluna `Desatualizado`, fora da trilha de etapas
- [ ] EGP despriorizado E desatualizado aparece na coluna de despriorizado, com o vínculo como marca
- [ ] O sucessor aparece na coluna da etapa dele, como qualquer EGP
- [ ] A divergência com o funil do Resumo (onde o mesmo EGP aparece na etapa espelhada) está explicada no guia do app — é contagem × trabalho, e vai parecer contradição para quem olhar as duas telas na mesma reunião

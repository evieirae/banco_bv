# 20: Não existe UI para criar o vínculo (a feature é inalcançável pela tela)

**Encontrado em uso real, 29/09/2026.** O usuário vinculou um EGP no app e tentou vê-lo como `Desatualizado`. Não aconteceu — e não podia acontecer.

**Diagnóstico:** o único botão de vínculo na tela é o `AtualizadoLinkButton`, que grava **`egp_atualizado_key`** (o link da ABA antiga, que aponta para a chave da versão). O vínculo novo — **`egp_vinculo_tipo` + `egp_sucessor`**, que aponta para o **projeto do corpus** e é o único que deriva `Desatualizado` — não tem nenhuma UI: `grep` por essas duas colunas no `frontend/src/` inteiro devolve **zero**.

Medido no ambiente: `egp_atualizado_key` com **12 linhas** preenchidas (2 gravadas hoje às 12:53, pelo usuário); `egp_sucessor` com **0**.

Construímos o motor (módulo puro, colunas, guardas, derivação, denominador, Kanban, funil) e **não construímos a ignição**. O agente do ticket 07 sinalizou isso no relatório dele ("não existe hoje nenhuma UI para criar o vínculo; os campos só existem no PATCH") e não virou ticket na hora.

**Consequência:** toda a série de tickets 03–15 está inalcançável pela interface. Nada disso aparece para a gestão sem passar por `PATCH` na mão.

**Blocked by:** None

**Status:** ENTREGUE (29/09/2026, commits 69abdbd7)

- [ ] Dá para criar o vínculo pela tela: escolher o **tipo** (`Atualizado` · `Substituído` · `Unificado`) e apontar o **sucessor**, que é um projeto do corpus (não a chave da aba)
- [ ] Dá para **desfazer** o vínculo, e desfazer devolve o status real (§3.2.6)
- [ ] As 4 guardas do servidor aparecem como erro legível, não como falha silenciosa: tipo inválido, não-gestão, sucessor fora do corpus, EGP já `Migrado`
- [ ] `Desatualizado` **não** é oferecido no seletor de status — é derivado, e o backend recusa gravá-lo
- [ ] A diferença entre `egp_atualizado_key` (link da aba) e `egp_sucessor` (projeto do corpus) fica clara para quem usa, ou as duas coisas viram uma só
- [ ] Os 12 `egp_atualizado_key` já gravados são reconciliados ou explicitamente deixados como estão (ver ticket 17)

# 16: Concluir uma ex-dependência faz o total de EGPs SUBIR

**O achado (28/09/2026, medido em prod):** o total saiu de **192 para 194 às 14:03 de hoje**, quando duas ex-dependências foram marcadas como `Migrado` com 7 segundos de diferença (`Cobranças__Valida_carga_v1_cp` e `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1`).

Causa: o critério "189" conta a ex-dependência **só se ela tiver etapa real**, e `Migrado` é etapa real. As **14** ex-dependências que hoje contam estão **todas** em `Migrado` — nenhuma numa etapa intermediária. Ou seja, na prática o contador de ex-dependências é "quantas já foram migradas", e ele sobe quando o trabalho termina.

Decomposição atual: 168 base + 12 dependências = 180 no recorte; + 14 ex-dependências contabilizadas (de 29 totais) = **194**.

**Não é bug** — o critério faz o que foi desenhado para fazer. Mas o efeito é contraintuitivo: a liderança vê "o total a migrar subiu" no dia em que dois EGPs foram migrados. É a mesma classe de surpresa que a decisão da categoria `extra` (28/09) foi criada para evitar em outro ponto.

**Blocked by:** None — mas é régua fechada, e mexer exige decisão da gestão.

**Status:** RESOLVIDO pelo ticket 19 (29/09/2026)

Caminhos possíveis, nenhum escolhido:
- [ ] Aceitar e **anunciar** (o total subiu de X para X+1 porque a ex-dependência Y foi migrada)
- [ ] Contar a ex-dependência desde que ela entra no recorte, não quando ganha etapa — total estável, mas muda a régua fechada em 2026-08-10
- [ ] Tirar ex-dependência do total e dar a ela um contador próprio, como foi feito com os `extra`

---

## Resolvido sem escolher nenhum dos 3 caminhos

A **linha de base congelada** (ticket 19, commit `0c4dc28c`) eliminou a classe inteira do problema: o denominador e uma lista fixa de 193, entao concluir uma ex-dependencia nao muda o total. Nenhum dos tres caminhos registrados aqui precisou ser escolhido.

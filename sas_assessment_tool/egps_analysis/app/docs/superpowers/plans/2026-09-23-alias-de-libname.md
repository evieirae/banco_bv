# Alias de libname — a tabela física vira a unidade de input (plano)

> Decisão e alternativas rejeitadas: `docs/adr/0003-alias-de-libname-como-unidade-de-input.md` (raiz do repo).
> Precedente de desenho: ADR 0002 + `app/backend/familias.py` (famílias de safra).
> Estado em 23/09/2026: **nada implementado**. O mapa de decisão já existe em prod
> (`sas_input_alias_canonico`, 85 grupos / 186 linhas) e está **inerte** — nada o lê.
> Levantamento: `egps_analysis/docs/analises/inputs_homonimos_libname_2026-09-23.csv`.
> Planilha de escolha por grupo: `unificacao_escolha_alias_2026-09-23.csv`.

**Goal:** `/infogrc/convsimu/TBSIMULACOES` é **1 input**, não 3. As 3 linhas
(`CONVSIMU`, `INFCVS`, `MIS2`) continuam no banco como evidência de quem lê com qual
apelido, mas nenhuma superfície de contagem volta a tratá-las como trabalho separado.
Efeito medido: 10.188 linhas vivas → 10.087 unidades (−101); no escopo Indicium, 56
linhas em 25 grupos, 25 delas excedente.

**Architecture:** o mesmo desenho das famílias de safra, com uma diferença que simplifica
tudo — aqui a regra **não é derivada**, é lida de uma tabela. `familias.py` precisa de
régua de data, overrides curados e guarda de ≥2 membros porque a família é inferida do
nome; o grupo de alias já está resolvido em `sas_input_alias_canonico`, com um canônico
por grupo garantido por invariante. Isso elimina a classe inteira de bugs de regra e
troca por uma dependência de dado: se a tabela estiver vazia ou desatualizada, o app
simplesmente não colapsa nada (degrada para o comportamento de hoje).

A unidade de agrupamento é `chave_canonica_alvo`. Onde `familias.py` expõe
`fam_key(row)`, o módulo novo expõe `alvo(chave) -> chave` com fallback identidade.

---

## Invariantes que o código pode assumir

Garantidos pelo bloco 2 do `mapa_alias_canonico_2026-09-23.sql`, todos verificados = 0 na
carga inicial. Um teste tem de reverificá-los a cada leitura da tabela, porque ela é
editável à mão:

1. exatamente **um** canônico por grupo;
2. todo `chave_canonica_alvo` aponta para uma linha que é canônica (`alvo_que_nao_e_canonico = 0`);
3. **sem cadeia de dois saltos** — alias nunca aponta para alias (`cadeia_de_dois_saltos = 0`);
4. toda linha ativa tem `path_fisico` preenchido.

O invariante 3 é o que permite resolver com um `JOIN` só, sem fecho transitivo. Se algum
dia quebrar, a resolução tem de falhar alto — nunca resolver parcialmente.

---

## Tickets

### 01 — `backend/alias_canonico.py`, a regra única
Módulo novo, espelhando a forma de `familias.py`: geradoras de SQL e gêmeas em Python no
mesmo arquivo, para divergência aparecer. Carrega `sas_input_alias_canonico` (só
`ativo = true`), valida os 4 invariantes com `strict=True` e expõe:

- `alvo_sql(col)` → expressão SQL que resolve a chave para o canônico (LEFT JOIN + coalesce);
- `py_alvo(chave)` → gêmea em Python para a agregação em memória;
- `aliases_de(chave_alvo)` → as N linhas do grupo, para o fan-out e para o drawer.

Flag `ALIAS_CANONICO` (default **off**), no molde de `FAMILIAS_SAFRA`. Desligada, tudo
resolve para identidade e o app se comporta como hoje.

**Verifica:** teste que, com a flag off, toda superfície devolve exatamente os números de
hoje; e que a carga com um invariante quebrado levanta erro em vez de resolver parcial.

### 02 — contagem nas superfícies de universo
`/api/inputs`, `/api/resumo`, `/api/landing`, funil de ingestão e funil por área passam a
contar por `chave_canonica_alvo`. Exibição usa o nome do canônico.

**Verifica:** com a flag on, universo vivo 10.188 → 10.087; escopo Indicium cai 25. Sem a
flag, os dois números voltam iguais aos de hoje.

### 03 — contagem nas superfícies de progresso
Prontidão por EGP, priorização/ondas e bloqueio transitivo. Aqui mora o risco: o EGP que
lê `INFCVS.TBSIMULACOES` tem de passar a depender do input colapsado, senão volta a
existir divergência entre o que o EGP vê e o que a fila conta.

**Verifica:** zero grupos com alias resolvido e alias pendente ao mesmo tempo — a mesma
consulta do bloco 3 do `unificacao_estado_libname_2026-09-23.sql`, que hoje dá 0 por
patch de dado e passaria a dar 0 por construção.

### 04 — escrita por fan-out
`PATCH /api/inputs` numa linha colapsada grava nas N linhas do grupo, uma auditoria por
linha, todas no mesmo instante. `/api/audit` agrupa na consulta (chave do grupo + campo +
valores + autor + instante) e devolve `n_aliases`, com o `LIMIT` **depois** do `GROUP BY`
— é o bug que a família de safra já pagou em 21/09 (39 linhas de auditoria comendo o
limite da aba Histórico).

**Verifica:** editar `TBSIMULACOES` grava 3 auditorias e mostra 1 linha no Histórico.

### 05 — publish nunca toca a tabela
`publish_to_databricks.py` não cria, não dropa, não reescreve `sas_input_alias_canonico`.
Ela é irmã de `sas_gestao_status`/`sas_gestao_datas` nesse aspecto.

**Verifica:** rodar o publish em dev e conferir que `describe history` da tabela não
registra operação nova.

### 06 — UI do input colapsado
Nome exibido = canônico. Os aliases absorvidos aparecem no drawer, no molde de
`paths_fisicos` (lista, não linha própria). Badge com o número de aliases quando > 1.

**Verifica:** `TBSIMULACOES` aparece uma vez na lista, com badge 3, e o drawer lista
`CONVSIMU`, `INFCVS`, `MIS2` com os EGPs de cada um.

### 07 — re-seed e revisão humana
Script que re-roda a proposta depois de cada publish (aliases novos entram, grupos que
sumiram do corpus viram `ativo = false`), respeitando `origem_decisao = 'revisao_humana'`.
Sem isso o mapa envelhece em silêncio.

**Verifica:** rodar duas vezes seguidas não altera nenhuma linha (idempotente), e uma
linha marcada como revisão humana sobrevive ao re-seed.

### 08 — docs e subida
`CLAUDE.md` → armadilhas; `app/README.md` → Decisões de design; `CONTEXT.md` → glossário.
Dev primeiro, prod via PR, flag ligada em separado do merge.

---

## Ordem e paralelismo

01 é pré-requisito de tudo. 02 e 03 são paralelos depois dele. 04 depende de 03 (o
fan-out precisa saber o grupo que a contagem usa). 05, 06 e 07 são independentes entre si
e podem ir junto com 04. 08 fecha.

---

## O que este plano NÃO faz

1. **Não toca no balde B** (92 grupos, paths distintos). São tabelas diferentes que só
   dividem o nome — `DIAS_UTEIS` em 6 diretórios são 6 calendários. Colapsar ali é o
   falso-merge que a identidade por path existe para evitar.
2. **Não toca no balde C** (72 grupos sem path completo). Entra quando o resolvedor de
   libname preencher o path, e a decisão de incluir é medição nova, não extensão desta.
3. **Não colapsa o grafo.** Linhagem, produtor canônico e casamento input↔output seguem
   por alias. O colapso é de contagem, exibição e estado.
4. **Não mexe em `categoria='arquivo'`/`'script'`.** A chave de arquivo é o basename, que
   é outro problema de identidade — não este.
5. **Não desfaz a unificação de estado de 23/09.** Enquanto a flag estiver off, é ela que
   segura a prontidão honesta. Quando o colapso existir, o estado por alias vira
   irrelevante para exibição, mas continua sendo onde o dado mora.

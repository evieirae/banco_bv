# Famílias de safra — a família vira a unidade de input do app (as-built)

> Decisão e alternativas rejeitadas: `docs/adr/0002-familia-de-safras-como-unidade-de-input.md` (raiz do repo).
> Termos: `CONTEXT.md` §Famílias de safra. Regra canônica: `app/backend/familias.py`.
> Estado em 15/09/2026: tickets **01–08 prontos**, **09 parcial** (docs + validação no dev feitos; PR e subida
> aguardam janela — a mudança de safra **não** subiu junto com a `feat/bv-subarea`). Tudo atrás da flag
> `FAMILIAS_SAFRA`, **ligada em prod a partir de 17/09/2026** (antes disso o app contava safra a safra). Branch: `wip/safra-families` (worktree `.worktrees/safra-families`).

**Goal:** uma safra deixa de ser um input. `GRIMALDI.CARGA_MASSIFICADOS` é **1 input** — não 58 — e é ela que
conta na fila, recebe etapa/status/responsável e vira pedido de ingestão. As 58 linhas continuam no banco como
evidência (quem lê qual safra, path físico, profundidade necessária), mas nenhuma superfície do app volta a
tratá-las como unidade de trabalho.

**Architecture:** `app/backend/familias.py` é a regra única (token de data em qualquer posição, ≥2 membros,
overrides curados em `familias_overrides.json`, só `categoria='tabela'`) e serve tanto o backend quanto o
`publish_to_databricks.py` (import por `sys.path`, sem segunda cópia). `app/backend/input_state.py` guarda os
predicados de estado em SQL **e** os gêmeos em Python no mesmo arquivo, para que divergência apareça. No
`main.py`: derivação ao vivo (`_familias_corpus`, `_fam_sql_egp`, `_agrega_familias`), escrita por fan-out
(`_patch_familia`), profundidade necessária por par (`sas_egp_input_periodo`, só gestão) e ingerida por família
(`sas_familia_ingestao`, qualquer analista) — ambas com tabela de auditoria irmã, criadas pelo backend e nunca
dropadas pelo publish.

## Números medidos (prod `bv_dev_db.monitoramento_sas`)

**Estruturais** — vêm do pipeline, só mudam em publish; servem de critério de aceite direto:

| recorte | hoje | com família |
|---|---|---|
| escopo Indicium — linhas | 2.446 | 1.404 unidades (137 famílias) |
| universo — linhas | 10.451 | 7.568 unidades (348 famílias) |

> **Régua de data ampliada em 17/09/2026** (mês em português, `MMYY`, `DDMMYY`, `DDMMYYYY`,
> `YYYY.MM`, epoch — da branch `feat/vintage_analysis`): +45 famílias, 0 desfeitas. O que
> está EM PROD hoje é a régua anterior (1.438 unidades / 126 famílias); estes números valem
> a partir do próximo merge. Ver ADR 0002 §Régua de data ampliada.

> Medido em prod em 17/09/2026. Os primeiros números deste plano diziam 1.437/95 e 7.795/304:
> as **famílias** vinham da régua antiga ("≥2 membros no recorte"), e a unidade extra em cada
> recorte é a exceção curada do `B_GERAL.DIAS_UTEIS_2026`. A régua válida é a do CORPUS, que é
> a que a API usa (invariante 3 de `familias.py`).

**Vivos** — pendentes derivam da edição diária dos analistas. Em 14/09/2026: escopo **1.220 → 527**, universo
**8.292 → 5.998**. Dois dias antes eram 1.209 → 516: 11 linhas saíram de terminal (9 `Concluído`→`Block`,
2 `Sanitizado`→`A Iniciar`). **Não use número de pendente escrito em ticket como aceite** — re-meça no dia.

No corpus local a regra da fase 1 produz **293 famílias** e **819 pares (EGP, família)**, dos quais 431 leem
≥2 safras — 182 contíguos, 189 esparsos, 60 com ano solto. Profundidade por par: mediana 8 meses, p90 39, máx 103.

Caso-bandeira: `Cobranças__ACOMPANHAMENTO_DESCONTO` sai de 202 para **20 inputs**, de 188 para **6 faltando**,
e a prontidão de 6,9% para **70%** — o painel de bloqueio deixa de listar 188 nomes e lista 6.

## Tickets (todos com evidência nos commits)

| # | título | estado |
|---|---|---|
| 01 | Prefactor — regra de família + exceções curadas | ✅ |
| 02 | Aba Inputs lê por família | ✅ |
| 03 | Aba Inputs escreve por família (fan-out + auditoria por safra) | ✅ |
| 04 | Fila e cards contam família (aba Resumo) | ✅ |
| 05 | Superfícies de EGP contam família (readiness, ondas, bloqueio) | ✅ |
| 06 | Métricas paralelas `inputs_familias` / `inputs_pendentes_familia` no publish | ✅ |
| 07 | Profundidade necessária por (EGP, família) | ✅ |
| 08 | Profundidade ingerida + avisos informativos | ✅ |
| 09 | Validação no dev, docs e subida | ◐ docs + validação ok; PR/subida na janela |
| 10 | Fase 2 — backlog (não pronto para agente) | ⬜ |

## Refinamentos vindos do uso (pós-09)

- **`B_GERAL.DIAS_UTEIS_2026` saiu por exceção curada, não por regra** (16/09/2026). O padrão
  `{tabela corrente, um único ano}` tem 10 casos no corpus e eu tratei como regra primeiro;
  o BV corrigiu: só o `DIAS_UTEIS` é tabela diferente, as outras 9 são safra. A guarda genérica
  teria separado 9 famílias certas. Está em `familias_overrides.json` (`separar` + motivo).
  Universo 304 → 303 famílias; escopo 127 → 126. Ver ADR 0002 §Exceção curada.
- **Filtro "só safras" na aba Inputs** — marcador `de_safra` vem do backend (`_marca_safra`) nos
  DOIS estados da flag, então o filtro serve prod também. Escopo Indicium: 1.136 das 2.446
  linhas são safra (desligada) = 123 famílias (ligada).
- **Nome de exibição `..._{SAFRA}`** — a chave da família apaga o token, então o template é
  derivado de um MEMBRO (`familias.nome_com_marcador`). Membro sem data não ganha o rótulo
  (senão a família aparece com nome de input solto). `artifact` segue sendo a chave, e é o que
  vai para ordenação e export.
- **Lista de safras do detalhe mostra o nome completo** da tabela, não só o token.

## Validação (ticket 09, `monitoramento_sas_dev`, 15/09/2026)

Dois scripts, de propósito medindo por fora e por dentro:

- `egps_analysis/scripts/verifica_familias.py` — read-only em SQL, paridade da regra e contagens.
- `egps_analysis/scripts/verifica_familias_api.py` — chama a API por dentro, nos dois estados da flag, e
  confere 4 coerências (card == dataset == universo do funil == tabela de origem; funil por mês == funil +deps).
  Recusa rodar contra o schema de prod.

| | flag OFF | flag ON |
|---|---|---|
| aba Inputs | 2.408 linhas (grão safra) | **1.378 unidades, 125 famílias** |
| landing (escopo / a ingerir) | 2.297 / 1.189 | **1.341 / 533** |
| funil — universo | 2.297 | 1.341 |
| Resumo | 2.297 | 1.341 |
| funil por mês | 1.544 | 833 |
| readiness (Σ n_inputs / Σ faltam) | 3.804 / 1.850 | 2.979 / **1.025** |

As 4 coerências passam **nos dois estados**. Neutralidade com a flag OFF foi verificada linha a linha
(landing, deps, funil, tabela de origem, 208 EGPs com 0 divergências; 0 divergências Python↔SQL em 10.451 linhas).

**Duas réguas que parecem divergência e não são** — custaram caça a fantasma, ficam registradas:

1. **Família por corpus × por recorte.** Contar "unidades com ≥2 membros **no recorte**" dá 98 no escopo;
   a API conta família segundo o **corpus** e dá 125. A régua certa é a do corpus (invariante 3 de `familias.py`):
   resolver sobre o recorte faz a mesma tabela ser família num escopo e input solto noutro. O
   `verifica_familias.py` foi alinhado à régua da API.
2. **Pendente em grão monitor × universo por vínculo.** O script conta pendentes no grão de
   `sas_inputs_monitor` (544) e o card da landing conta o **universo por vínculo ativo** (`_ch_vinculo_ativo`,
   533). Números diferentes, ambos certos — o script imprime a nota.

## Refinamentos de 21/09/2026 (branch `fix/audit-fanout-familia`)

Dois vieram do uso da Fran e de uma varredura do inventário; ambos com teste e medidos contra prod.

1. **Histórico colapsa o fan-out.** Uma edição de etapa/status em `CARNEIRO.BASE_3040_{SAFRA}` gravou 39 linhas
   em `sas_inputs_audit` (19 de etapa, 20 de status, mesmo microssegundo). `/api/audit` passou a agrupar na
   consulta por chave de família + campo + valores + autor + instante, devolvendo `n_safras`, com o `LIMIT`
   depois do `GROUP BY` — antes uma edição comia o limite da aba Histórico. `test_audit_fanout.py` (6 testes)
   trava os cinco eixos do `GROUP BY`, a presença da chave de família e a ordem `GROUP BY` → `LIMIT`.
2. **21 exceções para nomes que perderam a data.** `PERF_CL.PAGOS_CYBER_`, `CARNEIRO.BASE_3040_` e outros 19
   nunca achavam as próprias safras: no SAS a data vem de macro (`&DAT_EXEC.`, `&SAFRA.`, `&REF.`) ou o EGP lê a
   família num curinga (`SET ..._:`, `..._%`), e o extrator deixa só o separador solto. 17 por macro, 4 por
   curinga, todos com a evidência no motivo. A guarda de `juntar` passou a aceitar **um** membro (ver ADR 0002).
   Efeito: 1.356 → 1.343 unidades e 441 → 428 pendentes no escopo + deps.

Levantamento completo em `egps_analysis/docs/analises/BV_Migracao_SAS_Safra_Sem_Data_2026-09-21.csv`: 89
candidatos, 49 com separador solto no fim (21 com família), 2 com macro crua no nome e 38 com separador
duplicado no meio. **O terceiro grupo não é safra** — `DT_REF._0`, `PRODUTO._EST1`,
`_PEPR_RA.BASECUBO202506._4040` são macro usada como LIBNAME. É conserto de extrator, não exceção curada, e
entra no backlog abaixo.

## Fase 2 — backlog (ticket 10, não pronto para agente)

- Materializar a família no publish (hoje é tudo derivado ao vivo).
- Famílias de `arquivo`/`script` — **medido em 17/09/2026 e não vale a pena agora**: o path passou a ser publicado
  (2.650/2.650 cobertos) e produz só 6 famílias / 94 arquivos, 6 no escopo. Decisão documentada, não pendência.
- Casamento com a chameleon no grão de família — precisa do fato que só o BV tem: o nome do catálogo
  depois da ingestão.
- Aba Outputs por família.
- Macro usada como LIBNAME no extrator (38 casos, `DT_REF._0` / `PRODUTO._EST1`): hoje viram input
  fantasma no inventário. Conserto é no extrator + republish, não em `familias_overrides.json`.
- Aba EGPs Atualizados ainda conta por carga (1.191 pares → 932 por família).

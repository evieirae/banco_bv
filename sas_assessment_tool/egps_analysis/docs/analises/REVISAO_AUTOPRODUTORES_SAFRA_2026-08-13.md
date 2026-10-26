# Revisão dos EGPs auto-produtores com lente de safra: o que ingerir e o que sanitizar

**Data:** 2026-08-13
**Base:** `text_egps/` + `06_prontidao_tabela.csv` (extração de 2026-08-12), corpus completo (1.740 EGPs)
**Script:** `docs/analises/revisao_autoprodutores_safra.py`
**Complementa:** `BV_Migracao_SAS_Analise_Inputs_Autogerados_2026-08-12.md`

| Arquivo | Conteúdo |
|---|---|
| `revisao_autoprodutores_pares_2026-08-13.csv` | 13.178 pares (EGP × input tabela SAS/Local) com classificação e ação |
| `revisao_autoprodutores_triagem_2026-08-13.csv` | 7.046 inputs distintos, ação consolidada (a mais conservadora ganha) |
| `BV_Migracao_SAS_Inputs_Sanitizaveis_2026-08-13.csv` | **lista de validação da gestão** — 1.045 inputs do escopo em tiers 1/2/3, com etapa atual no app (§5) |
| `inputs_sanitizaveis_tiers.py` | gera o CSV acima cruzando a classificação com a aba Inputs em produção |

---

## 1. O que esta revisão acrescenta

A análise de 2026-08-12 detecta auto-produção por **chave idêntica**: o EGP consome e produz
exatamente a mesma tabela. Ela não vê o padrão de **safra irmã**, que é o mais comum no corpus:

```
PERFORMANCE_CL_202603  cria  PERF_CL.PAGOS_CYBER_202502
                       lê    PERF_CL.PAGOS_CYBER_202602   <- chave distinta, MESMA família
```

O produtor dessa leitura é o próprio EGP numa execução anterior. O grafo não fecha o ciclo
temporal, então o input cai como "dep. produtor ausente" e entra na fila de ingestão. Está
funcionalmente certo (alguém precisa colocar o dado no destino), mas a **ação é diferente**:
é backfill único de histórico, não ingestão recorrente de sistema-fonte.

## 2. Método

**Regra do criador.** `PERMANENT OUTPUTS` no cabeçalho é o conjunto de *todas* as escritas
permanentes; `NON_CREATOR_OUTPUTS` é o subconjunto que só apensa/atualiza (`INSERT INTO`,
`PROC APPEND BASE=`, `UPDATE`, `MODIFY`, `DELETE FROM`, sem nenhum sinal de criação). As duas
listas **não são disjuntas**. Criador real = `PERMANENT OUTPUTS − NON_CREATOR_OUTPUTS`, igual ao
que o orquestrador usa. Quem só apensa não é produtor e a leitura dele **não** é sanitizável.

**Identidade path-aware.** A chave é `(path físico, membro)`, nunca o alias do libname
(`REFAZ_LINHAGEM_PATH.md`). O path vem da coluna `path` do 06 com fallback em
`DETECTED_LIBNAMES`. Isso importa na prática: em `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO` os
aliases `PRIVADO` e `NPRIVADO` apontam para `/…/PJ_PRIVADO/Nova_Carga` e `BKCONSG`/`BACKUP` para
`/…/PJ_PRIVADO/Backup` — o mesmo alias `PRIVADO` chega a ser definido em dois paths.

**Família de safra.** Tokens `YYYYMM`/`YYYYMMDD` com mês válido são mascarados para `<D>`:
`PAGOS_CYBER_202502` → família `PAGOS_CYBER_<D>`. A validação de mês evita casar `REDIST_4041`.

**Duas populações de input.** `EXTERNAL INPUTS` (a fila do inventário, já sem os same-script
re-reads) e `INTERNAL READS` (tabelas permanentes que o EGP lê e escreve — o extractor as tira
da fila, mas o inventário de inputs do app as mantém; é a população dos 243).

## 3. Números

**543 EGPs auto-produtores** no corpus (108 no recorte Indicium) — contra 97 da análise anterior,
que só via a chave idêntica dentro do `indi_deps`.

| Classificação | Pares | Inputs | Inputs lidos por EGP do escopo Indicium | Ação |
|---|---:|---:|---:|---|
| `auto_mesmo_run` | 2.457 | 1.734 | 310 | **Sanitizar** |
| `calendario` | 39 | 12 | 9 | **Sanitizar** (date spine no dbt) |
| `auto_safra_irma` | 492 | 261 | 55 | **Backfill único** |
| `outro_egp_cria_safra_irma` | 1.377 | 795 | 458 | Backfill único + `ref()` do produtor |
| `outro_egp_cria` | 1.811 | 519 | 159 | `ref()` — migrar o produtor |
| `acumulador_compartilhado` | 132 | 64 | 11 | Carga inicial — **não sanitizar** |
| `ingestao_snapshot_datado` | 2.505 | 1.764 | 688 | Ingerir 1x (candidato a seed) |
| `ingestao_recorrente` | 3.888 | 1.605 | 421 | **Ingerir** (fonte real) |
| `membro_dinamico` | 477 | 292 | 84 | Resolver macro antes de decidir |

Olhando só os 8.765 pares de input dos 543 auto-produtores: 28,4% sanitizáveis, 17,8% backfill,
10,4% `ref()`, 40,1% ingestão real, 3,3% a resolver.

`auto_safra_irma` concentra em Cobranças (183 inputs), Riscos (59), Atacado (11), Crédito (6),
Finanças (2). Os maiores casos: `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO` (117 pares, 7 famílias),
`processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` (94), `Valida_carga_v1_cp` (52),
`Calculo_PDD_v3` (38).

## 4. Ressalvas

- **Chave por alias em 25% dos pares** (3.357/13.178), quando o libname não resolve para path.
  As classes que geram ação de descarte são pouco afetadas — `auto_safra_irma` 3% alias,
  `calendario` 0%, `auto_mesmo_run` 16% — mas `outro_egp_cria` (41%) e `ingestao_recorrente`
  (42%) dependem bastante disso. Nessas duas a ação é conservadora (ingerir / migrar o produtor),
  então o erro não descarta dado.
- **A máscara de família junta granularidades.** `X_202502` (mensal) e `X_20250213` (diária)
  caem na mesma família. Para a ação "backfill" isso é inócuo; não use a família como
  identidade de tabela.
- **`INTERNAL READS` é proxy forte, não garantia**: 2.440 dos 2.538 pares batem com um criador
  registrado. Sobram 3 inputs lidos sem nenhuma escrita de criação no cabeçalho
  (`INSIGHT.TBBRUTA`, `SHAREATA.TBALERTAINSIGHT`, `CAROL.PUBL_AJUIZAMENTO_COMP`) — o guard
  conservador do extractor não marca escrita sob outro alias do mesmo path. Ficaram como
  `ingestao_recorrente` de propósito: sem evidência de criação, não se sanitiza.
- **`acumulador_compartilhado` = 64 inputs**, não zero. Corpus-inteiro e path-aware, todas as 83
  chaves apensadas têm criador em algum lugar; os 64 são os casos em que o **próprio EGP leitor**
  só apensa. Nenhum é descartável — o histórico precisa de carga inicial.
- **A classe `calendario` subconta o calendário.** Um input de calendário que tem produtor no
  corpus cai em `outro_egp_cria`, que vence na ordem de precedência. Varrendo o padrão em todas
  as classes há **16 inputs de calendário**, e o maior deles é justamente um `outro_egp_cria`:
  `B_GERAL.DIAS_UTEIS`, lido por **66 EGPs**. Consolidar os 16 num único date spine com feriados
  é a maior alavanca isolada da lista, e independe de migrar o EGP que hoje os produz.
- Comparação com os 243 da análise anterior não é 1:1: recortes diferentes (222 nomes curtos do
  `indicium_scope_222_projetos.csv` aqui vs 186 EGPs do `indi_deps` lá) e critério de
  exclusividade de criador diferente. Os 310 `auto_mesmo_run` no escopo Indicium são o número
  comparável.

## 5. Do diagnóstico à ação: tiers e cruzamento com a aba Inputs

As classes da §3 são diagnóstico. Para virarem ação de gestão elas foram agrupadas em três
tiers pela **condição** que precisa ser satisfeita — e cruzadas com a etapa atual de cada input
na aba Inputs de produção (`inputs_sanitizaveis_tiers.py` → `BV_Migracao_SAS_Inputs_Sanitizaveis_2026-08-13.csv`,
1.045 linhas, uma por alias de tabela lido por EGP do escopo Indicium).

| Tier | Classes | Condição | Inputs |
|---|---|---|---:|
| **1** | `auto_mesmo_run` | nenhuma — o próprio leitor cria e lê no mesmo run | 310 |
| **1c** | `calendario` | nenhuma — recriar como date spine no dbt | 10 |
| **2** | `outro_egp_cria`, `outro_egp_cria_safra_irma` | **migrar o produtor** (vira `ref()`, não ingestão) | 659 |
| **3** | `acumulador_compartilhado`, `auto_safra_irma` | **carga inicial / backfill** — não sanitizar | 66 |

**Acionável hoje: 201 inputs.** Dos 320 do tier 1/1c: **201 estão como `A Receber`** e podem ir
para `Sanitizado`; 62 já constam `Modernizado` (nada a fazer); e 57 não têm linha na aba Inputs —
provavelmente fora do publish atual, e vale conferir antes de fechar o número.

No tier 2, **495 dos 659 têm o produtor dentro do plano de migração** — para esses não há ingestão
a fazer, o dado passa a vir do modelo dbt do produtor. Os 164 restantes têm produtor fora do plano:
ou o produtor entra, ou a tabela precisa ser ingerida de fato.

### 5.1 A triagem de 2026-08-12 se confirma

Os **200 inputs marcados como Tier 1** em 12/08 ("descarte direto — criador exclusivo") foram
reconferidos contra a classificação path-aware de corpus completo. **Os 200 se sustentam**: em
todos há um criador dentro do plano de migração, então nenhum exige ingestão e a recomendação
original — marcar `Sanitizado` — continua válida.

A classificação mais ampla acrescenta uma nuance de modelagem, não de fila:

| Perfil dentro dos 200 do Tier 1 | Inputs |
|---|---:|
| Auto-produção pura: só o próprio EGP lê e escreve | 148 |
| Auto-produção **com outros consumidores** — vira handoff interno | 51 |
| Fora do escopo da análise de tabelas (é um `.txt`) | 1 |

Nos 51, a tabela é criada e relida pelo próprio EGP no mesmo run, mas **outros EGPs também a
consomem**. Exemplo: `CARNEIRO.UF_CPF` é criada e lida por `Atualiza_UF_Cartoes`, e mais 3 EGPs a
leem. Ninguém precisa ingeri-la e o criador está no plano — porém, ao migrar, ela não pode virar
uma tabela temporária interna do modelo: precisa ser um modelo dbt materializado, referenciado por
`ref()` pelos consumidores. É uma instrução para quem for converter, não uma mudança de tier.

### 5.2 Seis inputs marcados Sanitizado que merecem revisão

Seis inputs do **tier 3** (precisam de carga inicial) já constam como `Sanitizado` no painel,
marcados manualmente ao longo de julho. Nenhum deles foi detectado como disponível
automaticamente, então a marcação reflete uma decisão de análise, não a existência do dado:

| Input | Classe | Justificativa registrada |
|---|---|---|
| `ZSHARE.AUX_BASE_ACORDOS_DIA` | acumulador | "Despriorizado, pq o projeto que consome esse dado foi despriorizado" ✔ |
| `RG_AGRAC.AUX_HIST_ENVIO_AC` | acumulador | — |
| `PERF_CL.RESULT_DIST_CL_202603` | safra irmã | — |
| `ADAMOR.CARTAO_BAT_20251113` | safra irmã | — |
| `ADAMOR.CARTAO_BAT_20251119` | safra irmã | — |
| `ADAMOR.SOLAR_BAT_TOTAL_20251113` | safra irmã | — |

O primeiro tem motivo válido e documentado (o consumidor foi despriorizado). Os outros cinco não
têm observação registrada — podem estar certos pelo mesmo motivo, mas o histórico do painel não
permite confirmar. Vale revisar antes de tratar como resolvido: se algum desses processos voltar
ao plano, o histórico não existirá.

---

## 6. Reprodutibilidade

```bash
cd egps_analysis && python docs/analises/revisao_autoprodutores_safra.py 2026-08-13
```

Roda offline sobre `text_egps/` e `06_prontidao_tabela.csv` — não precisa de Databricks. Para
cruzar com o status humano da aba Inputs (Sanitizado/Disponível já marcados), use
`script_inputs_autogerados.py`, que lê o app.

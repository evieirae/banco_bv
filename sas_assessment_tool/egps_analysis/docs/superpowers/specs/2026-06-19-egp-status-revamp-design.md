# Design — Revamp do status de EGP (vocabulário + status na lista + remover Progresso)

**Data:** 2026-06-19
**Componente:** `egps_analysis/app` (frontend React/TS + backend FastAPI) + migração única de dados em `bv_dev_db.monitoramento_sas.sas_egp_pipeline`
**Status:** aprovado para implementação

## 1. Objetivo

1. **Novo vocabulário** de status (escolha **manual**): mantém os atuais e **acrescenta** dois.
2. **Remover o funil "Progresso Projetos"** (mantém "Migração de Projetos" com suas 9 etapas, e Ingestão).
3. **Ver/editar o status do EGP na lista** (aba "EGPs" / `ReadinessView`) sem abrir o detalhe.

> **Decisões-chave (validadas):** o funil de Migração **continua idêntico** (9 etapas + lógica de empilhamento). **"Concluído" continua status escolhível.** A única lógica nova no funil: **Removido** e **Despriorizado e Contabilizado** viram **banda** (aparecem em todas as colunas). "Migrado" aparece só na coluna da sua etapa (verde "Concluído" antes).

## 2. Vocabulário (7 status manuais)

`STATUS_PROJETO` (idêntico em `pipeline.ts` e `main.py`):

| status | definição (vira tooltip) | mudança vs hoje |
|---|---|---|
| **A Iniciar** | habilitado, mas ainda não estamos trabalhando | recapitaliza `A iniciar` |
| **Em Andamento** | estamos trabalhando | recapitaliza `Em andamento` |
| **Concluído** | concluiu a etapa atual (verde) | **mantém** |
| **Block** | bloqueio para migração, mas o projeto continua no backlog | mantém |
| **Removido** | removido do backlog até a conversão, quando não houve ingestão | mantém |
| **Despriorizado e Contabilizado** | já trabalhamos na ingestão e foi despriorizado (qualquer etapa), **ou** validamos em DES mesmo sem ingestão | **novo** (substitui a derivação automática "Removido e Contabilizado") |
| **Migrado** | migrado | **novo** |

A distinção *Removido* ↔ *Despriorizado e Contabilizado* é **decisão manual** do analista (definições = guia).

## 3. Funil de Migração — empilhamento (`_funnel_bars`)

Single-pointer (cada EGP tem **etapa** + **status**). Conjunto novo `BANDS = {"Removido", "Despriorizado e Contabilizado"}`. Para um EGP na etapa de rank *i*, status *st*, em cada coluna *j*:

```
if st in BANDS:  k = st            # banda: aparece em TODAS as colunas
elif j < i:      k = "Concluído"   # etapa já vencida (verde)
elif j == i:     k = st            # status na etapa atual
else:            k = "A Iniciar"   # ainda não alcançada
```

- **Remove** a derivação antiga `"Removido e Contabilizado" (j<=i)` — agora Removido e Despriorizado e Contabilizado são bandas manuais distintas.
- "Migrado"/"Concluído" seguem o ramo normal (aparecem na etapa; verde antes).
- Headline **"N/230 migrados"** = EGPs com `etapa_migracao == "Migrado"` e status **não** em `BANDS` (5 com os dados atuais).
- O funil de **Ingestão** continua usando `_funnel_bars` (normalizar labels p/ `A Iniciar` / `Em Andamento` / `Concluído`).

## 4. Modelo de dados + migração

- `sas_egp_pipeline` **mantém todas as colunas**. Backend usa `etapa_migracao` + `status_migracao`; **para de usar** `etapa_progresso`/`status_progresso` (Progresso removido) — colunas vestigiais, não dropar.
- EGP **sem linha** = status efetivo **"A Iniciar"**.
- **Migração única (só recapitalização)** em `sas_egp_pipeline` (backup em `egps_analysis/_status_prod_backup/egp_pipeline.pre.json`):
  - `status_migracao = 'Em andamento'` → `'Em Andamento'`
  - `status_migracao = 'A iniciar'` → `'A Iniciar'`
  - `'Concluído'` / `'Block'` / `'Removido'` / `NULL` → **inalterados**.
  - Resultado nos 11: 6 Concluído · 1 Em Andamento · 1 Block · 3 nulos; headline migrados = 5 (etapa Migrado). `Migrado`/`Despriorizado e Contabilizado` ficam disponíveis p/ marcação manual futura.

## 5. Backend (`egps_analysis/app/backend/main.py`)

- `STATUS_PROJETO` = os 7 valores.
- `_funnel_bars`: adicionar `BANDS`; recapitalizar `"A iniciar"`→`"A Iniciar"`; remover o ramo `"Removido e Contabilizado"`. Continua servindo Migração **e** Ingestão.
- Ingestão: item label `"Em andamento"`→`"Em Andamento"`.
- `proj_funnel`: mantém p/ migração; remove o cômputo de progresso; `migr` exclui `BANDS`.
- `/api/funis`: retorna `{ migracao, ingestao }` (**remove `progresso`**).
- `/api/egp-pipeline` (PATCH): só migração — `{projeto, etapa?, status?}` (ignora/rejeita progresso). Valida `status in STATUS_PROJETO`. Mantém auditoria.
- `/api/egp-readiness`: `LEFT JOIN sas_egp_pipeline`; devolve `status` (`status_migracao` ou `'A Iniciar'`) + `etapa` por linha.
- `/api/egp` (detalhe): `pipeline` só `migracao: {etapa, status}`.
- `PIPELINE_PROJETO`: remove a chave `progresso`.

## 6. Frontend

- **`pipeline.ts`**: `STATUS_PROJETO` = os 7; `SEG`/`SEG_ORDER` cobrem os 7 (A Iniciar=cinza, Em Andamento=âmbar, Concluído=verde, Block=vermelho, Removido=`--seg-rem`, **Despriorizado e Contabilizado=teal (`--seg-remc` renomeado)**, **Migrado=verde-escuro (token novo)**). `PIPELINE_PROJETO` perde `progresso`.
- **`EgpDetailPanel.tsx`**: caixa de pipeline mostra **só Migração** (etapa + status com os 7); remove o bloco "Progresso Projetos"; tooltip com as definições no seletor.
- **`ReadinessView.tsx`**: **nova coluna "Status"** = dropdown inline (os 7, cor por `SEG`), grava via `egpPipeline({projeto, status})` sem expandir. `ReadinessRow` ganha `status`.
- **`FunnelChart.tsx`**: consome `SEG`/`SEG_ORDER` renomeados; sem mudança estrutural.
- **`ResumoView.tsx`**: remove o card do funil **Progresso Projetos**.
- **`WavesView.tsx`**: ajusta consumo de status/etapa (sem progresso).
- **`api.ts` / `types.ts`**: `egpPipeline({projeto, etapa?, status?})`; `FunisPayload` sem `progresso`; `ReadinessRow.status`; `EgpDetail.pipeline` sem `progresso`.

## 7. Deploy (gate humano)

**Sem republish** (código do app + 1 UPDATE de dados). Sequência:
1. **Migração de dados:** UPDATE de recapitalização em `sas_egp_pipeline` (regra §4), com re-snapshot antes/depois (`_status_prod_snapshot.py`).
2. **Deploy do app:** `npm run build` → `databricks sync` → `databricks apps deploy` (perfil `bv`, catálogo `bv_dev_db`).

## 8. Critérios de aceite

- Seletor (detalhe e lista) mostra os 7 com tooltip.
- Funil de Migração idêntico em etapas; **Removido e Despriorizado e Contabilizado aparecem como banda** em todas as colunas; "Migrado"/"Concluído" só na coluna da etapa; headline migrados = etapa Migrado (5/230).
- Aba EGPs: coluna Status visível e **editável inline**; persiste no reload.
- Landing: **sem** funil "Progresso Projetos"; Migração e Ingestão intactos.
- Após migração: `status_migracao` recapitalizado (Em Andamento), demais inalterados; re-snapshot confirma.
- `npm run build` (tsc strict) verde; backend `ast.parse` ok.

## 9. Testes

- **Backend:** `_funnel_bars` com fixtures (banda p/ Removido/Despriorizado em todas as colunas; taper p/ A Iniciar/Em Andamento/Concluído/Block/Migrado; verde Concluído nas etapas vencidas); `migr` exclui `BANDS`; validação de status no PATCH.
- **Migração:** UPDATE idempotente + verificação por re-snapshot.
- **Frontend:** `tsc -b && vite build` verde; smoke do dropdown inline + landing sem Progresso + funil com banda.

## 10. Fora de escopo

- Mudar a lógica de etapas do funil de Migração ou o funil de Ingestão.
- Derivar "Contabilizado" automaticamente (decisão: manual).
- Tocar na coluna `origem` (feature anterior) ou no `publish_to_databricks.py`.

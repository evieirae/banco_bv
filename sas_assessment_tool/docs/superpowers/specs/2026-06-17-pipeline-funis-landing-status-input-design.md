# Spec — Tracking de pipeline, novo status de input e 3 funis na landing

**Data:** 2026-06-17
**App:** `egps_analysis/app` (Painel de Modernização SAS — FastAPI + React, Databricks App OBO)
**Status:** aguardando revisão do usuário

## 1. Objetivo

Adicionar à landing (aba **Resumo**) três gráficos de funil de migração — espelhando os
mockups fornecidos — e o tracking que os alimenta:

1. **Funil de Migração SAS** (EGP, 9 etapas)
2. **Progresso Projetos** (EGP, 8 etapas) — segundo funil de projeto, distinto
3. **Funil de Ingestão** (input) — derivado do **status do input**

Além disso, trocar o vocabulário de **status de input** no Monitoramento para um lifecycle
de 7 estados, que passa a ser também a fonte do Funil de Ingestão.

## 2. Decisões já tomadas (respostas do usuário)

- **Fonte dos dados:** rastrear no próprio app (não importar de fonte externa).
- **Granularidade (EGP):** 1 etapa + 1 status por funil de projeto (single-pointer). O funil
  é derivado: etapas anteriores = Concluído, a atual = status do item, posteriores = A iniciar.
- **Funis de projeto:** os DOIS (Migração SAS e Progresso Projetos), com listas de etapas
  distintas ⇒ cada EGP tem 2 ponteiros (um por funil).
- **Status de projeto (5):** A iniciar · Em andamento · Concluído · Block · Removido. "Removido
  e Contabilizado" é derivado (Removido em etapa final), não editável.
- **Edição:** nos painéis existentes (EgpDetailPanel; status de input no Monitoramento).
- **Status de input (7):** Não recebido · Recebido · Priorizado · Em ingestão · Modernizado ·
  Sanitizado · Descartado. **O status É o funil de ingestão** (sem campo de etapa separado).
- **Modernizado** = `{Modernizado, Sanitizado}`. **Descartado** sai da conta de pendência.
- **Descartado:** excluído de toda métrica de pendência; **oculto por padrão** no filtro do
  Monitoramento (com opção de exibir); **nunca deletado**.
- **Denominadores:** dados vivos (escopo / inputs atuais), não os 231/2779 congelados.

## 3. A — Vocabulário de status de input

### 3.1 Novo conjunto (ordem do lifecycle)

```
0 Não recebido   1 Recebido   2 Priorizado   3 Em ingestão
4 Modernizado    5 Sanitizado            (— Descartado: terminal, fora do funil)
```

`STATUS_OPTIONS` (backend `main.py:61`) passa a:
`["Não recebido", "Recebido", "Priorizado", "Em ingestão", "Modernizado", "Sanitizado", "Descartado"]`.

### 3.2 Derivação "modernizado" / "a ingerir" / "descartado"

Expressão única (substitui as 6 ocorrências de `IN ('Disponível','Sanitizada')` —
`main.py` linhas 204, 238-239, 317, 586, 626, 672):

- `eff = coalesce(nullif(status_humano,''), status_auto_default)`
  onde `status_auto_default = CASE modernizada_auto WHEN 'Disponível' THEN 'Modernizado' ELSE 'Não recebido' END`.
- **modernizado** ⇔ `eff IN ('Modernizado','Sanitizado')`.
- **descartado** ⇔ `eff = 'Descartado'`.
- **a ingerir (pendência)** ⇔ `NOT modernizado AND NOT descartado`.

Definir um helper SQL (string) reutilizado em `/api/metrics`, `/api/landing`,
`/api/resumo`, `/api/inputs`, `/api/egp` para não repetir a regra.

**Preservação dos números atuais:** sem override humano, `Disponível→Modernizado` e
`A ingerir→Não recebido`, então "inputs a ingerir" continua 2902 até alguém editar.

### 3.3 Descartado — comportamento

- **Pendência:** já excluído por 3.2.
- **Totais ativos** (ex.: landing item 3 "Total inputs escopo", funil de ingestão): também
  excluem Descartado (input descartado não é mais escopo ativo). *(ponto a confirmar na revisão)*
- **Monitoramento:** `GET /api/inputs` ganha parâmetro `incluir_descartado` (default `false`)
  → `WHERE eff <> 'Descartado'` salvo quando o toggle estiver ligado. Front: checkbox
  "mostrar descartados" na FilterBar (default off). Nunca há DELETE — é só status.

### 3.4 Migração de valores antigos

Valores legados em `status_humano` (ex.: `Disponível`, `Sanitizada`, `Descartada`, `Em análise`)
quase não existem (a maioria é NULL → usa `modernizada_auto`). De-para aplicado **na leitura**
via um `CASE` de normalização (não reescreve a tabela): `Disponível→Modernizado`,
`Sanitizada→Sanitizado`, `Descartada→Descartado`, `Em análise→Recebido`,
`A ingerir→Não recebido`, `Em ingestão→Em ingestão`. Assim nenhuma linha "some" do filtro.

## 4. B/C — Funis e derivação unificada

### 4.1 Modelo de derivação (os 3 funis usam a mesma regra)

Cada item tem `(etapa_rank i, status st)`. Para cada etapa `j` do funil, o item contribui 1
segmento na barra `j`. Avaliação **top-down, primeira condição que casar vence**:

| ordem | condição | segmento |
|---|---|---|
| 1 | `st == Removido` e `j <= i` | **Removido e Contabilizado** (verde-escuro) |
| 2 | `st == Removido` (e `j > i`) | **Removido** (azul) |
| 3 | `j < i` | **Concluído** |
| 4 | `j == i` | `st` (Em andamento / Block / Concluído / A iniciar) |
| 5 | `j > i` | **A iniciar** |

**Coorte:** as barras mostram só itens que **entraram** no funil (têm linha de pipeline /
status definido). Itens nunca tocados entram só no denominador da barra de progresso.

- **Funil de Ingestão (input):** `i = rank do status` (0–5); `st = Concluído` se
  `eff ∈ {Modernizado,Sanitizado}`, senão `Em andamento`. Descartado é excluído (nem barra,
  nem denominador ativo). Não há "Block"/"Removido" para input.
- **Funis de projeto (EGP):** `i, st` lidos de `sas_egp_pipeline`.

### 4.2 Listas canônicas de etapas

**Funil de Migração SAS (EGP):**
`Projetos Habilitados · Pré-Working · Conversão do Código · Validação em DES · Aprv. PR ·
Implant. em PRD · Artefatos de GOV. · Validação da Área · Migrado`

**Progresso Projetos (EGP):**
`Conversão do Código · Validação em DES · Validação da Área · Aprv. PR · Implant. em PRD ·
Artefatos de GOV. · Validação Interna · Migrado`

**Funil de Ingestão (input) = lifecycle:**
`Não recebido · Recebido · Priorizado · Em ingestão · Modernizado` (Sanitizado conta como
"Concluído" junto de Modernizado; Descartado fora).

### 4.3 Cores (status)

Projeto: A iniciar `#9aa0a6` · Em andamento `#f4b400` · Concluído `#34a853` · Block `#d93025`
· Removido `#4285f4` · Removido e Contabilizado `#1e7e34`.
Ingestão (por etapa): cinza→azul→roxo→amarelo→verde; Concluído verde, atual amarelo, a iniciar cinza.

### 4.4 Barra de progresso por funil

- Projeto: `count(etapa == 'Migrado') / total do escopo`.
- Ingestão: `count(eff ∈ {Modernizado,Sanitizado}) / (total − Descartado)`.
- Callout opcional: Migrados / Despriorizado (Despriorizado = `status == Removido`).

## 5. Dados — `sas_egp_pipeline`

Tabela persistente (padrão `CREATE TABLE IF NOT EXISTS`, sobrevive a republish, como
`sas_escopo`). **Inputs não ganham tabela** — reusam `status_humano`.

```sql
CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_egp_pipeline (
  projeto STRING,
  etapa_migracao STRING,  status_migracao STRING,
  etapa_progresso STRING, status_progresso STRING,
  updated_by STRING, updated_at STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS bv_dev_db.monitoramento_sas.sas_pipeline_audit (
  id STRING, projeto STRING, funil STRING, campo STRING,
  valor_antigo STRING, valor_novo STRING, ator STRING, ts STRING
) USING DELTA;
```

- Linha criada/atualizada via MERGE no 1º PATCH; sem linha ⇒ EGP fora do coorte.
- Publish não recria (preserva edições); não precisa de recompute (funis são leitura viva).

## 6. Backend (`app/backend/main.py`)

- **`GET /api/funis`** → `{ migracao: {stages, bars:[{etapa, segmentos:{status:n}}], progresso:{migrados,total}},
  progresso_proj: {...}, ingestao: {...} }`. Agrega ao vivo: EGPs do escopo × `sas_egp_pipeline`
  (LEFT JOIN; sem linha ⇒ coorte=não), inputs × status efetivo.
- **`PATCH /api/egp-pipeline`** body `{projeto, funil:'migracao'|'progresso', etapa, status}` →
  valida etapa∈lista e status∈5-set, MERGE em `sas_egp_pipeline`, grava `sas_pipeline_audit`
  com `current_user()`.
- **`PATCH /api/inputs`** (existente): validar `status_humano` contra novos `STATUS_OPTIONS`.
- **`GET /api/inputs`**: novo `incluir_descartado` (default false).
- Helper único de "modernizado/descartado/a ingerir" aplicado em metrics/landing/resumo/inputs/egp.
- Permissões OBO: PATCH/MERGE exigem MODIFY em `sas_egp_pipeline` (UPDATE/INSERT apenas; sem
  CREATE OR REPLACE — consistente com a correção da fase 3).

## 7. Frontend

- **`FunnelChart.tsx`** (novo): barras verticais empilhadas em SVG/CSS, eixo %, rótulos de
  contagem, legenda, barra de progresso + callout. **Sem nova dependência** (bundle já 868 KB).
- **`ResumoView.tsx`**: 3 `FunnelChart` (useQuery `['funis']`) abaixo dos 7 indicadores;
  funil/origem atuais permanecem.
- **`MonitorView` / `FilterBar` / `InputsTable` / `InputDrawer`**: dropdown de status com os 7
  valores; checkbox "mostrar descartados" (default off → manda `incluir_descartado`).
- **`EgpDetailPanel.tsx`**: 2 blocos de dropdown (etapa+status) — Migração SAS e Progresso
  Projetos — com `useMutation` (otimista + auditoria) invalidando `['funis','landing',...]`.
- **Propagação instantânea (padrão fase 3):** toda edição invalida
  `['funis','metrics','landing','resumo','egp','egp-readiness','inputs']`.
- **`types.ts` / `api.ts`**: tipos `FunisPayload`, `FunnelBar`; `api.funis`, `api.egpPipeline`.

## 8. Constantes canônicas (compartilhadas front+back)

Um módulo único com as 2 listas de etapas de projeto, o lifecycle de input, o conjunto de 5
status de projeto, os 7 de input e o mapa de cores — para back e front lerem a mesma verdade
(back em `main.py`, front em um `pipeline.ts`). Divergência aqui = barra errada.

## 9. Verificação

- Counts de "a ingerir" inalterados (2902) logo após a troca de vocabulário (sem edições).
- Funil de ingestão: soma das barras coerente com o total de inputs não-descartados.
- Editar 1 EGP (etapa/status) e 1 input (status) → refletir nos funis/landing na hora (React Query).
- Descartar 1 input → some do Monitoramento por padrão, reaparece com o toggle, sai da pendência,
  nunca é deletado (continua na tabela).
- Ciclo de edição reversível (voltar status → números voltam).

## 10b. Filtro "quick win" (EGPs sem dependências)

Na aba **EGPs** (`ReadinessView`), novo chip/checkbox **"Quick win (sem dependências)"** que
filtra EGPs sem dependência de outros EGPs — candidatos a migração independente.

- Critério: `n_deps == 0` (a linha de readiness já traz `n_deps`/`n_deps_indi`/`n_deps_ext`;
  ver `types.ts:158`). Default: `n_deps == 0` = nenhuma dependência de qualquer EGP.
- **Frontend-only:** filtro client-side sobre as linhas já carregadas (`useQuery['egp-readiness']`),
  como os chips existentes (divergência etc.). Sem mudança de backend.
- Combina com os filtros atuais (área, escopo, busca) e com a ordenação.
- Mostra a contagem no chip (ex.: "Quick win: N").
- *(Variante opcional, a confirmar: "quick win forte" = `n_deps == 0` E todos os inputs já
  modernizados — não incluído por padrão.)*

## 10. Fora de escopo / riscos

- Não importa dados externos (PMO/PowerBI) — tracking nasce vazio (coorte cresce conforme se edita).
- `WavesView` não usa React Query; reflete por remount ao navegar (já é o comportamento atual).
- Denominadores vivos divergem dos prints (231/2779) — esperado.
- Edição em massa de pipeline não está no escopo (só painéis existentes).

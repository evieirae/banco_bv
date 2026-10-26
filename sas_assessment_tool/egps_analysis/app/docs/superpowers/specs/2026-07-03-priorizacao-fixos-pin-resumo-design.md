# Aba Priorização — filtros fixos, pin de mês e resumo (migrados/bloqueados/habilitados)

**Data:** 2026-07-03
**App:** `monitoramento-sas` (`egps_analysis/app`)
**Arquivos-alvo:** `backend/main.py`, `frontend/src/{types.ts,api.ts,components/WavesView.tsx,styles.css}`

## Objetivo

Transformar a aba **Priorização** (`WavesView` + `GET /api/priorizacao`) de uma
ferramenta de exploração com filtros livres numa **visão operacional fixa** do plano
de ingestão da Indicium, com três acréscimos:

1. **Recorte travado**: escopo `Indicium + dependências`, todas as áreas, capacidade
   **400 inputs/mês** — sem controles editáveis.
2. **Override manual**: mover (fixar) um EGP para outro mês quando houver razão de
   priorização fora do algoritmo — persistido.
3. **Resumo no topo**: três cards — *migrados neste mês* (calendário), *bloqueados*,
   *habilitados* — sobre o recorte fixo.

## Estado atual (baseline)

- `WavesView.tsx`: 4 controles editáveis (área, "só Indicium", "com dependências",
  capacidade default 500) → chama `api.priorizacao({scope, area, deps, capacidade})`.
- `GET /api/priorizacao(scope="indi", area="", deps="transitive", capacidade=500)`:
  empacota os EGPs do recorte em "meses" ordinais de ≤ `cap` inputs distintos.
  Ordem lexicográfica: **viabilidade** (`_viab`: 0 viável / 1 só-SAS-local / 2 bloqueado)
  → **alavancagem** (`-fan_out`) → **quick win** (menos inputs) → nome.
  Dedupe entre meses: input compartilhado conta 1× (no 1º mês em que aparece).
- Sem persistência de qualquer ajuste manual; meses são puramente algorítmicos.
- `_blocking()["blocked"]`: conjunto de EGPs bloqueados (leaf = lê tabela SAS/Local sem
  produtor mapeado e não modernizada; propagado transitivamente aos consumidores).
- `T_PIPE = sas_egp_pipeline` (projeto, etapa/status por funil, responsavel, updated_*).
- `T_PIPE_AUD = sas_pipeline_audit` (id, projeto, funil, campo, valor_antigo,
  valor_novo, ator, ts). `egp_pipeline` PATCH grava `campo='status'` / `valor_novo=<status>`
  para o funil `migracao`.
- Migrado é `status ∈ STATUS_PROJETO`; `"Migrado"` é a etapa/estado terminal.

## Decisões (fechadas com o usuário)

| Tema | Decisão |
|---|---|
| Filtros | **Removidos**; substituídos por rótulo fixo do recorte. `scope=indi`, `deps=transitive`, `area=""`, `cap=400`. |
| Sentido de "mês" nos cards | "migrados neste mês" = **mês de calendário real** (via `ts` da auditoria). Cards são resumo do topo, independentes das caixas do plano. |
| Pin vs teto 400 | **Pin absoluto; teto vira guia.** EGP fixado entra no mês escolhido mesmo estourando 400 (mês marcado "excede"); auto-packer preenche o resto até 400 e joga o excedente pra frente. |
| Definição de "habilitados" | **Não-bloqueados** (complemento): `habilitados = total_recorte − bloqueados`. |
| População dos cards | O **recorte fixo** (indi + deps). |
| Quem move EGP | **Só gestão** (bv_users): endpoint `_require_gestao`; UI só mostra o controle se `cfg.is_gestao`. |

## Design

### 1. Filtros fixos (frontend)

`WavesView.tsx`:
- Remover os `useState` de `scopeIndi`, `area`, `deps`, `cap`/`capInput` e os controles
  correspondentes.
- Constantes fixas: `SCOPE="indi"`, `DEPS="transitive"`, `AREA=""`, `CAP=400`.
- Barra de filtros → **rótulo fixo**: `Recorte fixo: Indicium + dependências · todas as
  áreas · 400 inputs/mês` (mantém `.filters`/`.count` para o contador
  "N meses · M inputs distintos · K EGPs").
- `queryKey` passa a `["priorizacao"]` (estável); refetch dirigido por invalidação após
  pin (ver §3).
- `cfg` continua recebido (já é) — usado para gatear o controle de mover.

### 2. Resumo no topo — 3 cards (backend + frontend)

**Backend** — `GET /api/priorizacao` ganha no payload:

```json
"resumo": { "migrados_mes": <int>, "bloqueados": <int>, "habilitados": <int>, "total": <int> }
```

- `total` = `len(frontier)` (EGPs do recorte).
- `bloqueados` = `len(blocked ∩ frontier)`.
- `habilitados` = `total − bloqueados`.
- `migrados_mes` = EGPs **do recorte** cujo status de migração virou `'Migrado'` **neste
  mês de calendário**, via auditoria:

  ```sql
  SELECT count(DISTINCT projeto) FROM {T_PIPE_AUD}
   WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Migrado'
     AND substr(ts, 1, 7) = date_format(current_date(), 'yyyy-MM')
     AND projeto IN (<frontier>)
  ```

  **Decisão explícita:** `migrados_mes` conta **apenas `'Migrado'`** (velocidade real de
  migração). Não inclui `Removido`/`Despriorizado e Contabilizado` (que são saídas de
  escopo, não migrações) — diverge de propósito da headline "migrados" do funil.
  Limitação conhecida: só captura transições **registradas na auditoria** (a partir de
  quando o funil passou a auditar) — aceitável para um KPI de "o que fizemos este mês".

**Frontend** — `WavesView`: bloco `.metrics` com 3 `.card` (reuso do estilo existente):
`Migrados neste mês` (neutro), `Bloqueados` (`.card.danger`), `Habilitados` (`.card.ok`).
Novo tipo `PrioResumo` em `types.ts`; `PriorizacaoPayload.resumo`.

### 3. Mover EGP de mês (pin manual, persistido)

**Persistência** — coluna nova `mes_prioridade INT` em `T_PIPE`, adicionada dentro de
`_ensure_pipe_table()` com o mesmo padrão idempotente já usado para `responsavel`
(`try SELECT … / except: ALTER TABLE ADD COLUMNS`). `NULL` = automático.
> ⚠️ Escrita de schema em produção (`bv_dev_db.monitoramento_sas`) — executada **só com
> consentimento humano explícito**, na primeira chamada que tocar a tabela.

**Endpoint** — `PATCH /api/priorizacao/mes`:
```
body: { projeto: str, mes: int | null }   # mes>=1 fixa; null volta ao automático
```
- Gated `_require_gestao()` (403 fora do grupo).
- `MERGE` em `T_PIPE` setando `mes_prioridade` (mesmo estilo do `egp_pipeline`), com
  `updated_by/updated_at`.
- Auditoria em `T_PIPE_AUD`: `funil='migracao'`, `campo='mes_prioridade'`,
  `valor_antigo/valor_novo`, `ator=current_user()`, `ts`.
- Valida `mes` como inteiro ≥ 1 ou `null`.

**Algoritmo de empacotamento com pins** (substitui o laço atual em `/api/priorizacao`):

Mantém a ordem lexicográfica (`_viab`, `-fanout`, esforço, nome) e o dedupe global.
Processa os meses em **ordem crescente** (garante que cada input é contado no mês mais
cedo em que aparece).

```
pin[pj]  = mes_prioridade do EGP (se houver), só p/ pj no frontier
order    = sorted(frontier, key=(_viab, -fanout, len(inputs), pj))   # como hoje
pinned   = [pj for pj in order if pin.get(pj)]
free     = [pj for pj in order if not pin.get(pj)]
ingested = set();  months = {}       # m -> {"inputs": set, "egps": []}
m = 1;  free_i = 0;  max_pin = max(pin.values(), default=0)

while free_i < len(free) or m <= max_pin:
    cm = months.setdefault(m, {"inputs": set(), "egps": []})
    # (a) pins deste mês, na ordem de prioridade
    for pj in pinned if pin[pj]==m:
        marginal = inputs[pj] - ingested
        cm.add(pj, marginal, excede=len(marginal)>cap, pinned=True); ingested |= marginal
    # (b) livres até o teto (soft)
    while free_i < len(free):
        pj = free[free_i]; marginal = inputs[pj]-ingested; novos = len(marginal)
        if novos > cap:                      # EGP sozinho excede -> mês próprio
            if cm["egps"]: break             # não empurra num mês já ocupado
            cm.add(pj, marginal, excede=True, pinned=False); ingested |= marginal
            free_i += 1; break
        if cm["egps"] and len(cm["inputs"])+novos > cap: break   # não cabe -> próximo mês
        cm.add(pj, marginal, excede=False, pinned=False); ingested |= marginal; free_i += 1
    m += 1

# remove meses vazios e renumera 1..K (contíguo) p/ exibição
```

- **Pin absoluto, teto guia:** um mês pode passar de 400 por causa de pins → `n_inputs >
  cap` → frontend já pinta `over` (barra/pill `todo`); rótulo "excede" por EGP mantém o
  comportamento atual do EGP-sozinho-excede.
- **Meses contíguos:** buckets vazios são removidos e renumerados 1..K na exibição. O
  `mes_prioridade` armazenado guarda a intenção absoluta do usuário; o display compacta.
- **Controle de mover (UI):** oferece `Mês 1..N` (existentes) + `+ novo mês` (N+1), para
  não criar buracos; `Limpar` (→ `null`, volta ao automático).

**Payload** — cada `PrioEgp` ganha `mes_pin: number | null` (mês fixado, se houver) para
a UI exibir 📌 e o valor atual no controle.

**Frontend `WavesView`** — em cada `.prio-egp` (só se `cfg.is_gestao`): controle discreto
de mover (`<select>` de mês + `Limpar`). Mutation react-query (padrão de
`EgpDetailPanel`): otimista sobre a lista, `onSuccess` → `qc.invalidateQueries(["priorizacao"])`
(o pin muda o empacotamento inteiro, então invalidar e refetch é mais simples e correto
que patch otimista completo). EGP fixado: badge 📌 + destaque.

### 4. Contrato de tipos (frontend `types.ts`)

```ts
export interface PrioResumo { migrados_mes: number; bloqueados: number; habilitados: number; total: number; }
export interface PrioEgp { /* … campos atuais … */ mes_pin: number | null; }
export interface PriorizacaoPayload { /* … atuais … */ resumo: PrioResumo; }
```

`api.ts`: `priorizacao()` deixa de receber args (chama `api/priorizacao` com o recorte
fixo embutido na URL); novo `priorizacaoSetMes({projeto, mes})`.

## Extensão — Onda → Mês de priorização (todas as abas)

**Requisito (2026-07-03):** o mês do plano de priorização **substitui** o atributo "Onda"
em todas as abas que hoje o exibem, refletindo **dinamicamente** (quando um pin muda ou os
dados mudam, o mês some/atualiza em todas as abas ao vivo).

**Decisões (fechadas com o usuário):**

| Tema | Decisão |
|---|---|
| Substituir vs adicionar | **Substituir** Onda → Mês (o "onda" antigo deixa de ser exibido nas abas). |
| EGPs fora do recorte fixo (não indi/dep) | Mostram **"—"** (não fazem parte do plano Indicium). |
| Indicador de ciclo (⟳) | **Mantido**, derivado de `ciclo_id` (ortogonal ao mês). |
| Abas afetadas | **Todas as 6**: Prontidão (+ filtro), Indicium, Escopo Migração, Detalhe do EGP, InputDrawer, Linhagem. |

**Arquitetura (sem mudança de backend):**

- Módulo novo `frontend/src/mesPlan.ts`:
  - `mesTag(mes)` → `mes == null ? "—" : "M" + mes`.
  - Hook `useMesPlan()` → usa `useQuery({ queryKey: ["priorizacao"], queryFn: api.priorizacao })`
    (mesma queryKey do `WavesView` ⇒ **cache compartilhado**). Deriva `mesOf: Map<projeto, mês>`
    a partir de `data.meses[].egps[].projeto → mes`. Como o `PATCH /api/priorizacao/mes`
    invalida `["priorizacao"]`, todas as abas que consomem o hook **refazem e re-renderizam**.
- Cada aba: remove o `waveTag` local, importa `mesTag`/`useMesPlan`, e troca
  `waveTag(r.onda)` por `mesTag(mesOf.get(r.projeto))`; o ⟳ passa a vir sempre de `ciclo_id`.
- **Prontidão**: o filtro "Onda" (`ondaSel`/`ondasList`) vira filtro "Mês"
  (`mesSel`/`mesesList` = meses presentes no `mesOf`), filtrando por `mesOf.get(r.projeto)`.
  As colunas de tabela/CSV "Onda" viram "Mês".
- **Linhagem** (cytoscape, imperativo): `egpEl` recebe `mesOf` por parâmetro; o rótulo do nó e
  o tooltip passam a mostrar o mês; um efeito adicional (dependente de `mesOf`) faz *patch*
  dos nós já renderizados para refletir o plano ao vivo. É a aba mais custosa.

**Semântica:** "onda" (estático, curado/orquestrador, com ciclo embutido na string) é
substituído pelo **mês dinâmico** do plano por capacidade. O aviso de ciclo continua
via `ciclo_id`. Isso é uma mudança de sentido deliberada, pedida pelo usuário.

## Fora de escopo (YAGNI)

- Mapear buckets do plano para meses de calendário reais (datas). Buckets seguem ordinais.
- Editar capacidade na UI (fixa em 400).
- Reordenar EGPs *dentro* de um mês manualmente (a ordem interna segue o algoritmo).
- Histórico/undo de pins além da auditoria já gravada.

## Arquivos tocados

| Arquivo | Mudança |
|---|---|
| `backend/main.py` | `_ensure_pipe_table` (+coluna `mes_prioridade`); `/api/priorizacao` (payload `resumo`+`mes_pin`, algoritmo com pins, query migrados-mês); novo `PATCH /api/priorizacao/mes` (gated). |
| `frontend/src/types.ts` | `PrioResumo`; `PrioEgp.mes_pin`; `PriorizacaoPayload.resumo`. |
| `frontend/src/api.ts` | `priorizacao()` sem args; `priorizacaoSetMes()`. |
| `frontend/src/components/WavesView.tsx` | remove filtros → rótulo fixo; 3 cards; controle de mover (gestão). |
| `frontend/src/styles.css` | ajustes mínimos (badge pin, controle mover); reusa `.metrics`/`.card`. |
| `pipeline.ts` | **sem mudança** (status strings preservados). |
| `frontend/src/mesPlan.ts` | **(extensão)** `mesTag` + hook `useMesPlan` (mapa `projeto→mês`, cache compartilhado). |
| `frontend/src/components/{ReadinessView,IndiciumView,MigrationScopeView,EgpDetailPanel,InputDrawer,LineageView}.tsx` | **(extensão)** Onda → Mês (remove `waveTag` local, usa `mesTag`/`useMesPlan`; ⟳ de `ciclo_id`); Prontidão troca o filtro Onda→Mês. |

## Testes

- **Unit (pytest, sem DB):** extrair o empacotamento como **função pura**
  `plan_months(order, inputs, pin, cap)` e cobrir:
  1. sem pins → resultado idêntico ao algoritmo atual (regressão);
  2. pin puxando EGP pra Mês 1 (dedupe move inputs pro mês cedo);
  3. pin estourando 400 → mês marcado excede, livres não passam do teto;
  4. pin pra mês novo ao final;
  5. `habilitados == total − bloqueados`.
- **Verificação visual** (skill `verify`) no app rodando local, após aprovação.

## Guardrails

- Sem `dbt build`, sem `git commit`/`push` sem pedido explícito.
- Deploy e a criação da coluna em prod → só com consentimento humano explícito.
- Editar `backend/main.py` via edição direcionada (arquivo grande / context-guard);
  revisar com `git diff`.

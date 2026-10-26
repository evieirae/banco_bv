# EGPs tab — coluna "Último status" + painel Gestão Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na aba EGPs, trocar a coluna "Prontidão" por "Último status" que, ao clicar, abre o painel lateral da Gestão (`GestaoStatusPanel`); o botão "+ Adicionar Comentário" só aparece para usuários `is_gestao()`.

**Architecture:** Frontend-only. Reusa endpoints já não-gated (`GET /api/gestao/rows`, `GET /api/gestao/status`) e o componente `GestaoStatusPanel` já existente. `ReadinessView` passa a buscar as linhas da Gestão (cache compartilhado com a aba Gestão) e monta um `Map<projeto, GestaoRow>` para render da célula e abertura do painel.

**Tech Stack:** React + TypeScript, `@tanstack/react-query`, Vite. Sem framework de teste no front — o gate de cada task é `npx tsc --noEmit` + verificação visual no app dev.

## Global Constraints

- **Sem mudança de backend.** Todos os dados vêm de `gestaoApi` (endpoints já não-gated).
- **Sem mudança de CSS.** A truncagem em 1 linha já é feita por `styles.css:280` (`.rd-thead > div, .rd-trow > div { overflow:hidden; white-space:nowrap; text-overflow:ellipsis }`). A coluna mantém a largura atual (`150px`, `styles.css:276`/`:278`).
- **Sem mudança no CSV** (`exportCsv` em `ReadinessView` fica intacto).
- Commits **sem** `Co-Authored-By` (regra do repo).
- Render da célula de último status, por linha (`gr = map.get(r.projeto)`):
  - sem `GestaoRow` → texto `fora de escopo`, muted, **não clicável**;
  - com `GestaoRow` e `resumoStatus` preenchido → texto truncado, `title` = texto completo, **clicável**;
  - com `GestaoRow` e `resumoStatus` vazio → texto `sem status`, muted, **clicável**.
- O clique na célula usa `stopPropagation` (não expande o detalhe da linha).
- Gate de escrita já é garantido pelo backend (`POST /api/gestao/status` = `_require_gestao()`); o front só **esconde** o botão.

---

### Task 1: Gate do botão "+ Adicionar Comentário" em `GestaoStatusPanel`

Esconde o botão de adicionar (e, por tabela, o modal) para quem não é `bv_users`. Sem regressão na aba Gestão (lá todos são `bv_users`).

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx`

**Interfaces:**
- Consumes: `api.config()` → `AppConfig` (campo `is_gestao?: boolean`, já em `types.ts:35`). O componente já busca `["config"]` para `is_admin` (`GestaoStatusPanel.tsx:33-34`).
- Produces: comportamento visual condicional; nenhuma nova assinatura exportada.

- [ ] **Step 1: Ler `is_gestao` do config já buscado**

Em `GestaoStatusPanel.tsx`, logo após a linha 34 (`const isAdmin = !!cfgQ.data?.is_admin;`), adicionar:

```tsx
  const isGestao = !!cfgQ.data?.is_gestao;
```

- [ ] **Step 2: Envolver o botão de adicionar no gate**

Trocar o bloco atual (`GestaoStatusPanel.tsx:111-113`):

```tsx
        <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
          + Adicionar Comentário
        </button>
```

por:

```tsx
        {isGestao && (
          <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
            + Adicionar Comentário
          </button>
        )}
```

O `AddCommentModal` só monta via `modal` (setado por esse botão), então esconder o botão já impede o modal — nenhuma mudança extra necessária.

- [ ] **Step 3: Typecheck**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 4: Verificação visual (aba Gestão, sem regressão)**

Com o app dev rodando, abrir a aba **Gestão**, clicar numa linha para abrir o painel. Como o usuário dev é `bv_users`, o botão **"+ Adicionar Comentário" continua aparecendo**. (O caso "não-gestão esconde" é verificado na Task 2, quando o painel abre pela aba EGPs.)

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx
git commit -m "feat(app): botão + Adicionar Comentário só para is_gestao no painel de status"
```

---

### Task 2: Coluna "Último status" e abertura do painel em `ReadinessView`

Substitui a coluna "Prontidão" por "Último status", buscando os dados da Gestão e abrindo `GestaoStatusPanel` no clique.

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/ReadinessView.tsx`

**Interfaces:**
- Consumes:
  - `gestaoApi.listRows("egp")` → `Promise<GestaoRow[]>` (de `../gestaoApi`); `GestaoRow` tem `{ id, nome, area, etapa, resumoStatus, bvEventos, ... }`.
  - `gestaoApi.getUsers()` → `Promise<GestaoUser[]>`.
  - `GestaoStatusPanel` (de `./GestaoStatusPanel`), props `{ entity, row, allRows, users, onClose }` (Task 1 tornou o botão condicional).
  - `bucketOf` / `BUCKET` continuam existindo (usados pela barra/chips) — **não** remover; só a célula/coluna "Prontidão" sai.
- Produces: nenhuma assinatura exportada nova.

- [ ] **Step 1: Imports**

No topo de `ReadinessView.tsx` (após os imports existentes, ex.: junto ao import de `EgpDetailPanel` na linha 5), adicionar:

```tsx
import { GestaoStatusPanel } from "./GestaoStatusPanel";
import { gestaoApi, type GestaoRow, type GestaoUser } from "../gestaoApi";
```

- [ ] **Step 2: Buscar linhas/usuários da Gestão e montar o mapa**

Dentro do componente `ReadinessView`, junto às outras queries (ex.: após a linha 102, `analistasQ`), adicionar:

```tsx
  const gestaoRowsQ = useQuery({ queryKey: ["gestao", "egp"], queryFn: () => gestaoApi.listRows("egp") });
  const gestaoUsersQ = useQuery({ queryKey: ["gestao-users"], queryFn: () => gestaoApi.getUsers() });
  const gestaoRows: GestaoRow[] = gestaoRowsQ.data ?? [];
  const gestaoUsers: GestaoUser[] = gestaoUsersQ.data ?? [];
  const gestaoById = useMemo(() => new Map(gestaoRows.map((r) => [r.id, r])), [gestaoRows]);
```

(As query keys `["gestao","egp"]` e `["gestao-users"]` são as mesmas da aba Gestão — o cache é compartilhado, sem request duplicado quando as duas abas são visitadas.)

- [ ] **Step 3: Estado do painel**

Junto aos outros `useState` (ex.: após a linha 86, `notFound`), adicionar:

```tsx
  const [panelId, setPanelId] = useState<string | null>(null);
  const panelRow = panelId ? gestaoById.get(panelId) ?? null : null;
```

- [ ] **Step 4: Trocar o cabeçalho da coluna**

Em `ReadinessView.tsx:293`, trocar `<div>Prontidão</div>` por `<div>Último status</div>` (é o último `<div>` da linha do `th(...)`s no `rd-thead`). O restante da linha 293 fica igual.

- [ ] **Step 5: Trocar a célula da coluna**

Em `ReadinessView.tsx:361`, trocar a célula da prontidão:

```tsx
                  <div><span className={`pill ${BUCKET[b].tone}`}>{BUCKET[b].label}</span></div>
```

por:

```tsx
                  {(() => {
                    const gr = gestaoById.get(r.projeto);
                    if (!gr) return <div className="muted">fora de escopo</div>;
                    const txt = gr.resumoStatus;
                    return (
                      <div className="muted" style={{ cursor: "pointer", color: txt ? "inherit" : undefined }}
                        title={txt ?? "sem status"}
                        onClick={(e) => { e.stopPropagation(); setPanelId(r.projeto); }}>
                        {txt ?? "sem status"}
                      </div>
                    );
                  })()}
```

(`fora de escopo` é muted e **sem** `onClick`. As duas variantes in-scope têm `onClick` com `stopPropagation`. Texto presente usa cor normal; `sem status` fica muted. A truncagem/tooltip usa o CSS já existente + `title`.)

- [ ] **Step 6: Renderizar o painel**

Antes do fechamento do `return` (após o `</div>` que fecha `rd-table`, perto da linha 372, antes do `</div>` final do wrapper `readiness`), adicionar:

```tsx
      {panelRow && (
        <GestaoStatusPanel entity="egp" row={panelRow} allRows={gestaoRows}
          users={gestaoUsers} onClose={() => setPanelId(null)} />
      )}
```

- [ ] **Step 7: Typecheck**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros. (Se acusar `BUCKET`/`bucketOf` não usados, confirmar que a barra de `% modernizado` e os chips ainda os usam — eles usam; nada a remover.)

- [ ] **Step 8: Verificação visual**

Com o app dev rodando, aba **EGPs**:
- escopo "só Indicium": a coluna final mostra **Último status**; linhas com status mostram o texto (truncado, tooltip com texto completo); linhas sem status mostram **`sem status`**.
- clicar numa célula com/sem status **abre o painel** (não expande o detalhe da linha); clicar no resto da linha **expande o detalhe** normalmente.
- trocar escopo para **"todos"**: EGPs fora do escopo Indicium mostram **`fora de escopo`** e **não abrem** painel ao clicar.
- se o usuário dev for `bv_users`: o painel mostra "+ Adicionar Comentário"; adicionar um comentário atualiza o último status na coluna (invalida `["gestao","egp"]` via `onSaved` do painel).

- [ ] **Step 9: Commit**

```bash
git add egps_analysis/app/frontend/src/components/ReadinessView.tsx
git commit -m "feat(app): aba EGPs — coluna Último status abre o painel da Gestão (substitui Prontidão)"
```

---

## Self-Review

**Spec coverage:**
- Coluna Prontidão → Último status: Task 2 (Steps 4-5). ✓
- Clique abre `GestaoStatusPanel`: Task 2 (Steps 3, 6). ✓
- Gate "+ Adicionar Comentário" em `is_gestao`: Task 1. ✓
- 3 casos de render (fora de escopo / com status / sem status): Task 2 Step 5 + Global Constraints. ✓
- `stopPropagation` no clique: Task 2 Step 5. ✓
- Sem backend / sem CSS / sem CSV: Global Constraints. ✓

**Placeholder scan:** nenhum TBD/TODO; todo passo tem o código exato.

**Type consistency:** `GestaoRow`/`GestaoUser` importados de `../gestaoApi`; `panelRow` é `GestaoRow | null`; `GestaoStatusPanel` recebe `row: GestaoRow`, `allRows: GestaoRow[]`, `users: GestaoUser[]`, `entity: "egp"` — batem com `GestaoStatusPanel.tsx:11-17`. `resumoStatus` é `string | null` (`gestaoApi.ts:30`). `is_gestao` é `boolean?` (`types.ts:35`).

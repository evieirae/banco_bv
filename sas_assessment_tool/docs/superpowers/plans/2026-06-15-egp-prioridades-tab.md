# Aba "Prioridades" (EGPs priorizados pela Indicium) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar uma aba "Prioridades" ao app com CRUD + reordenação de uma lista curada de EGPs priorizados, salva numa tabela Delta nova mantida por humano e nunca tocada pelo publish.

**Architecture:** Tabela Delta `sas_egp_prioridades` criada *lazy* pelo backend (`CREATE TABLE IF NOT EXISTS`). Cinco endpoints REST em `backend/main.py` (`run_sql`/`sql_lit`), com a lógica pura isolada em `backend/prioridades_logic.py` (testável sem Databricks). No front, um componente `PrioridadesView` (tabela inline-editável + picker híbrido + setas ↑/↓), fiado em `api.ts`/`types.ts`/`App.tsx`, reusando os tokens de tema.

**Tech Stack:** FastAPI + databricks-sdk (StatementExecutionAPI) no backend; React 18 + TypeScript/Vite no front; Delta Lake.

**Spec:** `docs/superpowers/specs/2026-06-15-egp-prioridades-tab-design.md`

---

## File Structure

| Arquivo | Mudança | Responsabilidade |
|---|---|---|
| `egps_analysis/app/backend/prioridades_logic.py` | criar | `STATUS_PRIO`, `valid_status`, `next_ordem`, `neighbor_swap` — puro, sem deps. |
| `egps_analysis/app/backend/test_prioridades_logic.py` | criar | teste das funções puras (script python com `assert`, sem pytest). |
| `egps_analysis/app/backend/main.py` | modificar | `import uuid`, import da lógica, `T_PRIO`, endpoints `/api/prioridades*` + helpers. |
| `egps_analysis/app/frontend/src/types.ts` | modificar | `Prioridade`, `PrioridadeCreate`, `PrioridadePatch`. |
| `egps_analysis/app/frontend/src/api.ts` | modificar | objeto `prioridades` (list/create/update/move/remove). |
| `egps_analysis/app/frontend/src/prioridades.ts` | criar | `filterEgps` — puro, p/ o picker. |
| `egps_analysis/app/frontend/prioridades.test.mts` | criar | teste Node de `filterEgps`. |
| `egps_analysis/app/frontend/src/components/PrioridadesView.tsx` | criar | a aba (tabela inline + picker + setas + excluir). |
| `egps_analysis/app/frontend/src/App.tsx` | modificar | tipo `View`, `TABS`, render da aba. |
| `egps_analysis/app/frontend/src/styles.css` | modificar | classes `.prio-*` (tokenizadas). |

**Nota de ambiente (rode os comandos do front a partir de `egps_analysis/app/frontend`):** `npm run build` roda `tsc -b && vite build`; `tsconfig` é estrito (`noUnusedLocals`/`noUnusedParameters`). Testes `.mts` rodam via `node <arquivo>.mts` (Node 24 faz type-stripping). Os arquivos `*.test.mts` ficam **fora** de `src/` e não entram no `tsc`.

---

### Task 1: Lógica pura do backend — TDD

**Files:**
- Create: `egps_analysis/app/backend/prioridades_logic.py`
- Test: `egps_analysis/app/backend/test_prioridades_logic.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `egps_analysis/app/backend/test_prioridades_logic.py`:
```python
from prioridades_logic import valid_status, next_ordem, neighbor_swap, STATUS_PRIO


def check(name, cond):
    assert cond, name
    print("ok -", name)


check("status válidos", all(valid_status(s) for s in STATUS_PRIO))
check("status inválido", (not valid_status("xpto")) and (not valid_status("")))
check("next_ordem de vazio", next_ordem(0) == 1 and next_ordem(None) == 1)
check("next_ordem incrementa", next_ordem(5) == 6)

rows = [{"id": "a", "ordem": 1}, {"id": "b", "ordem": 2}, {"id": "c", "ordem": 3}]
up = neighbor_swap(rows, "b", "up")
check("subir troca com anterior", up is not None and {up[0]["id"], up[1]["id"]} == {"a", "b"})
down = neighbor_swap(rows, "b", "down")
check("descer troca com próximo", down is not None and {down[0]["id"], down[1]["id"]} == {"b", "c"})
check("primeiro não sobe", neighbor_swap(rows, "a", "up") is None)
check("último não desce", neighbor_swap(rows, "c", "down") is None)
check("id inexistente", neighbor_swap(rows, "z", "up") is None)
unordered = [{"id": "c", "ordem": 3}, {"id": "a", "ordem": 1}, {"id": "b", "ordem": 2}]
res = neighbor_swap(unordered, "a", "down")
check("ordena por ordem numérica", res is not None and res[1]["id"] == "b")

print("\nOK")
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd egps_analysis/app/backend && python3 test_prioridades_logic.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'prioridades_logic'`.

- [ ] **Step 3: Implementar `prioridades_logic.py`**

Criar `egps_analysis/app/backend/prioridades_logic.py`:
```python
"""Funções puras da aba Prioridades — sem dependências de FastAPI/Databricks
(testáveis com `python3 test_prioridades_logic.py`)."""

STATUS_PRIO = ["A fazer", "Em andamento", "Concluído", "Descartado"]


def valid_status(s):
    return s in STATUS_PRIO


def next_ordem(max_ordem):
    return (max_ordem or 0) + 1


def neighbor_swap(rows, item_id, direction):
    """rows: lista de {id, ordem}. Devolve (atual, vizinho) cujos `ordem` devem
    ser trocados, ou None se item_id não existe ou já está na ponta na direção pedida."""
    ordered = sorted(rows, key=lambda r: r["ordem"])
    idx = next((i for i, r in enumerate(ordered) if r["id"] == item_id), None)
    if idx is None:
        return None
    j = idx - 1 if direction == "up" else idx + 1
    if j < 0 or j >= len(ordered):
        return None
    return ordered[idx], ordered[j]
```

- [ ] **Step 4: Rodar e confirmar passa**

Run: `cd egps_analysis/app/backend && python3 test_prioridades_logic.py`
Expected: 9 linhas `ok - …` e `OK`, exit 0.

- [ ] **Step 5: Commit** (SEM trailer Co-Authored-By)
```bash
git add egps_analysis/app/backend/prioridades_logic.py egps_analysis/app/backend/test_prioridades_logic.py
git commit -m "feat(app/back): lógica pura da aba Prioridades + teste"
```

---

### Task 2: Endpoints `/api/prioridades*` no backend

**Files:**
- Modify: `egps_analysis/app/backend/main.py`

- [ ] **Step 1: Adicionar `import uuid`** logo após `import functools` (linha ~22):
```python
import functools
import uuid
```

- [ ] **Step 2: Importar a lógica pura** logo após a linha `from databricks.sdk.service.sql import StatementState, Disposition, Format`:
```python
from prioridades_logic import STATUS_PRIO, valid_status, next_ordem, neighbor_swap
```

- [ ] **Step 3: Declarar a constante da tabela** logo após `T_FUN = f"{FQ}.sas_funil_area"`:
```python
T_PRIO = f"{FQ}.sas_egp_prioridades"
```

- [ ] **Step 4: Inserir o bloco de endpoints** imediatamente ANTES do comentário `# ---- estáticos (SPA) — montados por último para não capturar /api ----`:
```python
# ---- aba Prioridades (lista curada de EGPs priorizados pela Indicium) ----
@functools.lru_cache(maxsize=1)
def _ensure_prio_table():
    run_sql(
        f"CREATE TABLE IF NOT EXISTS {T_PRIO} ("
        f"id STRING, ordem INT, projeto STRING, vinculado BOOLEAN, "
        f"status STRING, responsavel STRING, justificativa STRING, "
        f"created_by STRING, created_at TIMESTAMP, updated_by STRING, updated_at TIMESTAMP"
        f") USING DELTA", want_rows=False)
    return True


def _prio_out(r):
    return {
        "id": r["id"], "ordem": int(r.get("ordem") or 0), "projeto": r.get("projeto"),
        "vinculado": str(r.get("vinculado")).lower() == "true",
        "status": r.get("status"), "responsavel": r.get("responsavel"),
        "justificativa": r.get("justificativa"),
        "created_by": r.get("created_by"), "created_at": r.get("created_at"),
        "updated_by": r.get("updated_by"), "updated_at": r.get("updated_at"),
        "area": r.get("area"), "onda": r.get("onda"),
    }


_PRIO_SELECT = (
    "SELECT p.id, p.ordem, p.projeto, p.vinculado, p.status, p.responsavel, p.justificativa, "
    "p.created_by, CAST(p.created_at AS STRING) AS created_at, "
    "p.updated_by, CAST(p.updated_at AS STRING) AS updated_at, nd.area AS area, nd.onda AS onda "
    f"FROM {T_PRIO} p LEFT JOIN {T_ND} nd ON nd.projeto = p.projeto AND p.vinculado = true")


class PrioIn(BaseModel):
    projeto: str
    vinculado: bool = False
    status: str = "A fazer"
    responsavel: str | None = None
    justificativa: str | None = None


class PrioPatch(BaseModel):
    projeto: str | None = None
    vinculado: bool | None = None
    status: str | None = None
    responsavel: str | None = None
    justificativa: str | None = None


class PrioMove(BaseModel):
    dir: str


@app.get("/api/prioridades")
def prioridades_list():
    _ensure_prio_table()
    rows = run_sql(_PRIO_SELECT + " ORDER BY p.ordem ASC, p.created_at ASC")
    return {"rows": [_prio_out(r) for r in rows]}


@app.post("/api/prioridades")
def prioridades_create(p: PrioIn):
    _ensure_prio_table()
    projeto = (p.projeto or "").strip()
    if not projeto:
        raise HTTPException(400, "projeto vazio")
    if not valid_status(p.status):
        raise HTTPException(400, f"status inválido: {p.status}")
    m = run_sql(f"SELECT COALESCE(MAX(ordem), 0) AS m FROM {T_PRIO}")
    ordem = next_ordem(int(m[0]["m"]) if m and m[0].get("m") is not None else 0)
    pid = uuid.uuid4().hex
    run_sql(
        f"INSERT INTO {T_PRIO} (id, ordem, projeto, vinculado, status, responsavel, justificativa, "
        f"created_by, created_at, updated_by, updated_at) VALUES ("
        f"{sql_lit(pid)}, {ordem}, {sql_lit(projeto)}, {'true' if p.vinculado else 'false'}, "
        f"{sql_lit(p.status)}, {sql_lit(p.responsavel)}, {sql_lit(p.justificativa)}, "
        f"current_user(), current_timestamp(), current_user(), current_timestamp())", want_rows=False)
    rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
    if not rows:
        raise HTTPException(502, "falha ao criar a prioridade")
    return _prio_out(rows[0])


@app.patch("/api/prioridades/{pid}")
def prioridades_patch(pid: str, p: PrioPatch):
    _ensure_prio_table()
    cur = run_sql(f"SELECT id FROM {T_PRIO} WHERE id = {sql_lit(pid)}")
    if not cur:
        raise HTTPException(404, "prioridade não encontrada")
    sets = []
    if p.projeto is not None:
        pj = p.projeto.strip()
        if not pj:
            raise HTTPException(400, "projeto vazio")
        sets.append(f"projeto = {sql_lit(pj)}")
    if p.vinculado is not None:
        sets.append(f"vinculado = {'true' if p.vinculado else 'false'}")
    if p.status is not None:
        if not valid_status(p.status):
            raise HTTPException(400, f"status inválido: {p.status}")
        sets.append(f"status = {sql_lit(p.status)}")
    if p.responsavel is not None:
        sets.append(f"responsavel = {sql_lit(p.responsavel)}")
    if p.justificativa is not None:
        sets.append(f"justificativa = {sql_lit(p.justificativa)}")
    if not sets:
        raise HTTPException(400, "nada para atualizar")
    sets.append("updated_by = current_user()")
    sets.append("updated_at = current_timestamp()")
    run_sql(f"UPDATE {T_PRIO} SET {', '.join(sets)} WHERE id = {sql_lit(pid)}", want_rows=False)
    rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
    return _prio_out(rows[0])


@app.post("/api/prioridades/{pid}/move")
def prioridades_move(pid: str, body: PrioMove):
    _ensure_prio_table()
    if body.dir not in ("up", "down"):
        raise HTTPException(400, "dir deve ser 'up' ou 'down'")
    raw = run_sql(f"SELECT id, ordem FROM {T_PRIO}")
    rows = [{"id": r["id"], "ordem": int(r["ordem"])} for r in raw]
    pair = neighbor_swap(rows, pid, body.dir)
    if pair is None:
        return {"ok": True}  # já é a ponta ou id ausente -> no-op
    cur, nb = pair
    run_sql(f"UPDATE {T_PRIO} SET ordem = {nb['ordem']} WHERE id = {sql_lit(cur['id'])}", want_rows=False)
    run_sql(f"UPDATE {T_PRIO} SET ordem = {cur['ordem']} WHERE id = {sql_lit(nb['id'])}", want_rows=False)
    return {"ok": True}


@app.delete("/api/prioridades/{pid}")
def prioridades_delete(pid: str):
    _ensure_prio_table()
    cur = run_sql(f"SELECT id FROM {T_PRIO} WHERE id = {sql_lit(pid)}")
    if not cur:
        raise HTTPException(404, "prioridade não encontrada")
    run_sql(f"DELETE FROM {T_PRIO} WHERE id = {sql_lit(pid)}", want_rows=False)
    return {"ok": True}
```

- [ ] **Step 5: Compilar (gate determinístico — não executa imports/Databricks)**

Run: `cd egps_analysis/app/backend && python3 -m py_compile main.py prioridades_logic.py && echo COMPILE_OK`
Expected: `COMPILE_OK` (sem SyntaxError).

- [ ] **Step 6: Confirmar que o publish não referencia a tabela nova**

Run: `cd egps_analysis && grep -c "sas_egp_prioridades" publish_to_databricks.py || true`
Expected: `0` (o publish não toca a tabela — segurança da spec §9).

- [ ] **Step 7: Commit**
```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app/back): endpoints CRUD + reorder da aba Prioridades"
```

---

### Task 3: Tipos + cliente HTTP no front

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/api.ts`

- [ ] **Step 1: Adicionar os tipos** ao final de `src/types.ts`:
```typescript
export interface Prioridade {
  id: string;
  ordem: number;
  projeto: string;
  vinculado: boolean;
  status: string;
  responsavel: string | null;
  justificativa: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
  area?: string | null;
  onda?: string | null;
}

export interface PrioridadeCreate {
  projeto: string;
  vinculado: boolean;
  status: string;
  responsavel: string | null;
  justificativa: string | null;
}

export interface PrioridadePatch {
  projeto?: string;
  vinculado?: boolean;
  status?: string;
  responsavel?: string | null;
  justificativa?: string | null;
}
```

- [ ] **Step 2: Importar os tipos** em `src/api.ts` — adicionar à lista de import de `./types` os nomes `Prioridade, PrioridadeCreate, PrioridadePatch`. O bloco de import passa a ser:
```typescript
import type {
  AppConfig, Filters, InputRow, InputsResponse, Metrics,
  LineageNode, LineagePayload, EgpDetail, WaveRow, AuditRow, ReadinessRow, ResumoPayload,
  Prioridade, PrioridadeCreate, PrioridadePatch,
} from "./types";
```

- [ ] **Step 3: Adicionar o objeto `prioridades`** ao objeto `api` (logo após a linha `resumo: () => fetch("api/resumo").then(json<ResumoPayload>),`):
```typescript
  prioridades: {
    list: () => fetch("api/prioridades").then(json<{ rows: Prioridade[] }>),
    create: (body: PrioridadeCreate) =>
      fetch("api/prioridades", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(json<Prioridade>),
    update: (id: string, patch: PrioridadePatch) =>
      fetch(`api/prioridades/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }).then(json<Prioridade>),
    move: (id: string, dir: "up" | "down") =>
      fetch(`api/prioridades/${encodeURIComponent(id)}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir }),
      }).then(json<{ ok: boolean }>),
    remove: (id: string) =>
      fetch(`api/prioridades/${encodeURIComponent(id)}`, { method: "DELETE" }).then(json<{ ok: boolean }>),
  },
```

- [ ] **Step 4: Build verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: sem erros (tipos/exports novos são usados pelo objeto `api`; nada quebra).

- [ ] **Step 5: Commit**
```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app/front): tipos + cliente HTTP da aba Prioridades"
```

---

### Task 4: Filtro puro do picker — TDD

**Files:**
- Create: `egps_analysis/app/frontend/src/prioridades.ts`
- Test: `egps_analysis/app/frontend/prioridades.test.mts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `egps_analysis/app/frontend/prioridades.test.mts`:
```typescript
import assert from "node:assert/strict";
import { filterEgps } from "./src/prioridades.ts";

const nodes = [
  { projeto: "PROJ_RISCOS_PJ", area: "Riscos", onda: "Onda 2", escopo_indi: true, n_inputs: 0, n_outputs: 0 },
  { projeto: "PROJ_TI_EXTRACAO", area: "TI", onda: "Onda 1", escopo_indi: true, n_inputs: 0, n_outputs: 0 },
  { projeto: "OUTRO_X", area: "X", onda: "", escopo_indi: false, n_inputs: 0, n_outputs: 0 },
];

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

check("vazio -> sem resultados", () => {
  assert.deepEqual(filterEgps(nodes, ""), []);
  assert.deepEqual(filterEgps(nodes, "   "), []);
});
check("substring case-insensitive", () => {
  assert.equal(filterEgps(nodes, "risc").length, 1);
  assert.equal(filterEgps(nodes, "proj").length, 2);
  assert.equal(filterEgps(nodes, "PROJ_TI").length, 1);
});
check("respeita o limite", () => {
  assert.equal(filterEgps(nodes, "proj", 1).length, 1);
});
console.log(`\n${pass} testes OK`);
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd egps_analysis/app/frontend && node prioridades.test.mts`
Expected: FAIL — `Cannot find module './src/prioridades.ts'`.

- [ ] **Step 3: Implementar `src/prioridades.ts`**
```typescript
import type { LineageNode } from "./types";

// Filtro client-side do picker de EGPs: substring case-insensitive no nome do projeto.
// Vazio -> lista vazia (não mostra dropdown). Limita o nº de resultados exibidos.
export function filterEgps(nodes: LineageNode[], q: string, limit = 20): LineageNode[] {
  const s = q.trim().toLowerCase();
  if (!s) return [];
  return nodes.filter((n) => n.projeto.toLowerCase().includes(s)).slice(0, limit);
}
```

- [ ] **Step 4: Rodar e confirmar passa**

Run: `cd egps_analysis/app/frontend && node prioridades.test.mts`
Expected: `3 testes OK`, exit 0.

- [ ] **Step 5: Build verde** (garante que `prioridades.ts` type-checa no `tsc`)

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: sem erros.

- [ ] **Step 6: Commit**
```bash
git add egps_analysis/app/frontend/src/prioridades.ts egps_analysis/app/frontend/prioridades.test.mts
git commit -m "feat(app/front): filtro puro do picker de EGPs + teste"
```

---

### Task 5: Componente `PrioridadesView`

**Files:**
- Create: `egps_analysis/app/frontend/src/components/PrioridadesView.tsx`

- [ ] **Step 1: Criar o componente** `egps_analysis/app/frontend/src/components/PrioridadesView.tsx`:
```tsx
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LineageNode, Prioridade } from "../types";
import { filterEgps } from "../prioridades";

const STATUS: string[] = ["A fazer", "Em andamento", "Concluído", "Descartado"];
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const stClass = (s: string) =>
  s === "Concluído" ? "st-ok"
  : s === "Em andamento" ? "st-wip"
  : s === "Descartado" ? "st-muted"
  : "st-todo";

export function PrioridadesView() {
  const [rows, setRows] = useState<Prioridade[]>([]);
  const [egps, setEgps] = useState<LineageNode[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // formulário de adicionar
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<LineageNode | null>(null);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("A fazer");
  const [resp, setResp] = useState("");
  const [just, setJust] = useState("");

  const refetch = () =>
    api.prioridades.list().then((r) => setRows(r.rows)).catch((e) => setErr(String(e)));

  useEffect(() => {
    api.prioridades.list()
      .then((r) => { setRows(r.rows); setLoaded(true); })
      .catch((e) => { setErr(String(e)); setLoaded(true); });
    api.lineageSearch("", "", "", 5000).then((r) => setEgps(r.rows)).catch(() => setEgps([]));
  }, []);

  const matches = useMemo(() => filterEgps(egps, q), [egps, q]);
  const projeto = picked ? picked.projeto : q.trim();
  const canAdd = projeto.length > 0;

  const add = async () => {
    if (!canAdd) return;
    try {
      await api.prioridades.create({
        projeto, vinculado: !!picked, status,
        responsavel: resp.trim() || null, justificativa: just.trim() || null,
      });
      setQ(""); setPicked(null); setOpen(false); setStatus("A fazer"); setResp(""); setJust("");
      await refetch();
    } catch (e) { setErr(String(e)); }
  };

  const patch = async (id: string, p: Partial<Prioridade>) => {
    try { await api.prioridades.update(id, p); await refetch(); }
    catch (e) { setErr(String(e)); }
  };
  const move = async (id: string, dir: "up" | "down") => {
    try { await api.prioridades.move(id, dir); await refetch(); }
    catch (e) { setErr(String(e)); }
  };
  const remove = async (id: string, name: string) => {
    if (!window.confirm(`Remover "${shortName(name)}" da lista de prioridades?`)) return;
    try { await api.prioridades.remove(id); await refetch(); }
    catch (e) { setErr(String(e)); }
  };

  return (
    <div className="prio">
      <div className="prio-add">
        <div style={{ position: "relative" }}>
          <input
            className="q"
            placeholder="buscar EGP ou digitar nome livre…"
            value={picked ? shortName(picked.projeto) : q}
            onChange={(e) => { setPicked(null); setQ(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          />
          {open && !picked && matches.length > 0 && (
            <ul className="prio-drop">
              {matches.map((n) => (
                <li key={n.projeto} onMouseDown={() => { setPicked(n); setOpen(false); }}>
                  <span>{shortName(n.projeto)}</span>
                  <span className="meta">{n.area}{n.onda ? ` · ${n.onda}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input placeholder="responsável" value={resp} onChange={(e) => setResp(e.target.value)} />
        <input placeholder="justificativa" value={just} onChange={(e) => setJust(e.target.value)} style={{ minWidth: 200 }} />
        <button disabled={!canAdd} onClick={add}>+ Adicionar</button>
      </div>

      {err && <div className="error">{err}</div>}
      {loaded && rows.length === 0 && (
        <div className="empty">Nenhum EGP priorizado ainda. Use o campo acima para adicionar.</div>
      )}

      {rows.length > 0 && (
        <div className="prio-table">
          <div className="prio-thead">
            <div>#</div><div>EGP</div><div>Status</div><div>Responsável</div><div>Justificativa</div><div></div>
          </div>
          <div className="prio-tbody">
            {rows.map((r, i) => (
              <div key={r.id} className="prio-trow">
                <div className="prio-ord">
                  <span>{i + 1}</span>
                  <button disabled={i === 0} title="subir" onClick={() => move(r.id, "up")}>↑</button>
                  <button disabled={i === rows.length - 1} title="descer" onClick={() => move(r.id, "down")}>↓</button>
                </div>
                <div className="prio-egp" title={r.projeto}>
                  {shortName(r.projeto)}
                  {r.vinculado
                    ? <span className="sub">{r.area ?? "—"}{r.onda ? ` · ${r.onda}` : ""}</span>
                    : <span className="tag free">livre</span>}
                </div>
                <div>
                  <select className={stClass(r.status)} value={r.status}
                    onChange={(e) => patch(r.id, { status: e.target.value })}>
                    {STATUS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <input
                    key={`resp-${r.id}-${r.responsavel ?? ""}`}
                    defaultValue={r.responsavel ?? ""}
                    placeholder="—"
                    onBlur={(e) => { if (e.target.value !== (r.responsavel ?? "")) patch(r.id, { responsavel: e.target.value }); }}
                  />
                </div>
                <div>
                  <input
                    key={`just-${r.id}-${r.justificativa ?? ""}`}
                    defaultValue={r.justificativa ?? ""}
                    placeholder="—"
                    onBlur={(e) => { if (e.target.value !== (r.justificativa ?? "")) patch(r.id, { justificativa: e.target.value }); }}
                  />
                </div>
                <div><button className="prio-del" title="excluir" onClick={() => remove(r.id, r.projeto)}>🗑</button></div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Por que `defaultValue` + `key` (não controlled + onChange):** com input controlado espelhando cada tecla no estado, o `onBlur` que compara "mudou?" contra o valor da linha sempre veria o valor já atualizado → nunca persistiria. Input **não-controlado** (`defaultValue`) mantém `r.responsavel`/`r.justificativa` no valor do servidor durante a digitação, então a comparação no blur é válida; a `key` inclui o valor salvo, forçando remontar o input quando o `refetch` traz um valor novo.

- [ ] **Step 2: Build verde** (componente ainda não roteado, mas precisa type-checar; tsc só inclui arquivos alcançáveis a partir do entry — então importe-o no App.tsx no mesmo commit OU verifique aqui via referência temporária). Para manter o passo isolado, apenas garanta que o arquivo compila junto do build após a Task 6. Aqui rode:

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit -p tsconfig.json`
Expected: sem erros. (Se o `tsc` não “ver” o arquivo por não estar importado, ele ainda assim é type-checado por estar em `src/` com o `include` padrão do projeto.)

- [ ] **Step 3: Commit**
```bash
git add egps_analysis/app/frontend/src/components/PrioridadesView.tsx
git commit -m "feat(app/front): componente PrioridadesView (CRUD + reorder)"
```

---

### Task 6: Rotear a aba + CSS

**Files:**
- Modify: `egps_analysis/app/frontend/src/App.tsx`
- Modify: `egps_analysis/app/frontend/src/styles.css`

- [ ] **Step 1: Importar o componente** em `src/App.tsx`, logo após `import { ResumoView } from "./components/ResumoView";`:
```tsx
import { PrioridadesView } from "./components/PrioridadesView";
```

- [ ] **Step 2: Adicionar `"prioridades"` ao tipo `View`** (após `"egp"`):
```tsx
type View = "resumo" | "monitor" | "egp" | "prioridades" | "readiness" | "waves" | "lineage" | "history";
```

- [ ] **Step 3: Adicionar a aba ao array `TABS`** — inserir logo após a linha `{ id: "egp", label: "EGPs", slug: "egps" },`:
```tsx
  { id: "prioridades", label: "Prioridades", slug: "prioridades" },
```

- [ ] **Step 4: Renderizar a view** — adicionar logo após a linha `{view === "egp" && <EgpView cfg={cfg} />}`:
```tsx
      {view === "prioridades" && <PrioridadesView />}
```

- [ ] **Step 5: Adicionar as classes** ao final de `src/styles.css`:
```css
/* aba Prioridades */
.prio { flex: 1; display: flex; flex-direction: column; min-height: 0; gap: 10px; }
.prio-add { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.prio-add input, .prio-add select { background: var(--panel2); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font-size: 12px; }
.prio-add .q { min-width: 240px; }
.prio-add button { background: var(--accent); color: var(--on-accent); border: 0; border-radius: 6px; padding: 7px 14px; font-size: 12px; cursor: pointer; }
.prio-add button:disabled { opacity: .5; cursor: default; }
.prio-drop { position: absolute; z-index: 20; top: 38px; left: 0; margin: 0; padding: 4px; list-style: none; max-height: 280px; overflow: auto; width: 360px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 8px 24px rgba(0, 0, 0, .4); }
.prio-drop li { padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12px; display: flex; gap: 8px; align-items: center; }
.prio-drop li:hover { background: var(--panel2); }
.prio-drop .meta { margin-left: auto; color: var(--mut); font-size: 11px; }
.prio-table { flex: 1; display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; min-height: 0; }
.prio-thead, .prio-trow { display: grid; grid-template-columns: 96px minmax(220px, 2fr) 150px 1fr 1.6fr 64px; align-items: center; }
.prio-thead { background: var(--panel2); border-bottom: 1px solid var(--line); font-size: 11px; color: var(--mut); text-transform: uppercase; letter-spacing: .4px; }
.prio-thead > div, .prio-trow > div { padding: 5px 8px; overflow: hidden; }
.prio-tbody { flex: 1; overflow: auto; min-height: 0; }
.prio-trow { border-bottom: 1px solid var(--line-soft); }
.prio-trow:hover { background: var(--hover); }
.prio-ord { display: flex; align-items: center; gap: 6px; }
.prio-ord button { background: transparent; color: var(--mut); border: 1px solid var(--line); border-radius: 5px; cursor: pointer; font-size: 11px; line-height: 1; padding: 2px 5px; }
.prio-ord button:hover { border-color: var(--mut); color: var(--ink); }
.prio-ord button:disabled { opacity: .35; cursor: default; }
.prio-egp { font-weight: 600; white-space: nowrap; text-overflow: ellipsis; }
.prio-egp .sub { color: var(--mut); font-weight: 400; font-size: 11px; margin-left: 6px; }
.tag.free { background: var(--tone-ext-bg); color: var(--tone-wip-fg); }
.prio-trow select, .prio-trow input { width: 100%; background: transparent; color: var(--ink); border: 1px solid transparent; border-radius: 5px; padding: 4px 6px; font-size: 12px; }
.prio-trow select:hover, .prio-trow input:hover { border-color: var(--line); }
.prio-trow select:focus, .prio-trow input:focus { border-color: var(--accent); background: var(--panel2); outline: none; }
.prio-trow select.st-ok { color: var(--ok); }
.prio-trow select.st-wip { color: var(--warn); }
.prio-trow select.st-todo { color: var(--danger-soft); }
.prio-trow select.st-muted { color: var(--mut); }
.prio-del { background: transparent; border: 0; color: var(--mut); cursor: pointer; font-size: 14px; }
.prio-del:hover { color: var(--danger); }
```

- [ ] **Step 6: Build verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: sem erros; bundle gerado em `../static/`.

- [ ] **Step 7: Commit** (inclui o bundle estático regerado)
```bash
git add egps_analysis/app/frontend/src/App.tsx egps_analysis/app/frontend/src/styles.css egps_analysis/app/static
git commit -m "feat(app/front): roteia aba Prioridades + estilos"
```

---

### Task 7: Operação — rebuild + deploy (gate humano)

**Files:** nenhum (operação; disparar só com OK do usuário).

- [ ] **Step 1: Rebuild + sync + deploy**
```bash
cd egps_analysis/app/frontend && npm run build && cd ..
databricks sync . /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas \
  --exclude 'frontend/node_modules/**' --exclude '.databricks/**' --profile bv
databricks apps deploy monitoramento-sas \
  --source-code-path /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas --profile bv
```
Expected: deployment `SUCCEEDED`.

- [ ] **Step 2: Checagem manual** (hard-refresh) na aba **Prioridades**:
  - Adicionar um EGP **vinculado** (escolhido no dropdown) → mostra `área · onda`; e um **livre** (texto sem selecionar) → tag "livre".
  - Editar status (select), responsável e justificativa (sair do campo salva); recarregar e conferir persistência.
  - Reordenar com ↑/↓ nas pontas (1º não sobe, último não desce) e no meio; recarregar e conferir a ordem.
  - Excluir com confirmação.
  - Conferir legibilidade no **tema claro** (pills/inputs/dropdown).
  - 1ª carga sem dados mostra o estado vazio.

---

## Fora do plano
Log de auditoria dedicado; gating por papel; data-alvo/observação separada; renumerar `ordem`; drag-and-drop; edição inline do nome do EGP (o endpoint aceita, a UI não expõe).

## Self-review (preenchido)

**Cobertura do spec:**
- §4 tabela/colunas → Task 2 (DDL em `_ensure_prio_table`, colunas batem 1:1). ✓
- §5 endpoints (GET/POST/PATCH/move/DELETE, validação, carimbos, join área/onda) → Task 2. ✓
- §5 funções puras (`valid_status`/`next_ordem`/`neighbor_swap`) → Task 1. ✓
- §6 front (types, api, PrioridadesView com picker híbrido, inline edit, ↑/↓, excluir, estado vazio) → Tasks 3–6. ✓
- §6 filtro puro do picker → Task 4. ✓
- §8 testes (puros backend + front; manual) → Tasks 1, 4, 7. ✓
- §9 segurança do publish (grep) → Task 2 Step 6. ✓
- §2 aba após "EGPs", hard delete + confirm, sem audit → Tasks 6, 5, (omitido por design). ✓

**Placeholders:** nenhum; todo passo de código mostra o código completo; comandos têm resultado esperado.

**Consistência de tipos/nomes:** `Prioridade`/`PrioridadeCreate`/`PrioridadePatch` (Task 3) são exatamente os usados em `api.prioridades` (Task 3) e no `PrioridadesView` (Task 5). `filterEgps` (Task 4) é importado de `../prioridades` no componente (Task 5). Os campos da `_prio_out` (Task 2) batem com a interface `Prioridade` (Task 3): `id, ordem, projeto, vinculado, status, responsavel, justificativa, created_by/at, updated_by/at, area, onda`. `STATUS_PRIO` (backend, Task 1) e o array `STATUS` (front, Task 5) listam os mesmos 4 valores. Rotas `/api/prioridades`, `/api/prioridades/{pid}`, `/api/prioridades/{pid}/move` batem entre backend (Task 2) e cliente (Task 3).
